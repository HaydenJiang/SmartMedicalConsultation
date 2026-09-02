#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Medical Data Processor
Clean and process raw crawled data
"""

import json
import logging
import re
from pathlib import Path
from datetime import datetime
from collections import Counter

import pandas as pd

# ===== Configuration =====

PROJECT_ROOT = Path(__file__).parent.parent
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DATA_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

INPUT_FILE = DATA_RAW_DIR / "diseases.json"
OUTPUT_JSON = DATA_PROCESSED_DIR / "diseases.json"
OUTPUT_XLSX = DATA_PROCESSED_DIR / "diseases.xlsx"

# Logging setup
log_dir = PROJECT_ROOT / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "data_processor.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Department name standardization mapping
DEPARTMENT_MAPPING = {
    "就诊科": "",  # Remove incomplete department names
    "心血管内科": "心血管内科",
    "心内科": "心血管内科",
    "神经内科": "神经内科",
    "神经科": "神经内科",
    "消化内科": "消化内科",
    "呼吸内科": "呼吸内科",
    "内分泌科": "内分泌科",
    "骨科": "骨科",
    "外科": "外科",
    "内科": "内科",
}


class DataProcessor:
    """Process and clean raw medical data"""

    def __init__(self):
        self.raw_data = []
        self.cleaned_data = []
        self.stats = {
            "total_raw": 0,
            "duplicates_removed": 0,
            "empty_removed": 0,
            "cleaned": 0,
        }

    def load_raw_data(self):
        """Load raw data from JSON file"""
        if not INPUT_FILE.exists():
            logger.error(f"[ERROR] Raw data file not found: {INPUT_FILE}")
            return False

        try:
            with open(INPUT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.raw_data = data.get("diseases", [])
            self.stats["total_raw"] = len(self.raw_data)
            logger.info(f"[LOADED] {len(self.raw_data)} raw records")
            return True

        except Exception as e:
            logger.error(f"[ERROR] Failed to load raw data: {e}")
            return False

    def clean_text(self, text: str) -> str:
        """Clean text: remove extra spaces and special characters"""
        if not text:
            return ""

        # Remove extra whitespace
        text = " ".join(text.split())

        # Remove special characters (keep Chinese, English, numbers, punctuation)
        text = re.sub(r'[^\w\s一-鿿，。、；：！？""''（）《》]+', '', text)

        return text.strip()

    def standardize_department(self, dept: str) -> str:
        """Standardize department names"""
        if not dept:
            return ""

        dept = dept.strip()

        # Check if it's in our mapping
        if dept in DEPARTMENT_MAPPING:
            return DEPARTMENT_MAPPING[dept]

        # Try to find a match
        for key, value in DEPARTMENT_MAPPING.items():
            if key in dept:
                return value if value else ""

        # If no match, return as is (but cleaned)
        return self.clean_text(dept)

    def remove_duplicates(self):
        """Remove duplicate diseases based on name"""
        seen_names = set()
        unique_data = []

        for disease in self.raw_data:
            name = disease.get("name", "").strip()

            if not name:
                self.stats["empty_removed"] += 1
                continue

            if name in seen_names:
                self.stats["duplicates_removed"] += 1
                continue

            seen_names.add(name)
            unique_data.append(disease)

        self.raw_data = unique_data
        logger.info(
            f"[DEDUP] Removed {self.stats['duplicates_removed']} duplicates, "
            f"{self.stats['empty_removed']} empty records"
        )

    def clean_records(self):
        """Clean individual records"""
        cleaned = []

        for disease in self.raw_data:
            cleaned_disease = {
                "name": self.clean_text(disease.get("name", "")),
                "description": self.clean_text(disease.get("description", "")),
                "symptoms": [self.clean_text(s) for s in disease.get("symptoms", []) if s],
                "department": self.standardize_department(disease.get("department", "")),
                "treatment": self.clean_text(disease.get("treatment", "")),
                "medications": [self.clean_text(m) for m in disease.get("medications", []) if m],
                "source": disease.get("source", "unknown"),
                "url": disease.get("url", ""),
                "crawled_at": disease.get("crawled_at", ""),
            }

            # Only keep records with at least a name
            if cleaned_disease["name"]:
                cleaned.append(cleaned_disease)
                self.stats["cleaned"] += 1

        self.cleaned_data = cleaned
        logger.info(f"[CLEAN] {len(cleaned)} records cleaned")

    def generate_statistics(self):
        """Generate data statistics"""
        if not self.cleaned_data:
            logger.warning("[WARN] No cleaned data to analyze")
            return

        # Count by source
        source_counter = Counter(d["source"] for d in self.cleaned_data)

        # Count symptoms
        all_symptoms = []
        for d in self.cleaned_data:
            all_symptoms.extend(d["symptoms"])
        symptom_counter = Counter(all_symptoms)

        # Count departments
        dept_counter = Counter(d["department"] for d in self.cleaned_data if d["department"])

        # Field coverage
        fields = ["description", "symptoms", "department", "treatment", "medications"]
        coverage = {}
        for field in fields:
            count = sum(1 for d in self.cleaned_data if d.get(field))
            coverage[field] = f"{count}/{len(self.cleaned_data)} ({count/len(self.cleaned_data)*100:.1f}%)"

        # Print statistics
        logger.info("=" * 60)
        logger.info("[STATS] Data Statistics:")
        logger.info(f"  Total records: {len(self.cleaned_data)}")
        logger.info(f"  By source: {dict(source_counter)}")
        logger.info(f"  Unique symptoms: {len(symptom_counter)}")
        logger.info(f"  Unique departments: {len(dept_counter)}")
        logger.info(f"  Top 10 symptoms: {symptom_counter.most_common(10)}")
        logger.info(f"  Top 10 departments: {dept_counter.most_common(10)}")
        logger.info(f"  Field coverage: {coverage}")
        logger.info("=" * 60)

        return {
            "total": len(self.cleaned_data),
            "by_source": dict(source_counter),
            "unique_symptoms": len(symptom_counter),
            "unique_departments": len(dept_counter),
            "top_symptoms": symptom_counter.most_common(10),
            "top_departments": dept_counter.most_common(10),
            "field_coverage": coverage,
        }

    def save_json(self):
        """Save cleaned data as JSON"""
        try:
            output = {
                "metadata": {
                    "processed_at": datetime.now().isoformat(),
                    "total_diseases": len(self.cleaned_data),
                    "stats": self.stats,
                },
                "diseases": self.cleaned_data,
            }

            with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)

            logger.info(f"[SAVED] JSON saved to {OUTPUT_JSON}")

        except Exception as e:
            logger.error(f"[ERROR] Failed to save JSON: {e}")

    def save_excel(self):
        """Save cleaned data as Excel for manual review"""
        try:
            # Convert to DataFrame
            df = pd.DataFrame(self.cleaned_data)

            # Convert list fields to strings for Excel
            df["symptoms"] = df["symptoms"].apply(lambda x: "、".join(x) if x else "")
            df["medications"] = df["medications"].apply(lambda x: "、".join(x) if x else "")

            # Save to Excel
            with pd.ExcelWriter(OUTPUT_XLSX, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="Diseases")

            logger.info(f"[SAVED] Excel saved to {OUTPUT_XLSX}")

        except Exception as e:
            logger.error(f"[ERROR] Failed to save Excel: {e}")

    def process(self):
        """Run the full processing pipeline"""
        logger.info("=" * 60)
        logger.info("[START] Data Processing Pipeline")
        logger.info("=" * 60)

        # Step 1: Load raw data
        if not self.load_raw_data():
            return False

        # Step 2: Remove duplicates
        self.remove_duplicates()

        # Step 3: Clean records
        self.clean_records()

        # Step 4: Generate statistics
        stats = self.generate_statistics()

        # Step 5: Save outputs
        self.save_json()
        self.save_excel()

        logger.info("=" * 60)
        logger.info("[COMPLETE] Data Processing Summary:")
        logger.info(f"  Raw records: {self.stats['total_raw']}")
        logger.info(f"  Duplicates removed: {self.stats['duplicates_removed']}")
        logger.info(f"  Empty removed: {self.stats['empty_removed']}")
        logger.info(f"  Cleaned records: {self.stats['cleaned']}")
        logger.info("=" * 60)

        return True


def main():
    """Main entry point"""
    processor = DataProcessor()
    success = processor.process()

    if success:
        print("\n[SUCCESS] Data processing completed!")
        print(f"  JSON output: {OUTPUT_JSON}")
        print(f"  Excel output: {OUTPUT_XLSX}")
        print(f"  Log file: {log_dir / 'data_processor.log'}")
    else:
        print("\n[FAILED] Data processing failed. Check logs for details.")


if __name__ == "__main__":
    main()
