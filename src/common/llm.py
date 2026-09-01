"""
LLM Client Module
Provides a singleton ChatOpenAI instance configured from project settings.
"""

import sys
from pathlib import Path
from functools import lru_cache

# Ensure project root is in sys.path for direct execution
_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from langchain_openai import ChatOpenAI

from config.settings import settings
from src.common.logger import setup_logger

logger = setup_logger(__name__, "llm.log")


@lru_cache(maxsize=1)
def get_llm(temperature: float = 0.7) -> ChatOpenAI:
    """
    Get a cached ChatOpenAI instance (singleton pattern).

    Uses lru_cache to ensure only one LLM connection is created,
    avoiding redundant API connections and reducing latency.

    Args:
        temperature: Controls randomness of output (0.0 - 1.0).
                     Lower = more deterministic, Higher = more creative.
                     Default: 0.7 (balanced for medical consultation).

    Returns:
        Configured ChatOpenAI instance.

    Raises:
        ValueError: If MODEL_API_KEY is not configured in .env.

    Usage:
        >>> llm = get_llm()
        >>> response = llm.invoke("What are the symptoms of hypertension?")

        >>> # For deterministic tasks (entity extraction)
        >>> llm_strict = get_llm(temperature=0.1)
    """
    # Validate API key
    if not settings.model_api_key:
        logger.error("MODEL_API_KEY is not configured in .env")
        raise ValueError(
            "MODEL_API_KEY is empty. "
            "Please set it in the .env file. "
            "Get your key from: https://dashscope.console.aliyun.com/apiKey"
        )

    logger.info(
        f"Creating LLM client: model={settings.model_name}, "
        f"base_url={settings.model_base_url}, temperature={temperature}, "
        f"enable_thinking={settings.llm_enable_thinking}"
    )

    llm = ChatOpenAI(
        model=settings.model_name,
        openai_api_key=settings.model_api_key,
        openai_api_base=settings.model_base_url,
        temperature=temperature,
        max_retries=settings.llm_max_retries,
        request_timeout=60,
        # qwen3 系列为混合思考模型，默认开启 reasoning 会使结构化小任务也产生
        # 大量思考 token、单次延迟飙到 5-20s。显式下发开关（默认关）以控制延迟；
        # 对非 qwen3 模型，服务端会忽略该参数，无副作用。
        extra_body={"enable_thinking": settings.llm_enable_thinking},
    )

    logger.info("LLM client created successfully")
    return llm


@lru_cache(maxsize=1)
def get_extract_llm(temperature: float = 0.1) -> ChatOpenAI:
    """
    Get the LLM client for entity/relation extraction.

    独立缓存，不复用 get_llm 的 lru_cache：
    - EXTRACTION_MODEL_BASE_URL 非空 → 指向自部署 vLLM 微调模型（OpenAI 兼容接口）；
    - 为空（默认）→ 回退主 LLM get_llm()（云端），行为与改动前完全一致。

    Args:
        temperature: 抽取为结构化任务，建议低温度，默认 0.1。

    Returns:
        Configured ChatOpenAI instance.

    Usage:
        >>> llm = get_extract_llm()
    """
    base_url = settings.extraction_model_base_url.strip()
    if not base_url:
        logger.info("Extraction LLM: EXTRACTION_MODEL_BASE_URL 为空，抽取回退云端主 LLM get_llm()")
        return get_llm(temperature)

    logger.info(
        f"Extraction LLM: 抽取使用本地 vLLM 微调模型, "
        f"model={settings.extraction_model_name}, base_url={base_url}, "
        f"temperature={temperature}"
    )

    # vLLM 的 OpenAI 兼容接口不认识 qwen3 的 enable_thinking 参数，不携带 extra_body
    # max_tokens=2048：训练集输出最长约 896 字符，但模型对含噪声长描述的样本会照抄输入
    # （输出可达 ~1500 token）；2048 给足正常空间，同时作为失控生成的保险丝
    return ChatOpenAI(
        model=settings.extraction_model_name,
        openai_api_key=settings.extraction_model_api_key,
        openai_api_base=base_url,
        temperature=temperature,
        max_tokens=2048,
        max_retries=settings.llm_max_retries,
        request_timeout=90,
    )


if __name__ == "__main__":
    # Demo: test LLM connection
    print("=" * 60)
    print("LLM Client Test")
    print("=" * 60)

    try:
        llm = get_llm()
        print(f"[PASS] Model: {settings.model_name}")
        print(f"[PASS] Base URL: {settings.model_base_url}")

        # Quick connectivity test
        response = llm.invoke("Say 'hello' in one word")
        print(f"[PASS] Response: {response.content}")

        # Test singleton (should return same instance)
        llm2 = get_llm()
        assert llm is llm2, "[FAIL] Singleton pattern broken"
        print("[PASS] Singleton pattern verified")

        print("\n[SUCCESS] LLM client is working correctly!")

    except ValueError as e:
        print(f"[FAIL] Configuration error: {e}")
    except Exception as e:
        print(f"[FAIL] Connection error: {e}")
        print("  Please check your MODEL_API_KEY and network connection.")
