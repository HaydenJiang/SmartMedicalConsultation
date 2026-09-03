"""
Configuration Module Verification Script
Tests config/settings.py and config/paths.py
"""

import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_settings():
    """Test settings.py - configuration loading"""
    print("=" * 60)
    print("[TEST 1] Configuration Loading (settings.py)")
    print("=" * 60)

    try:
        from config import settings

        # Test LLM configuration
        assert settings.model_base_url.startswith("https://"), "[FAIL] MODEL_BASE_URL invalid"
        assert settings.model_api_key.startswith("sk-"), "[FAIL] MODEL_API_KEY invalid"
        assert settings.model_name in ["qwen-plus", "qwen-max"], "[FAIL] MODEL_NAME invalid"
        print(f"[PASS] LLM Config: {settings.model_name} @ {settings.model_base_url}")

        # Test Neo4j configuration
        assert settings.neo4j_uri.startswith("bolt://"), "[FAIL] NEO4J_URI invalid"
        assert settings.neo4j_user == "neo4j", "[FAIL] NEO4J_USER invalid"
        assert len(settings.neo4j_password) >= 6, "[FAIL] NEO4J_PASSWORD too short"
        print(f"[PASS] Neo4j Config: {settings.neo4j_user}@{settings.neo4j_uri}")

        # Test Embedding model configuration
        assert settings.embedding_model_path, "[FAIL] EMBEDDING_MODEL_PATH empty"
        print(f"[PASS] Embedding Model: {settings.embedding_model_path}")

        # Test logging configuration
        assert settings.log_level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], "[FAIL] LOG_LEVEL invalid"
        print(f"[PASS] Log Level: {settings.log_level}")

        # Test application configuration
        assert settings.app_name, "[FAIL] APP_NAME empty"
        assert settings.api_port > 0, "[FAIL] API_PORT invalid"
        assert settings.frontend_port > 0, "[FAIL] FRONTEND_PORT invalid"
        print(f"[PASS] App Config: {settings.app_name} v{settings.app_version}")
        print(f"[PASS] Ports: API={settings.api_port}, Frontend={settings.frontend_port}")

        print("\n[SUCCESS] All settings tests passed!\n")
        return True

    except Exception as e:
        print(f"[FAIL] Settings test failed: {e}\n")
        return False


def test_paths():
    """Test paths.py - path configuration"""
    print("=" * 60)
    print("[TEST 2] Path Configuration (paths.py)")
    print("=" * 60)

    try:
        from config import (
            PROJECT_ROOT,
            DATA_DIR,
            DATA_RAW_DIR,
            DATA_PROCESSED_DIR,
            DATA_KG_DIR,
            DATA_INDEXES_DIR,
            MODELS_DIR,
            LOGS_DIR,
        )
        from config.paths import (
            SRC_DIR,
            AGENTS_DIR,
            API_DIR,
            COMMON_DIR,
            EXTRACTION_DIR,
            FRONTEND_DIR,
            KNOWLEDGE_GRAPH_DIR,
            get_data_path,
            get_log_path,
        )

        # Test PROJECT_ROOT
        assert PROJECT_ROOT.exists(), "[FAIL] PROJECT_ROOT does not exist"
        assert (PROJECT_ROOT / ".env").exists(), "[FAIL] .env file not found in PROJECT_ROOT"
        print(f"[PASS] PROJECT_ROOT: {PROJECT_ROOT}")

        # Test data directories exist
        assert DATA_DIR.exists(), "[FAIL] DATA_DIR does not exist"
        assert DATA_RAW_DIR.exists(), "[FAIL] DATA_RAW_DIR does not exist"
        assert DATA_PROCESSED_DIR.exists(), "[FAIL] DATA_PROCESSED_DIR does not exist"
        assert DATA_KG_DIR.exists(), "[FAIL] DATA_KG_DIR does not exist"
        assert DATA_INDEXES_DIR.exists(), "[FAIL] DATA_INDEXES_DIR does not exist"
        print(f"[PASS] Data directories created: {DATA_DIR.name}/")

        # Test models and logs directories
        assert MODELS_DIR.exists(), "[FAIL] MODELS_DIR does not exist"
        assert LOGS_DIR.exists(), "[FAIL] LOGS_DIR does not exist"
        print(f"[PASS] MODELS_DIR: {MODELS_DIR}")
        print(f"[PASS] LOGS_DIR: {LOGS_DIR}")

        # Test source directories
        assert SRC_DIR.name == "src", "[FAIL] SRC_DIR name incorrect"
        assert AGENTS_DIR.name == "agents", "[FAIL] AGENTS_DIR name incorrect"
        assert API_DIR.name == "api", "[FAIL] API_DIR name incorrect"
        assert COMMON_DIR.name == "common", "[FAIL] COMMON_DIR name incorrect"
        print(f"[PASS] Source directories: {SRC_DIR.name}/")

        # Test helper functions
        test_file = get_data_path("test.json")
        assert test_file.parent == DATA_DIR, "[FAIL] get_data_path() incorrect"
        print(f"[PASS] Helper function: get_data_path('test.json')")

        log_file = get_log_path("app.log")
        assert log_file.parent == LOGS_DIR, "[FAIL] get_log_path() incorrect"
        print(f"[PASS] Helper function: get_log_path('app.log')")

        # Test cross-platform compatibility
        assert isinstance(PROJECT_ROOT, Path), "[FAIL] Paths should be pathlib.Path objects"
        print(f"[PASS] Cross-platform: Using pathlib.Path")

        print("\n[SUCCESS] All paths tests passed!\n")
        return True

    except Exception as e:
        print(f"[FAIL] Paths test failed: {e}\n")
        return False


def test_integration():
    """Test integration between settings and paths"""
    print("=" * 60)
    print("[TEST 3] Integration Test")
    print("=" * 60)

    try:
        from config import settings, PROJECT_ROOT, LOGS_DIR

        # Test that settings and paths work together
        log_file = LOGS_DIR / "app.log"
        print(f"[PASS] Combined usage: {log_file}")

        # Test that we can use settings to configure paths
        model_path = PROJECT_ROOT / settings.embedding_model_path
        print(f"[PASS] Model path from settings: {model_path}")

        print("\n[SUCCESS] Integration test passed!\n")
        return True

    except Exception as e:
        print(f"[FAIL] Integration test failed: {e}\n")
        return False


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("CONFIGURATION MODULE VERIFICATION")
    print("=" * 60 + "\n")

    results = []
    results.append(("Settings", test_settings()))
    results.append(("Paths", test_paths()))
    results.append(("Integration", test_integration()))

    # Summary
    print("=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status} {name}")

    print("=" * 60)
    print(f"Total: {passed}/{total} tests passed")

    if passed == total:
        print("\n[SUCCESS] All configuration tests passed!")
        return 0
    else:
        print("\n[FAILED] Some tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
