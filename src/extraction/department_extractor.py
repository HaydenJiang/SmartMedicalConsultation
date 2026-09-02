"""
Department Entity Extractor
Uses LLM to extract structured department information from raw text.
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
from src.extraction.schemas import DepartmentEntity

logger = setup_logger(__name__, "extraction.log")


# Standard department name mapping
DEPARTMENT_MAPPING = {
    "心内科": "心血管内科",
    "心脏内科": "心血管内科",
    "神经科": "神经内科",
    "消化科": "消化内科",
    "呼吸科": "呼吸内科",
    "内分泌": "内分泌科",
    "骨科": "骨科",
    "外科": "外科",
    "内科": "内科",
}


class DepartmentExtractionOutput(BaseModel):
    """科室抽取输出模型"""
    departments: list[dict] = Field(
        default_factory=list,
        description="科室列表，每项包含 name, description"
    )


class DepartmentExtractor:
    """
    科室实体抽取器

    从原始医疗文本中抽取科室信息。

    Usage:
        >>> extractor = DepartmentExtractor()
        >>> depts = extractor.extract("建议到心血管内科就诊...")
        >>> for d in depts:
        ...     print(d.name)
    """

    def __init__(self, temperature: float = 0.1):
        """
        初始化抽取器

        Args:
            temperature: LLM 温度参数
        """
        self.llm = get_llm(temperature=temperature)

        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一个专业的医疗信息抽取助手。请从以下文本中提取科室信息。

要求：
1. 科室名称使用标准名称（如"心血管内科"而非"心内科"）
2. 如果文本中使用非标准名称，请转换为标准名称
3. 严格按照 JSON 格式输出"""),
            ("user", """请从以下文本中提取科室信息：

{text}

请以 JSON 格式输出：
{{
    "departments": [
        {{
            "name": "科室标准名称",
            "description": "科室职责描述（可选）"
        }}
    ]
}}""")
        ])

        self.chain = self.prompt | self.llm.with_structured_output(
            DepartmentExtractionOutput,
            method="json_mode"
        )

    @retry_on_error(max_retries=3, delay=1.0)
    def extract(self, text: str) -> list[DepartmentEntity]:
        """
        从文本中抽取科室实体

        Args:
            text: 原始医疗文本

        Returns:
            list[DepartmentEntity]: 科室实体列表
        """
        logger.info(f"[EXTRACT] Starting department extraction, text length: {len(text)}")

        try:
            result = self.chain.invoke({"text": text})

            departments = []
            for d in result.departments:
                name = self._standardize_name(d.get("name", ""))
                dept = DepartmentEntity(
                    name=name,
                    description=d.get("description")
                )
                departments.append(dept)

            logger.info(f"[EXTRACT] Extracted {len(departments)} departments")
            return departments

        except ValidationError as e:
            logger.error(f"[EXTRACT] Validation error: {e}")
            raise
        except Exception as e:
            logger.error(f"[EXTRACT] Extraction failed: {e}")
            raise

    def _standardize_name(self, name: str) -> str:
        """
        标准化科室名称

        Args:
            name: 原始科室名称

        Returns:
            标准化后的科室名称
        """
        if not name:
            return ""

        name = name.strip()

        # Check exact match
        if name in DEPARTMENT_MAPPING:
            return DEPARTMENT_MAPPING[name]

        # Check partial match
        for key, value in DEPARTMENT_MAPPING.items():
            if key in name:
                return value

        return name

    def extract_from_list(self, dept_names: list[str]) -> list[DepartmentEntity]:
        """
        从科室名称列表创建 DepartmentEntity 对象

        Args:
            dept_names: 科室名称列表

        Returns:
            list[DepartmentEntity]
        """
        return [
            DepartmentEntity(name=self._standardize_name(name))
            for name in dept_names
            if name
        ]


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("Department Extractor Test")
    print("=" * 60)

    # Test 1: Create extractor
    print("\n[TEST 1] Create DepartmentExtractor")
    extractor = DepartmentExtractor(temperature=0.1)
    print("[PASS] DepartmentExtractor created")

    # Test 2: Extract from list with standardization
    print("\n[TEST 2] Extract from list with name standardization")
    depts = extractor.extract_from_list(["心内科", "神经科", "骨科"])
    print(f"[PASS] Extracted {len(depts)} departments:")
    for d in depts:
        print(f"  - {d.name}")

    # Test 3: Name standardization
    print("\n[TEST 3] Name standardization")
    assert extractor._standardize_name("心内科") == "心血管内科"
    assert extractor._standardize_name("神经科") == "神经内科"
    assert extractor._standardize_name("骨科") == "骨科"
    print("[PASS] Name standardization works correctly")

    print("\n" + "=" * 60)
    print("[SUCCESS] Department extractor tests passed!")
    print("=" * 60)
