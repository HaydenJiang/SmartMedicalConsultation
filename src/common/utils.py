"""
General Utility Functions
Provides text cleaning, retry logic, timing decorators, and other helpers.
"""

import re
import time
import functools
from typing import Callable, Any

import sys
from pathlib import Path

# Ensure project root is in sys.path for direct execution
_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.common.logger import setup_logger

logger = setup_logger(__name__, "utils.log")


# ============================================================
# 1. Text Cleaning
# ============================================================

def clean_text(text: str) -> str:
    """
    Clean text by removing extra whitespace and special characters.
    Preserves Chinese characters, English, numbers, and common punctuation.

    Args:
        text: Raw input text to clean.

    Returns:
        Cleaned text string. Empty string if input is None or empty.

    Usage:
        >>> clean_text("  Hello   World  ")
        'Hello World'
        >>> clean_text("头痛、发热@@@")
        '头痛、发热'
    """
    if not text:
        return ""

    # Normalize whitespace (tabs, newlines, multiple spaces -> single space)
    text = " ".join(text.split())

    # Remove special characters (keep Chinese, English, numbers, common punctuation)
    text = re.sub(
        r'[^\w\s一-鿿，。、；：！？“”‘’（）《》.-]+',
        '',
        text
    )

    return text.strip()


# ============================================================
# 2. Retry Decorator
# ============================================================

def retry_on_error(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
) -> Callable:
    """
    Decorator that retries a function on failure with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts (default: 3).
        delay: Initial delay between retries in seconds (default: 1.0).
        backoff: Multiplier for delay after each retry (default: 2.0).
                 Example: delay=1, backoff=2 -> waits 1s, 2s, 4s.
        exceptions: Tuple of exception types to catch.
                    Default: catches all exceptions.

    Returns:
        Decorated function with retry logic.

    Usage:
        >>> @retry_on_error(max_retries=3, delay=2.0)
        ... def fetch_data(url):
        ...     return requests.get(url).json()

        >>> @retry_on_error(max_retries=5, exceptions=(ConnectionError, TimeoutError))
        ... def connect_db():
        ...     return neo4j.GraphDatabase.driver(uri)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            current_delay = delay
            last_exception = None

            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(
                            f"[RETRY] {func.__name__} failed (attempt {attempt}/{max_retries}): "
                            f"{type(e).__name__}: {e}. "
                            f"Retrying in {current_delay:.1f}s..."
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(
                            f"[RETRY] {func.__name__} failed after {max_retries} attempts: "
                            f"{type(e).__name__}: {e}"
                        )

            raise last_exception

        return wrapper
    return decorator


# ============================================================
# 3. Timer Decorator
# ============================================================

def timer(func: Callable = None, *, log: bool = True) -> Callable:
    """
    Decorator that measures and logs function execution time.

    Can be used with or without arguments:
        @timer           - logs to logger
        @timer(log=False) - prints to console only

    Args:
        func: The function to decorate (auto-passed by @timer syntax).
        log: If True, log timing via logger. If False, use print().

    Returns:
        Decorated function that logs execution time.
        The execution time in seconds is also stored as func.last_duration.

    Usage:
        >>> @timer
        ... def slow_function():
        ...     time.sleep(1)

        >>> @timer(log=False)
        ... def quick_calc():
        ...     return sum(range(1000000))
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> Any:
            start = time.perf_counter()
            result = fn(*args, **kwargs)
            elapsed = time.perf_counter() - start

            # Store duration for programmatic access
            wrapper.last_duration = elapsed

            msg = f"[TIMER] {fn.__name__} completed in {elapsed:.3f}s"

            if log:
                logger.info(msg)
            else:
                print(msg)

            return result

        wrapper.last_duration = 0.0
        return wrapper

    # Support both @timer and @timer(log=False) syntax
    if func is not None:
        return decorator(func)
    return decorator


# ============================================================
# Main: Self-test
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Utility Functions Test")
    print("=" * 60)

    # Test 1: clean_text
    print("\n[TEST 1] clean_text")
    assert clean_text("") == ""
    assert clean_text(None) == ""
    assert clean_text("  hello   world  ") == "hello world"
    assert clean_text("头痛、发热@@@") == "头痛、发热"
    assert clean_text("Hello\n\n\tWorld") == "Hello World"
    print("[PASS] clean_text works correctly")

    # Test 2: retry_on_error
    print("\n[TEST 2] retry_on_error")

    def _test_retry():
        count = 0

        @retry_on_error(max_retries=3, delay=0.1)
        def flaky_function():
            nonlocal count
            count += 1
            if count < 3:
                raise ValueError(f"Attempt {count} failed")
            return "success"

        result = flaky_function()
        assert result == "success"
        assert count == 3
        print(f"[PASS] retry_on_error: succeeded after {count} attempts")

    _test_retry()

    # Test 3: timer
    print("\n[TEST 3] timer")

    @timer(log=False)
    def timed_function():
        total = sum(range(100000))
        return total

    result = timed_function()
    assert timed_function.last_duration > 0
    print(f"[PASS] timer: execution took {timed_function.last_duration:.4f}s")

    print("\n" + "=" * 60)
    print("[SUCCESS] All utility tests passed!")
    print("=" * 60)
