"""
Configuration module for SmartMedicalConsultation
"""

from .settings import settings
from .paths import (
    PROJECT_ROOT,
    DATA_DIR,
    DATA_RAW_DIR,
    DATA_PROCESSED_DIR,
    DATA_KG_DIR,
    DATA_INDEXES_DIR,
    MODELS_DIR,
    LOGS_DIR,
)

__all__ = [
    "settings",
    "PROJECT_ROOT",
    "DATA_DIR",
    "DATA_RAW_DIR",
    "DATA_PROCESSED_DIR",
    "DATA_KG_DIR",
    "DATA_INDEXES_DIR",
    "MODELS_DIR",
    "LOGS_DIR",
]
