"""
Knowledge Graph Schema Definitions
Pydantic models for 8 entity types and 12 relation types.

Based on TDD.md Section: Neo4j Schema Design
"""

from typing import Optional
from enum import Enum

from pydantic import BaseModel, Field


# ============================================================
# Enums —— 统一定义于 src/knowledge_graph/schema.py（R1 名字唯一主人）
# 本文件仅转导入、不再就地定义。DiseaseRelationType 即原 RelationType
# （因与图关系契约 RelationType 重名而改名，消除导入歧义）。
# ============================================================

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.knowledge_graph.schema import (
    SeverityLevel,
    FrequencyLevel,
    EvidenceLevel,
    DiseaseRelationType,
)


# ============================================================
# 1. Entity Types (8 types)
# ============================================================

class DiseaseEntity(BaseModel):
    """
    疾病实体
    Node label: Disease
    """
    name: str = Field(
        ...,
        description="疾病名称，如：高血压、冠心病、糖尿病"
    )
    description: Optional[str] = Field(
        default=None,
        description="疾病描述，包含病因、发病机制等"
    )
    icd_code: Optional[str] = Field(
        default=None,
        description="ICD-10 国际疾病分类编码，如：I10（高血压）"
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="疾病别名，如：高血压又称'高血压病'"
    )
    created_at: Optional[str] = Field(
        default=None,
        description="创建时间戳"
    )


class SymptomEntity(BaseModel):
    """
    症状实体
    Node label: Symptom
    """
    name: str = Field(
        ...,
        description="症状名称，如：头痛、发热、咳嗽"
    )
    description: Optional[str] = Field(
        default=None,
        description="症状详细描述"
    )
    severity: SeverityLevel = Field(
        default=SeverityLevel.MEDIUM,
        description="严重程度：low（轻微）、medium（中等）、high（严重）"
    )
    duration: Optional[str] = Field(
        default=None,
        description="症状持续时间，如：急性、慢性"
    )


class MedicationEntity(BaseModel):
    """
    药物实体
    Node label: Drug
    """
    name: str = Field(
        ...,
        description="药物名称，如：氨氯地平、阿司匹林"
    )
    category: Optional[str] = Field(
        default=None,
        description="药物类别，如：钙通道阻滞剂、他汀类"
    )
    side_effects: list[str] = Field(
        default_factory=list,
        description="副作用列表，如：['脚踝水肿', '面部潮红']"
    )
    contraindications: list[str] = Field(
        default_factory=list,
        description="禁忌症列表，如：['严重低血压']"
    )
    dosage: Optional[str] = Field(
        default=None,
        description="常规剂量，如：5mg 每日一次"
    )


class DepartmentEntity(BaseModel):
    """
    科室实体
    Node label: Department
    """
    name: str = Field(
        ...,
        description="科室名称，如：心血管内科、骨科、消化内科"
    )
    description: Optional[str] = Field(
        default=None,
        description="科室职责描述"
    )
    floor_location: Optional[str] = Field(
        default=None,
        description="楼层位置，如：门诊楼3层"
    )
    parent_department: Optional[str] = Field(
        default=None,
        description="上级科室，如：内科"
    )


class ExaminationEntity(BaseModel):
    """
    检查实体
    Node label: Examination
    """
    name: str = Field(
        ...,
        description="检查名称，如：血压测量、血常规、心电图"
    )
    purpose: Optional[str] = Field(
        default=None,
        description="检查目的，如：检测血压水平"
    )
    preparation: Optional[str] = Field(
        default=None,
        description="检查前准备，如：安静休息5分钟后测量"
    )
    category: Optional[str] = Field(
        default=None,
        description="检查类别，如：实验室检查、影像学检查"
    )


class TreatmentEntity(BaseModel):
    """
    治疗方案实体
    Node label: Treatment
    """
    name: str = Field(
        ...,
        description="治疗方案名称，如：药物治疗、手术治疗"
    )
    description: Optional[str] = Field(
        default=None,
        description="治疗方案描述"
    )
    duration: Optional[str] = Field(
        default=None,
        description="治疗周期，如：长期、短期"
    )


class BodyPartEntity(BaseModel):
    """
    身体部位实体
    Node label: BodyPart
    """
    name: str = Field(
        ...,
        description="身体部位名称，如：心脏、肝脏、大脑"
    )
    description: Optional[str] = Field(
        default=None,
        description="部位描述，如：循环系统的核心器官"
    )
    system: Optional[str] = Field(
        default=None,
        description="所属系统，如：循环系统、消化系统"
    )


class MedicalConceptEntity(BaseModel):
    """
    医学概念实体
    Node label: MedicalConcept
    """
    name: str = Field(
        ...,
        description="概念名称，如：血压、血糖、胆固醇"
    )
    definition: Optional[str] = Field(
        default=None,
        description="概念定义，如：血液在血管中流动时对血管壁的压力"
    )
    normal_range: Optional[str] = Field(
        default=None,
        description="正常范围，如：收缩压90-140mmHg"
    )


# ============================================================
# 2. Relation Types (12 types)
# ============================================================

class HasSymptomRelation(BaseModel):
    """
    疾病-症状关系
    Pattern: (d:Disease)-[:HAS_SYMPTOM]->(s:Symptom)
    """
    disease_name: str = Field(..., description="疾病名称")
    symptom_name: str = Field(..., description="症状名称")
    frequency: FrequencyLevel = Field(
        default=FrequencyLevel.COMMON,
        description="症状出现频率：rare/occasional/common/very_common"
    )


class MayIndicateRelation(BaseModel):
    """
    症状-疾病关系（反向）
    Pattern: (s:Symptom)-[:MAY_INDICATE]->(d:Disease)
    """
    symptom_name: str = Field(..., description="症状名称")
    disease_name: str = Field(..., description="疾病名称")
    probability: str = Field(
        default="medium",
        description="指示概率：low/medium/high"
    )


class BelongsToDepartmentRelation(BaseModel):
    """
    疾病-科室关系
    Pattern: (d:Disease)-[:BELONGS_TO_DEPARTMENT]->(dep:Department)
    """
    disease_name: str = Field(..., description="疾病名称")
    department_name: str = Field(..., description="科室名称")
    priority: int = Field(
        default=1,
        description="推荐优先级：1（首选）2（次选）3（备选）"
    )


class TreatedByDrugRelation(BaseModel):
    """
    疾病-药物关系
    Pattern: (d:Disease)-[:TREATED_BY_MEDICATION]->(dr:Medication)
    """
    disease_name: str = Field(..., description="疾病名称")
    drug_name: str = Field(..., description="药物名称")
    evidence_level: EvidenceLevel = Field(
        default=EvidenceLevel.B,
        description="证据等级：A（强）B（中）C（弱）D（专家意见）"
    )
    is_first_line: bool = Field(
        default=False,
        description="是否一线用药"
    )


class TreatsDiseaseRelation(BaseModel):
    """
    药物-疾病关系（反向）
    Pattern: (dr:Drug)-[:TREATS_DISEASE]->(d:Disease)
    """
    drug_name: str = Field(..., description="药物名称")
    disease_name: str = Field(..., description="疾病名称")


class HasSideEffectRelation(BaseModel):
    """
    药物-副作用关系
    Pattern: (dr:Drug)-[:HAS_SIDE_EFFECT]->(s:Symptom)
    """
    drug_name: str = Field(..., description="药物名称")
    symptom_name: str = Field(..., description="副作用症状名称")
    frequency: FrequencyLevel = Field(
        default=FrequencyLevel.OCCASIONAL,
        description="副作用发生频率"
    )


class DrugInteractionRelation(BaseModel):
    """
    药物-药物相互作用
    Pattern: (dr1:Drug)-[:INTERACTS_WITH]->(dr2:Drug)
    """
    drug1_name: str = Field(..., description="药物1名称")
    drug2_name: str = Field(..., description="药物2名称")
    severity: SeverityLevel = Field(
        default=SeverityLevel.MEDIUM,
        description="相互作用严重程度：low/medium/high"
    )
    description: Optional[str] = Field(
        default=None,
        description="相互作用描述"
    )


class NeedsExaminationRelation(BaseModel):
    """
    疾病-检查关系
    Pattern: (d:Disease)-[:NEEDS_EXAMINATION]->(e:Examination)
    """
    disease_name: str = Field(..., description="疾病名称")
    examination_name: str = Field(..., description="检查名称")
    necessity: str = Field(
        default="recommended",
        description="必要性：required（必需）/recommended（推荐）/optional（可选）"
    )


class AffectsBodyPartRelation(BaseModel):
    """
    疾病-身体部位关系
    Pattern: (d:Disease)-[:AFFECTS_BODY_PART]->(bp:BodyPart)
    """
    disease_name: str = Field(..., description="疾病名称")
    body_part_name: str = Field(..., description="身体部位名称")


class ForDiseaseRelation(BaseModel):
    """
    治疗方案-疾病关系（仅抽取层建模；辅助关系，不在图谱 RelationType 契约内，不入图）
    """
    treatment_name: str = Field(..., description="治疗方案名称")
    disease_name: str = Field(..., description="疾病名称")


class HandlesDiseaseRelation(BaseModel):
    """
    科室-疾病关系（反向）
    Pattern: (dep:Department)-[:HANDLES_DISEASE]->(d:Disease)
    """
    department_name: str = Field(..., description="科室名称")
    disease_name: str = Field(..., description="疾病名称")


class DiseaseRelatedRelation(BaseModel):
    """
    疾病-疾病相关关系（仅抽取层建模；具体语义见 relation_type 字段，不入图）
    """
    disease1_name: str = Field(..., description="疾病1名称")
    disease2_name: str = Field(..., description="疾病2名称")
    relation_type: DiseaseRelationType = Field(
        default=DiseaseRelationType.COMPLICATION,
        description="关系类型：complication（并发症）/comorbidity（合并症）/causal（因果）/similar（相似）"
    )


# ============================================================
# 3. Comprehensive Extraction Result
# ============================================================

class DiseaseExtractionResult(BaseModel):
    """
    疾病抽取综合结果
    包含一个疾病及其所有相关实体和关系
    """
    # Core entity
    disease: DiseaseEntity = Field(..., description="疾病实体")

    # Related entities
    symptoms: list[SymptomEntity] = Field(
        default_factory=list,
        description="相关症状列表"
    )
    medications: list[MedicationEntity] = Field(
        default_factory=list,
        description="相关药物列表"
    )
    departments: list[DepartmentEntity] = Field(
        default_factory=list,
        description="相关科室列表"
    )
    examinations: list[ExaminationEntity] = Field(
        default_factory=list,
        description="相关检查列表"
    )
    treatments: list[TreatmentEntity] = Field(
        default_factory=list,
        description="相关治疗方案列表"
    )
    body_parts: list[BodyPartEntity] = Field(
        default_factory=list,
        description="相关身体部位列表"
    )
    concepts: list[MedicalConceptEntity] = Field(
        default_factory=list,
        description="相关医学概念列表"
    )

    # Relations
    has_symptom_relations: list[HasSymptomRelation] = Field(
        default_factory=list,
        description="疾病-症状关系"
    )
    treated_by_relations: list[TreatedByDrugRelation] = Field(
        default_factory=list,
        description="疾病-药物关系"
    )
    department_relations: list[BelongsToDepartmentRelation] = Field(
        default_factory=list,
        description="疾病-科室关系"
    )
    examination_relations: list[NeedsExaminationRelation] = Field(
        default_factory=list,
        description="疾病-检查关系"
    )
    body_part_relations: list[AffectsBodyPartRelation] = Field(
        default_factory=list,
        description="疾病-身体部位关系"
    )

    # Metadata
    source_text: Optional[str] = Field(
        default=None,
        description="原始文本来源"
    )
    extraction_confidence: float = Field(
        default=0.0,
        description="抽取置信度（0-1）"
    )


# ============================================================
# 4. Utility Functions
# ============================================================

def get_all_entity_types() -> list[type[BaseModel]]:
    """获取所有实体类型"""
    return [
        DiseaseEntity,
        SymptomEntity,
        MedicationEntity,
        DepartmentEntity,
        ExaminationEntity,
        TreatmentEntity,
        BodyPartEntity,
        MedicalConceptEntity,
    ]


def get_all_relation_types() -> list[type[BaseModel]]:
    """获取所有关系类型"""
    return [
        HasSymptomRelation,
        MayIndicateRelation,
        BelongsToDepartmentRelation,
        TreatedByDrugRelation,
        TreatsDiseaseRelation,
        HasSideEffectRelation,
        DrugInteractionRelation,
        NeedsExaminationRelation,
        AffectsBodyPartRelation,
        ForDiseaseRelation,
        HandlesDiseaseRelation,
        DiseaseRelatedRelation,
    ]


# ============================================================
# Main: Self-test
# ============================================================

if __name__ == "__main__":
    import sys
    from pathlib import Path

    # Fix Windows console encoding
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    sys.path.insert(0, str(Path(__file__).parent.parent.parent.resolve()))

    print("=" * 60)
    print("Knowledge Graph Schema Validation")
    print("=" * 60)

    # Test entity types
    print("\n[TEST 1] Entity Types (8)")
    entities = get_all_entity_types()
    print(f"  Total: {len(entities)}")
    for e in entities:
        print(f"  - {e.__name__}")
    assert len(entities) == 8, "Expected 8 entity types"

    # Test relation types
    print("\n[TEST 2] Relation Types (12)")
    relations = get_all_relation_types()
    print(f"  Total: {len(relations)}")
    for r in relations:
        print(f"  - {r.__name__}")
    assert len(relations) == 12, "Expected 12 relation types"

    # Test entity instantiation
    print("\n[TEST 3] Entity Instantiation")
    disease = DiseaseEntity(
        name="高血压",
        description="高血压是指以体循环动脉血压增高为主要特征的临床综合征",
        icd_code="I10",
        aliases=["高血压病"]
    )
    print(f"  Disease: {disease.name} ({disease.icd_code})")

    symptom = SymptomEntity(
        name="头痛",
        severity=SeverityLevel.MEDIUM
    )
    print(f"  Symptom: {symptom.name} ({symptom.severity})")

    drug = MedicationEntity(
        name="氨氯地平",
        category="钙通道阻滞剂",
        side_effects=["脚踝水肿", "面部潮红"],
        contraindications=["严重低血压"]
    )
    print(f"  Drug: {drug.name} ({drug.category})")

    dept = DepartmentEntity(
        name="心血管内科",
        description="专门治疗心脏和血管疾病"
    )
    print(f"  Department: {dept.name}")

    # Test relation instantiation
    print("\n[TEST 4] Relation Instantiation")
    rel1 = HasSymptomRelation(
        disease_name="高血压",
        symptom_name="头痛",
        frequency=FrequencyLevel.COMMON
    )
    print(f"  HAS_SYMPTOM: {rel1.disease_name} -> {rel1.symptom_name}")

    rel2 = TreatedByDrugRelation(
        disease_name="高血压",
        drug_name="氨氯地平",
        evidence_level=EvidenceLevel.A,
        is_first_line=True
    )
    print(f"  TREATED_BY_MEDICATION: {rel2.disease_name} -> {rel2.drug_name}")

    rel3 = BelongsToDepartmentRelation(
        disease_name="高血压",
        department_name="心血管内科",
        priority=1
    )
    print(f"  BELONGS_TO_DEPARTMENT: {rel3.disease_name} -> {rel3.department_name}")

    # Test comprehensive result
    print("\n[TEST 5] Comprehensive Extraction Result")
    result = DiseaseExtractionResult(
        disease=disease,
        symptoms=[symptom],
        medications=[drug],
        departments=[dept],
        has_symptom_relations=[rel1],
        treated_by_relations=[rel2],
        department_relations=[rel3],
        extraction_confidence=0.95
    )
    print(f"  Disease: {result.disease.name}")
    print(f"  Symptoms: {len(result.symptoms)}")
    print(f"  Medications: {len(result.medications)}")
    print(f"  Departments: {len(result.departments)}")
    print(f"  Confidence: {result.extraction_confidence}")

    print("\n" + "=" * 60)
    print("[SUCCESS] All schema tests passed!")
    print("=" * 60)
