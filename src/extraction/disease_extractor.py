"""
Disease Entity Extractor
Uses LLM to extract structured disease information from raw text.
"""

import json
import sys
from pathlib import Path

# Ensure project root is in sys.path
_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field, ValidationError
from typing import Optional

from config.settings import settings
from src.common.llm import get_extract_llm, get_llm
from src.common.logger import setup_logger
from src.common.utils import retry_on_error
from src.extraction.schemas import (
    DiseaseEntity,
    SymptomEntity,
    MedicationEntity,
    DepartmentEntity,
    ExaminationEntity,
    TreatmentEntity,
    BodyPartEntity,
    MedicalConceptEntity,
    HasSymptomRelation,
    TreatedByDrugRelation,
    BelongsToDepartmentRelation,
    NeedsExaminationRelation,
    AffectsBodyPartRelation,
    DiseaseExtractionResult,
    SeverityLevel,
    FrequencyLevel,
    EvidenceLevel,
)


# ============================================================
# Simple LLM Output Schema (for easier LLM generation)
# ============================================================

class SimpleDiseaseInfo(BaseModel):
    """Simple disease info for LLM output"""
    name: str = Field(description="疾病名称")
    description: Optional[str] = Field(default=None, description="疾病描述")
    icd_code: Optional[str] = Field(default=None, description="ICD编码")


class SimpleLLMOutput(BaseModel):
    """
    Simple output schema for LLM extraction.
    Uses string lists instead of entity objects for easier LLM generation.
    """
    disease: SimpleDiseaseInfo = Field(description="疾病基本信息")
    symptoms: list[str] = Field(default_factory=list, description="症状名称列表")
    medications: list[str] = Field(default_factory=list, description="药物名称列表")
    departments: list[str] = Field(default_factory=list, description="科室名称列表")
    examinations: list[str] = Field(default_factory=list, description="检查项目名称列表")
    treatments: list[str] = Field(default_factory=list, description="治疗方案名称列表")
    body_parts: list[str] = Field(default_factory=list, description="身体部位名称列表")

logger = setup_logger(__name__, "extraction.log")


# vLLM 微调模型专用指令：与训练数据（data/finetune/ft_extract.json）的 instruction
# 逐字一致——原 system 提示词 + JSON 字段模板合并为一条指令。训练时 (instruction, input)
# 渲染在同一侧，推理若拆成 system/user 两条消息会导致格式遵循退化（如漏逗号、JSON 畸形）。
_VLLM_EXTRACT_INSTRUCTION = """你是一个专业的医疗信息抽取助手。请从以下文本中提取疾病及其相关信息。

要求：
1. 疾病名称使用标准医学术语
2. 症状列表要完整，包含所有提到的症状
3. 科室名称使用标准科室名称（如"心血管内科"而非"心内科"）
4. 药物名称使用通用名（如"氨氯地平"而非商品名）
5. 如果没有相关信息，对应字段返回空列表
6. 严格按照 JSON 格式输出

请以 JSON 格式输出，包含以下字段：
{{
    "disease": {{
        "name": "疾病名称",
        "description": "疾病描述",
        "icd_code": "ICD编码（如知道）或 null"
    }},
    "symptoms": ["症状1", "症状2"],
    "medications": ["药物1", "药物2"],
    "departments": ["科室1"],
    "examinations": ["检查1", "检查2"],
    "treatments": ["治疗方案1"],
    "body_parts": ["身体部位1"]
}}"""


# 指令模板里的占位示例：微调模型在字段本应为空时偶尔原样回声这些占位符，
# 入图前统一过滤，避免图谱出现"治疗方案1"之类的垃圾节点
_TEMPLATE_PLACEHOLDERS = {
    "疾病名称", "疾病描述", "ICD编码（如知道）或 null",
    "症状1", "症状2", "药物1", "药物2", "科室1",
    "检查1", "检查2", "治疗方案1", "身体部位1",
}


def _drop_placeholders(items: list) -> list:
    return [s for s in items if s and s not in _TEMPLATE_PLACEHOLDERS]


# 云端主 LLM 抽取用的原版双消息提示词（EXTRACTION_MODEL_BASE_URL 留空时的默认路径）
_CLOUD_EXTRACT_SYSTEM = """你是一个专业的医疗信息抽取助手。请从以下文本中提取疾病及其相关信息。

要求：
1. 疾病名称使用标准医学术语
2. 症状列表要完整，包含所有提到的症状
3. 科室名称使用标准科室名称（如"心血管内科"而非"心内科"）
4. 药物名称使用通用名（如"氨氯地平"而非商品名）
5. 如果没有相关信息，对应字段返回空列表
6. 严格按照 JSON 格式输出"""

_CLOUD_EXTRACT_USER = """请从以下文本中提取疾病信息：

{text}

请以 JSON 格式输出，包含以下字段：
{{
    "disease": {{
        "name": "疾病名称",
        "description": "疾病描述",
        "icd_code": "ICD编码（如知道）或 null"
    }},
    "symptoms": ["症状1", "症状2"],
    "medications": ["药物1", "药物2"],
    "departments": ["科室1"],
    "examinations": ["检查1", "检查2"],
    "treatments": ["治疗方案1"],
    "body_parts": ["身体部位1"]
}}"""


def build_cloud_extract_chain(temperature: float = 0.1):
    """
    云端主 LLM 抽取链（json_mode 结构化输出）。

    两个用途：
    1. EXTRACTION_MODEL_BASE_URL 留空时的默认抽取路径；
    2. vLLM 微调模型抽取失败（失控生成/畸形 JSON）时的兜底，保证建图覆盖率。
    """
    prompt = ChatPromptTemplate.from_messages([
        ("system", _CLOUD_EXTRACT_SYSTEM),
        ("user", _CLOUD_EXTRACT_USER),
    ])
    return prompt | get_llm(temperature=temperature).with_structured_output(
        SimpleLLMOutput,
        method="json_mode"
    )


def _parse_simple_llm_output(raw) -> "SimpleLLMOutput":
    """
    手工解析微调模型的 JSON 输出。

    vLLM 路径不使用 with_structured_output(method="json_mode")：实测 response_format
    json_object 的引导解码会诱发微调模型失控生成（烧穿 max_tokens 后 finish_reason=length）。
    裸调用时模型稳定收尾，但常给 JSON 包 ```json 围栏，这里做容错解析。
    """
    text = raw.content if hasattr(raw, "content") else str(raw)
    text = text.strip()

    # 去掉 ```json ... ``` Markdown 围栏
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()

    # 容错截取第一个 { 到最后一个 }
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"No JSON object in model output: {text[:120]!r}")

    data = json.loads(text[start:end + 1])
    return SimpleLLMOutput(**data)


class DiseaseExtractor:
    """
    疾病实体抽取器

    从原始医疗文本中抽取疾病及其相关实体和关系。

    Usage:
        >>> extractor = DiseaseExtractor()
        >>> result = extractor.extract("高血压是一种以动脉血压升高为特征的疾病...")
        >>> print(result.disease.name)
        >>> print(result.symptoms)
    """

    def __init__(self, temperature: float = 0.1):
        """
        初始化抽取器

        Args:
            temperature: LLM 温度参数，抽取任务建议低温度（0.1-0.3）
        """
        # 抽取专用入口：EXTRACTION_MODEL_BASE_URL 非空走本地 vLLM 微调模型，为空自动回退云端 get_llm()
        self.llm = get_extract_llm(temperature=temperature)

        if settings.extraction_model_base_url.strip():
            # vLLM 微调模型分支：消息结构与训练数据对齐（完整 instruction 作 system，
            # 纯疾病文本作 user），裸调用 + 手工解析（json_mode 引导解码会诱发失控生成）
            self.prompt = ChatPromptTemplate.from_messages([
                ("system", _VLLM_EXTRACT_INSTRUCTION),
                ("user", "{text}"),
            ])
            self.chain = self.prompt | self.llm | _parse_simple_llm_output
        else:
            # 云端主 LLM 分支：原有双消息提示词 + json_mode 结构化输出
            self.prompt = ChatPromptTemplate.from_messages([
                ("system", _CLOUD_EXTRACT_SYSTEM),
                ("user", _CLOUD_EXTRACT_USER),
            ])
            self.chain = self.prompt | self.llm.with_structured_output(
                SimpleLLMOutput,
                method="json_mode"
            )

    def _convert_to_result(self, simple: SimpleLLMOutput) -> DiseaseExtractionResult:
        """Convert simple LLM output to full DiseaseExtractionResult"""
        # Build disease entity
        disease = DiseaseEntity(
            name=simple.disease.name,
            description=simple.disease.description,
            icd_code=simple.disease.icd_code,
        )

        # 各类实体统一过滤模板占位符回声（如"治疗方案1"）
        symptoms = [SymptomEntity(name=s) for s in _drop_placeholders(simple.symptoms)]
        medications = [MedicationEntity(name=m) for m in _drop_placeholders(simple.medications)]
        departments = [DepartmentEntity(name=d) for d in _drop_placeholders(simple.departments)]
        examinations = [ExaminationEntity(name=e) for e in _drop_placeholders(simple.examinations)]
        treatments = [TreatmentEntity(name=t) for t in _drop_placeholders(simple.treatments)]
        body_parts = [BodyPartEntity(name=bp) for bp in _drop_placeholders(simple.body_parts)]

        # Build relations
        has_symptom_relations = [
            HasSymptomRelation(disease_name=disease.name, symptom_name=s.name, frequency=FrequencyLevel.COMMON)
            for s in symptoms
        ]

        treated_by_relations = [
            TreatedByDrugRelation(disease_name=disease.name, drug_name=m.name, evidence_level=EvidenceLevel.B)
            for m in medications
        ]

        department_relations = [
            BelongsToDepartmentRelation(disease_name=disease.name, department_name=d.name, priority=1)
            for d in departments
        ]

        examination_relations = [
            NeedsExaminationRelation(disease_name=disease.name, examination_name=e.name, necessity="recommended")
            for e in examinations
        ]

        body_part_relations = [
            AffectsBodyPartRelation(disease_name=disease.name, body_part_name=bp.name)
            for bp in body_parts
        ]

        return DiseaseExtractionResult(
            disease=disease,
            symptoms=symptoms,
            medications=medications,
            departments=departments,
            examinations=examinations,
            treatments=treatments,
            body_parts=body_parts,
            has_symptom_relations=has_symptom_relations,
            treated_by_relations=treated_by_relations,
            department_relations=department_relations,
            examination_relations=examination_relations,
            body_part_relations=body_part_relations,
            extraction_confidence=0.9
        )

    @retry_on_error(max_retries=3, delay=1.0)
    def extract(self, text: str) -> DiseaseExtractionResult:
        """
        从文本中抽取疾病实体

        Args:
            text: 原始医疗文本

        Returns:
            DiseaseExtractionResult: 包含疾病及所有相关实体和关系

        Raises:
            ValidationError: LLM 返回格式错误（会自动重试）
        """
        logger.info(f"[EXTRACT] Starting disease extraction, text length: {len(text)}")

        try:
            # Invoke the chain - returns SimpleLLMOutput
            simple_result = self.chain.invoke({"text": text})

            # Convert to full DiseaseExtractionResult
            result = self._convert_to_result(simple_result)

            # Validate and log
            logger.info(f"[EXTRACT] Disease: {result.disease.name}")
            logger.info(f"[EXTRACT] Symptoms: {len(result.symptoms)}")
            logger.info(f"[EXTRACT] Medications: {len(result.medications)}")
            logger.info(f"[EXTRACT] Departments: {len(result.departments)}")

            return result

        except ValidationError as e:
            logger.error(f"[EXTRACT] Validation error: {e}")
            raise
        except Exception as e:
            logger.error(f"[EXTRACT] Extraction failed: {e}")
            raise

    def extract_from_dict(self, data: dict) -> DiseaseExtractionResult:
        """
        从字典数据创建 DiseaseExtractionResult

        Args:
            data: 包含疾病信息的字典

        Returns:
            DiseaseExtractionResult
        """
        # Build disease entity
        disease = DiseaseEntity(
            name=data.get("disease", {}).get("name", ""),
            description=data.get("disease", {}).get("description"),
            icd_code=data.get("disease", {}).get("icd_code"),
        )

        # Build symptom entities
        symptoms = [
            SymptomEntity(name=s)
            for s in data.get("symptoms", [])
        ]

        # Build medication entities
        medications = [
            MedicationEntity(name=m)
            for m in data.get("medications", [])
        ]

        # Build department entities
        departments = [
            DepartmentEntity(name=d)
            for d in data.get("departments", [])
        ]

        # Build examination entities
        examinations = [
            ExaminationEntity(name=e)
            for e in data.get("examinations", [])
        ]

        # Build treatment entities
        treatments = [
            TreatmentEntity(name=t)
            for t in data.get("treatments", [])
        ]

        # Build body part entities
        body_parts = [
            BodyPartEntity(name=bp)
            for bp in data.get("body_parts", [])
        ]

        # Build relations
        has_symptom_relations = [
            HasSymptomRelation(
                disease_name=disease.name,
                symptom_name=s.name,
                frequency=FrequencyLevel.COMMON
            )
            for s in symptoms
        ]

        treated_by_relations = [
            TreatedByDrugRelation(
                disease_name=disease.name,
                drug_name=m.name,
                evidence_level=EvidenceLevel.B
            )
            for m in medications
        ]

        department_relations = [
            BelongsToDepartmentRelation(
                disease_name=disease.name,
                department_name=d.name,
                priority=1
            )
            for d in departments
        ]

        examination_relations = [
            NeedsExaminationRelation(
                disease_name=disease.name,
                examination_name=e.name,
                necessity="recommended"
            )
            for e in examinations
        ]

        body_part_relations = [
            AffectsBodyPartRelation(
                disease_name=disease.name,
                body_part_name=bp.name
            )
            for bp in body_parts
        ]

        return DiseaseExtractionResult(
            disease=disease,
            symptoms=symptoms,
            medications=medications,
            departments=departments,
            examinations=examinations,
            treatments=treatments,
            body_parts=body_parts,
            has_symptom_relations=has_symptom_relations,
            treated_by_relations=treated_by_relations,
            department_relations=department_relations,
            examination_relations=examination_relations,
            body_part_relations=body_part_relations,
            extraction_confidence=0.9
        )


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("Disease Extractor Test")
    print("=" * 60)

    # Test 1: Create extractor
    print("\n[TEST 1] Create DiseaseExtractor")
    extractor = DiseaseExtractor(temperature=0.1)
    print("[PASS] DiseaseExtractor created")

    # Test 2: Extract from dict (no LLM call)
    print("\n[TEST 2] Extract from dict")
    test_data = {
        "disease": {
            "name": "高血压",
            "description": "以体循环动脉血压增高为主要特征的临床综合征",
            "icd_code": "I10"
        },
        "symptoms": ["头痛", "头晕", "心悸"],
        "medications": ["氨氯地平", "缬沙坦"],
        "departments": ["心血管内科"],
        "examinations": ["血压测量", "心电图"],
        "treatments": ["药物治疗", "生活方式干预"],
        "body_parts": ["心脏", "血管"]
    }

    result = extractor.extract_from_dict(test_data)
    print(f"[PASS] Disease: {result.disease.name} ({result.disease.icd_code})")
    print(f"[PASS] Symptoms: {[s.name for s in result.symptoms]}")
    print(f"[PASS] Medications: {[m.name for m in result.medications]}")
    print(f"[PASS] Departments: {[d.name for d in result.departments]}")
    print(f"[PASS] HAS_SYMPTOM relations: {len(result.has_symptom_relations)}")
    print(f"[PASS] TREATED_BY_MEDICATION relations: {len(result.treated_by_relations)}")

    print("\n" + "=" * 60)
    print("[SUCCESS] Disease extractor tests passed!")
    print("=" * 60)
