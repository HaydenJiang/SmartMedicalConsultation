# -*- coding: utf-8 -*-
"""
SmartMedicalConsultation - Environment Validation Script
Check all required environment configurations
"""

import sys
import os
import subprocess
import importlib
from pathlib import Path

# Color output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_header(text):
    """Print header"""
    print(f"\n{Colors.BLUE}{Colors.BOLD}{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}{Colors.RESET}\n")

def print_success(text):
    """Print success message"""
    print(f"  [PASS] {Colors.GREEN}{text}{Colors.RESET}")

def print_error(text):
    """Print error message"""
    print(f"  [FAIL] {Colors.RED}{text}{Colors.RESET}")

def print_warning(text):
    """Print warning message"""
    print(f"  [WARN] {Colors.YELLOW}{text}{Colors.RESET}")

def print_info(text):
    """Print info message"""
    print(f"  [INFO] {text}")

def check_python_version():
    """Check if Python version is 3.11"""
    print(f"{Colors.BOLD}1. Checking Python Version{Colors.RESET}")

    version = sys.version_info
    version_str = f"{version.major}.{version.minor}.{version.micro}"

    if version.major == 3 and version.minor == 11:
        print_success(f"Python version: {version_str}")
        return True
    else:
        print_error(f"Python version: {version_str} (requires 3.11.x)")
        print_info("Fix:")
        print_info("  conda create -n smc_project python=3.11")
        print_info("  conda activate smc_project")
        return False

def check_required_packages():
    """Check all required Python packages"""
    print(f"\n{Colors.BOLD}2. Checking Required Python Packages{Colors.RESET}")

    required_packages = [
        # Core AI/LLM libraries
        ('langchain', 'langchain'),
        ('langchain_openai', 'langchain-openai'),
        ('langgraph', 'langgraph'),
        ('langchain_community', 'langchain-community'),
        ('langchain_core', 'langchain-core'),

        # Vector search
        ('faiss', 'faiss-cpu'),
        ('sentence_transformers', 'sentence-transformers'),

        # Graph database
        ('neo4j', 'neo4j'),

        # Web framework
        ('fastapi', 'fastapi'),
        ('uvicorn', 'uvicorn'),
        ('streamlit', 'streamlit'),

        # Data validation
        ('pydantic', 'pydantic'),
        ('pydantic_settings', 'pydantic-settings'),

        # Data processing
        ('pandas', 'pandas'),
        ('openpyxl', 'openpyxl'),
        ('numpy', 'numpy'),

        # Network requests
        ('requests', 'requests'),
        ('bs4', 'beautifulsoup4'),
        ('httpx', 'httpx'),
        ('aiohttp', 'aiohttp'),

        # Utilities
        ('dotenv', 'python-dotenv'),
        ('tqdm', 'tqdm'),
        ('tenacity', 'tenacity'),
    ]

    all_installed = True
    missing_packages = []

    for module_name, package_name in required_packages:
        try:
            importlib.import_module(module_name)
            print_success(f"{package_name}")
        except ImportError:
            print_error(f"{package_name} not installed")
            missing_packages.append(package_name)
            all_installed = False

    if missing_packages:
        print_info("\nFix:")
        print_info(f"  pip install {' '.join(missing_packages)}")

    return all_installed

def check_env_file():
    """Check if .env file exists and contains all required configurations"""
    print(f"\n{Colors.BOLD}3. Checking .env Configuration File{Colors.RESET}")

    env_file = Path('.env')

    if not env_file.exists():
        print_error(".env file does not exist")
        print_info("Fix:")
        print_info("  cp .env.example .env")
        print_info("  Then edit .env file with your actual configurations")
        return False

    print_success(".env file exists")

    # Load .env file
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception as e:
        print_error(f"Cannot load .env file: {e}")
        return False

    # Check required configurations
    required_configs = {
        'MODEL_BASE_URL': 'LLM API URL',
        'MODEL_API_KEY': 'LLM API Key',
        'MODEL_NAME': 'LLM Model Name',
        'NEO4J_URI': 'Neo4j Connection URI',
        'NEO4J_USER': 'Neo4j Username',
        'NEO4J_PASSWORD': 'Neo4j Password',
        'EMBEDDING_MODEL_PATH': 'Embedding Model Path',
        'LOG_LEVEL': 'Log Level',
    }

    all_configs_valid = True

    for config_key, description in required_configs.items():
        value = os.getenv(config_key)

        if not value:
            print_error(f"{config_key} not configured ({description})")
            all_configs_valid = False
        elif value in ['your_api_key_here', 'your_dashscope_api_key_here', 'your_neo4j_password']:
            print_warning(f"{config_key} is still placeholder, please replace with real value ({description})")
            all_configs_valid = False
        else:
            # Mask sensitive information
            if 'KEY' in config_key or 'PASSWORD' in config_key:
                masked_value = value[:4] + '...' + value[-4:] if len(value) > 8 else '***'
                print_success(f"{config_key} = {masked_value}")
            else:
                print_success(f"{config_key} = {value}")

    if not all_configs_valid:
        print_info("\nFix:")
        print_info("  Edit .env file and fill in all required configuration values")

    return all_configs_valid

def check_neo4j_docker():
    """Check if Neo4j Docker container is running"""
    print(f"\n{Colors.BOLD}4. Checking Neo4j Docker Container{Colors.RESET}")

    try:
        # Check if Docker is installed
        result = subprocess.run(
            ['docker', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode != 0:
            print_error("Docker is not installed or not running")
            print_info("Fix:")
            print_info("  Install Docker: https://docs.docker.com/get-docker/")
            return False

        print_success(f"Docker installed: {result.stdout.strip()}")

        # Check if Neo4j container is running
        result = subprocess.run(
            ['docker', 'ps', '--filter', 'name=neo4j', '--format', '{{.Names}} {{.Status}}'],
            capture_output=True,
            text=True,
            timeout=5
        )

        if 'neo4j' in result.stdout and 'Up' in result.stdout:
            print_success("Neo4j container is running")
            return True
        else:
            print_error("Neo4j container is not running")
            print_info("Fix:")
            print_info("  docker run -d --name neo4j \\")
            print_info("    -p 7474:7474 -p 7687:7687 \\")
            print_info("    -e NEO4J_AUTH=neo4j/12345678 \\")
            print_info("    neo4j:5.26")
            return False

    except subprocess.TimeoutExpired:
        print_error("Docker command timeout")
        return False
    except FileNotFoundError:
        print_error("Docker command not found")
        print_info("Fix:")
        print_info("  Install Docker: https://docs.docker.com/get-docker/")
        return False
    except Exception as e:
        print_error(f"Error checking Docker: {e}")
        return False

def check_bge_m3_model():
    """Check if BGE-M3 model files exist"""
    print(f"\n{Colors.BOLD}5. Checking BGE-M3 Embedding Model{Colors.RESET}")

    # Read model path from .env
    model_path = os.getenv('EMBEDDING_MODEL_PATH', 'models/bge-m3')
    model_dir = Path(model_path)

    if not model_dir.exists():
        print_error(f"Model directory does not exist: {model_path}")
        print_info("Fix:")
        print_info("  pip install huggingface-hub")
        print_info("  huggingface-cli download BAAI/bge-m3 --local-dir models/bge-m3")
        return False

    print_success(f"Model directory exists: {model_path}")

    # Check key files
    required_files = [
        'config.json',
        'tokenizer.json',
        'tokenizer_config.json',
    ]

    # Model files can be .bin or .safetensors
    model_files = list(model_dir.glob('*.bin')) + list(model_dir.glob('*.safetensors'))

    all_files_exist = True

    for file_name in required_files:
        file_path = model_dir / file_name
        if file_path.exists():
            print_success(f"Config file: {file_name}")
        else:
            print_error(f"Missing config file: {file_name}")
            all_files_exist = False

    if model_files:
        print_success(f"Model files: {len(model_files)} found")
    else:
        print_error("No model files found (*.bin or *.safetensors)")
        all_files_exist = False

    if not all_files_exist:
        print_info("\nFix:")
        print_info("  Re-download model:")
        print_info("  huggingface-cli download BAAI/bge-m3 --local-dir models/bge-m3")

    return all_files_exist

def check_dashscope_api():
    """Check if Alibaba Cloud DashScope API is accessible"""
    print(f"\n{Colors.BOLD}6. Checking Alibaba Cloud DashScope API{Colors.RESET}")

    api_key = os.getenv('MODEL_API_KEY')
    base_url = os.getenv('MODEL_BASE_URL')

    if not api_key or api_key in ['your_api_key_here', 'your_dashscope_api_key_here']:
        print_error("MODEL_API_KEY not configured or still placeholder")
        print_info("Fix:")
        print_info("  1. Visit https://dashscope.console.aliyun.com/apiKey to get API Key")
        print_info("  2. Edit .env file and replace MODEL_API_KEY with real value")
        return False

    if not base_url:
        print_error("MODEL_BASE_URL not configured")
        return False

    print_info(f"API URL: {base_url}")

    # Try to call API
    try:
        import httpx

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        # Send a simple request
        response = httpx.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json={
                "model": os.getenv('MODEL_NAME', 'qwen-plus'),
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 10
            },
            timeout=10.0
        )

        if response.status_code == 200:
            print_success("API is accessible, connection successful")
            return True
        elif response.status_code == 401:
            print_error("API key is invalid or expired")
            print_info("Fix:")
            print_info("  Check MODEL_API_KEY in .env file")
            return False
        else:
            print_error(f"API returned error status code: {response.status_code}")
            print_info(f"Response: {response.text[:200]}")
            return False

    except httpx.TimeoutException:
        print_error("API request timeout")
        print_info("Fix:")
        print_info("  Check network connection")
        print_info("  Verify MODEL_BASE_URL is correct")
        return False
    except Exception as e:
        print_error(f"Error checking API: {e}")
        print_info("Fix:")
        print_info("  Install httpx: pip install httpx")
        print_info("  Check network connection")
        return False

def main():
    """Main function"""
    print_header("SmartMedicalConsultation - Environment Validation")

    results = {
        'Python Version': check_python_version(),
        'Python Packages': check_required_packages(),
        '.env Configuration': check_env_file(),
        'Neo4j Docker': check_neo4j_docker(),
        'BGE-M3 Model': check_bge_m3_model(),
        'DashScope API': check_dashscope_api(),
    }

    # Print summary
    print_header("Validation Summary")

    passed = sum(1 for result in results.values() if result)
    total = len(results)

    for check_name, result in results.items():
        if result:
            print_success(f"{check_name}")
        else:
            print_error(f"{check_name}")

    print(f"\n{Colors.BOLD}Summary: {passed}/{total} checks passed{Colors.RESET}\n")

    if passed == total:
        print(f"{Colors.GREEN}{Colors.BOLD}[SUCCESS] All environment checks passed, ready to develop!{Colors.RESET}\n")
        return 0
    elif passed >= total * 0.7:
        print(f"{Colors.YELLOW}{Colors.BOLD}[WARNING] Some checks failed, please fix according to suggestions above{Colors.RESET}\n")
        return 1
    else:
        print(f"{Colors.RED}{Colors.BOLD}[ERROR] Multiple checks failed, please complete environment setup first{Colors.RESET}\n")
        return 2

if __name__ == '__main__':
    sys.exit(main())
