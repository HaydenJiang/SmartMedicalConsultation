"""
Project Path Configuration
Defines all project directories and paths using pathlib.
Automatically creates necessary directories.
Cross-platform compatible (Windows/Mac/Linux).
"""

from pathlib import Path


# ===== Project Root =====
# config/ is one level deep, so parent.parent gives us the project root
PROJECT_ROOT = Path(__file__).parent.parent.resolve()


# ===== Data Directories =====
DATA_DIR = PROJECT_ROOT / "data"
DATA_RAW_DIR = DATA_DIR / "raw"                    # Raw crawled data
DATA_PROCESSED_DIR = DATA_DIR / "processed"        # Cleaned and processed data
DATA_KG_DIR = DATA_DIR / "knowledge_graph"         # Knowledge graph intermediate data
DATA_INDEXES_DIR = DATA_DIR / "indexes"            # FAISS vector indexes


# ===== Models Directory =====
MODELS_DIR = PROJECT_ROOT / "models"               # Local model storage


# ===== Logs Directory =====
LOGS_DIR = PROJECT_ROOT / "logs"                   # Application logs


# ===== Source Directories =====
SRC_DIR = PROJECT_ROOT / "src"                     # Source code root
AGENTS_DIR = SRC_DIR / "agents"                    # Agent modules
API_DIR = SRC_DIR / "api"                          # FastAPI modules
COMMON_DIR = SRC_DIR / "common"                    # Common utilities
EXTRACTION_DIR = SRC_DIR / "extraction"            # Entity extraction modules
FRONTEND_DIR = PROJECT_ROOT / "frontend"            # Vue 3 frontend (project root)
KNOWLEDGE_GRAPH_DIR = SRC_DIR / "knowledge_graph"  # Knowledge graph modules


# ===== Auto-create necessary directories =====
_dirs_to_create = [
    DATA_RAW_DIR,
    DATA_PROCESSED_DIR,
    DATA_KG_DIR,
    DATA_INDEXES_DIR,
    MODELS_DIR,
    LOGS_DIR,
]

for _dir in _dirs_to_create:
    _dir.mkdir(parents=True, exist_ok=True)


# ===== Helper Functions =====
def get_data_path(filename: str) -> Path:
    """Get full path for a file in data/ directory"""
    return DATA_DIR / filename


def get_raw_data_path(filename: str) -> Path:
    """Get full path for a file in data/raw/ directory"""
    return DATA_RAW_DIR / filename


def get_processed_data_path(filename: str) -> Path:
    """Get full path for a file in data/processed/ directory"""
    return DATA_PROCESSED_DIR / filename


def get_log_path(filename: str) -> Path:
    """Get full path for a log file"""
    return LOGS_DIR / filename


# ===== Debug: Print paths when run directly =====
if __name__ == "__main__":
    print("=" * 60)
    print("Project Path Configuration")
    print("=" * 60)
    print(f"PROJECT_ROOT:        {PROJECT_ROOT}")
    print(f"DATA_DIR:            {DATA_DIR}")
    print(f"DATA_RAW_DIR:        {DATA_RAW_DIR}")
    print(f"DATA_PROCESSED_DIR:  {DATA_PROCESSED_DIR}")
    print(f"DATA_KG_DIR:         {DATA_KG_DIR}")
    print(f"DATA_INDEXES_DIR:    {DATA_INDEXES_DIR}")
    print(f"MODELS_DIR:          {MODELS_DIR}")
    print(f"LOGS_DIR:            {LOGS_DIR}")
    print(f"SRC_DIR:             {SRC_DIR}")
    print(f"AGENTS_DIR:          {AGENTS_DIR}")
    print(f"API_DIR:             {API_DIR}")
    print(f"COMMON_DIR:          {COMMON_DIR}")
    print(f"EXTRACTION_DIR:      {EXTRACTION_DIR}")
    print(f"FRONTEND_DIR:        {FRONTEND_DIR}")
    print(f"KNOWLEDGE_GRAPH_DIR: {KNOWLEDGE_GRAPH_DIR}")
    print("=" * 60)
    print("All directories created successfully!")
