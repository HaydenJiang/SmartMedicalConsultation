"""
Symptom Entity Extractor
Uses LLM to extract structured symptom information from raw text.
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
from src.extraction.schemas import (
    SymptomEntity,
    SeverityLevel,
)

logger = setup_logger(__name__, "extraction.log")


class SymptomExtractionOutput(BaseModel):
    """症状抽取输出模型"""
    symptoms: list[dict] = Field(
        default_factory=list,
        description="症状列表，每项包含 name, description, severity"
    )


class SymptomExtractor:
    """
    症状实体抽取器

    从原始医疗文本中抽取症状信息。

    Usage:
        >>> extractor = SymptomExtractor()
        >>> symptoms = extractor.extract("患者主诉头痛、头晕，伴有恶心...")
        >>> for s in symptoms:
        ...     print(f"{s.name}: {s.severity}")
    """

    def __init__(self, temperature: float = 0.1):
        """
        初始化抽取器

        Args:
            temperature: LLM 温度参数
        """
        self.llm = get_llm(temperature=temperature)

        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一个专业的医疗信息抽取助手。请从以下文本中提取症状信息。

要求：
1. 症状名称使用标准医学术语
2. 严重程度根据描述判断：low（轻微）、medium（中等）、high（严重）
3. 如果没有明确描述严重程度，默认为 medium
4. 严格按照 JSON 格式输出"""),
            ("user", """请从以下文本中提取症状信息：

{text}

请以 JSON 格式输出：
{{
    "symptoms": [
        {{
            "name": "症状名称",
            "description": "症状描述（可选）",
            "severity": "low/medium/high"
        }}
    ]
}}""")
        ])

        self.chain = self.prompt | self.llm.with_structured_output(
            SymptomExtractionOutput,
            method="json_mode"
        )

    @retry_on_error(max_retries=3, delay=1.0)
    def extract(self, text: str) -> list[SymptomEntity]:
        """
        从文本中抽取症状实体

        Args:
            text: 原始医疗文本

        Returns:
            list[SymptomEntity]: 症状实体列表
        """
        logger.info(f"[EXTRACT] Starting symptom extraction, text length: {len(text)}")

        try:
            result = self.chain.invoke({"text": text})

            symptoms = []
            for s in result.symptoms:
                severity_str = s.get("severity", "medium")
                try:
                    severity = SeverityLevel(severity_str)
                except ValueError:
                    severity = SeverityLevel.MEDIUM

                symptom = SymptomEntity(
                    name=s.get("name", ""),
                    description=s.get("description"),
                    severity=severity
                )
                symptoms.append(symptom)

            logger.info(f"[EXTRACT] Extracted {len(symptoms)} symptoms")
            return symptoms

        except ValidationError as e:
            logger.error(f"[EXTRACT] Validation error: {e}")
            raise
        except Exception as e:
            logger.error(f"[EXTRACT] Extraction failed: {e}")
            raise

    def extract_from_list(self, symptom_names: list[str]) -> list[SymptomEntity]:
        """
        从症状名称列表创建 SymptomEntity 对象

        Args:
            symptom_names: 症状名称列表

        Returns:
            list[SymptomEntity]
        """
        return [
            SymptomEntity(name=name, severity=SeverityLevel.MEDIUM)
            for name in symptom_names
            if name
        ]


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("Symptom Extractor Test")
    print("=" * 60)

    # Test 1: Create extractor
    print("\n[TEST 1] Create SymptomExtractor")
    extractor = SymptomExtractor(temperature=0.1)
    print("[PASS] SymptomExtractor created")

    # Test 2: Extract from list (no LLM call)
    print("\n[TEST 2] Extract from list")
    symptoms = extractor.extract_from_list(["头痛", "头晕", "恶心", "呕吐"])
    print(f"[PASS] Extracted {len(symptoms)} symptoms:")
    for s in symptoms:
        print(f"  - {s.name} ({s.severity})")

    print("\n" + "=" * 60)
    print("[SUCCESS] Symptom extractor tests passed!")
    print("=" * 60)
