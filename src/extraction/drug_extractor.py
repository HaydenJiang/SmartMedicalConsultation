"""
Drug/Medication Entity Extractor
Uses LLM to extract structured medication information from raw text.
"""

import sys
from pathlib import Path

# Ensure project root is in sys.path
_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field, ValidationError

from config.settings import settings
from src.common.llm import get_llm
from src.common.logger import setup_logger
from src.common.utils import retry_on_error
from src.extraction.schemas import MedicationEntity

logger = setup_logger(__name__, "extraction.log")


class DrugExtractionOutput(BaseModel):
    """药物抽取输出模型"""
    medications: list[dict] = Field(
        default_factory=list,
        description="药物列表，每项包含 name, category, side_effects, contraindications"
    )


class DrugExtractor:
    """
    药物实体抽取器

    从原始医疗文本中抽取药物信息。

    Usage:
        >>> extractor = DrugExtractor()
        >>> drugs = extractor.extract("常用药物包括氨氯地平、缬沙坦...")
        >>> for d in drugs:
        ...     print(f"{d.name}: {d.category}")
    """

    def __init__(self, temperature: float = 0.1):
        """
        初始化抽取器

        Args:
            temperature: LLM 温度参数
        """
        self.llm = get_llm(temperature=temperature)

        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一个专业的医疗信息抽取助手。请从以下文本中提取药物信息。

要求：
1. 药物名称使用通用名（如"氨氯地平"而非商品名"络活喜"）
2. 药物类别使用标准分类（如"钙通道阻滞剂"、"他汀类"）
3. 副作用和禁忌症要完整列出
4. 严格按照 JSON 格式输出"""),
            ("user", """请从以下文本中提取药物信息：

{text}

请以 JSON 格式输出：
{{
    "medications": [
        {{
            "name": "药物通用名",
            "category": "药物类别",
            "side_effects": ["副作用1", "副作用2"],
            "contraindications": ["禁忌症1"]
        }}
    ]
}}""")
        ])

        self.chain = self.prompt | self.llm.with_structured_output(
            DrugExtractionOutput,
            method="json_mode"
        )

    @retry_on_error(max_retries=3, delay=1.0)
    def extract(self, text: str) -> list[MedicationEntity]:
        """
        从文本中抽取药物实体

        Args:
            text: 原始医疗文本

        Returns:
            list[MedicationEntity]: 药物实体列表
        """
        logger.info(f"[EXTRACT] Starting drug extraction, text length: {len(text)}")

        try:
            result = self.chain.invoke({"text": text})

            medications = []
            for m in result.medications:
                med = MedicationEntity(
                    name=m.get("name", ""),
                    category=m.get("category"),
                    side_effects=m.get("side_effects", []),
                    contraindications=m.get("contraindications", [])
                )
                medications.append(med)

            logger.info(f"[EXTRACT] Extracted {len(medications)} medications")
            return medications

        except ValidationError as e:
            logger.error(f"[EXTRACT] Validation error: {e}")
            raise
        except Exception as e:
            logger.error(f"[EXTRACT] Extraction failed: {e}")
            raise

    def extract_from_list(self, drug_names: list[str]) -> list[MedicationEntity]:
        """
        从药物名称列表创建 MedicationEntity 对象

        Args:
            drug_names: 药物名称列表

        Returns:
            list[MedicationEntity]
        """
        return [
            MedicationEntity(name=name)
            for name in drug_names
            if name
        ]


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("Drug Extractor Test")
    print("=" * 60)

    # Test 1: Create extractor
    print("\n[TEST 1] Create DrugExtractor")
    extractor = DrugExtractor(temperature=0.1)
    print("[PASS] DrugExtractor created")

    # Test 2: Extract from list (no LLM call)
    print("\n[TEST 2] Extract from list")
    drugs = extractor.extract_from_list(["氨氯地平", "缬沙坦", "阿司匹林"])
    print(f"[PASS] Extracted {len(drugs)} medications:")
    for d in drugs:
        print(f"  - {d.name}")

    print("\n" + "=" * 60)
    print("[SUCCESS] Drug extractor tests passed!")
    print("=" * 60)
