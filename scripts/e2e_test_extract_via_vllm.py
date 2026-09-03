"""E2E test: DiseaseExtractor production path via vLLM (reads EXTRACTION_MODEL_BASE_URL from .env)."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from config.settings import settings
from src.extraction.disease_extractor import DiseaseExtractor

print(f"EXTRACTION_MODEL_BASE_URL = {settings.extraction_model_base_url!r}")
print(f"EXTRACTION_MODEL_NAME     = {settings.extraction_model_name!r}")

extractor = DiseaseExtractor(temperature=0.1)

text = (
    "疾病名称：糖尿病\n"
    "疾病描述：一种慢性代谢性疾病，主要特征是高血糖。\n"
    "症状：多饮、多尿、多食、体重下降\n"
    "就诊科室：内分泌科\n"
    "常用药物：二甲双胍、格列美脲"
)

result = extractor.extract(text)

print("\n===== DiseaseExtractionResult =====")
print("disease:", result.disease.name, "| icd:", result.disease.icd_code)
print("symptoms:", [s.name for s in result.symptoms])
print("medications:", [m.name for m in result.medications])
print("departments:", [d.name for d in result.departments])
print("examinations:", [e.name for e in result.examinations])
print("treatments:", [t.name for t in result.treatments])
print("body_parts:", [b.name for b in result.body_parts])
print("\n[E2E PASS] structured output parsed successfully via vLLM")
