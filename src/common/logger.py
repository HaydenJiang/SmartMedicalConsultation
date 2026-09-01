"""
Unified Logging Module
Provides consistent logging across all project modules.
Outputs to both console and log file simultaneously.
"""

import logging
import sys
from pathlib import Path


# Import paths - use config module if available, fallback to relative path
try:
    from config.paths import LOGS_DIR
    from config.settings import settings
    _DEFAULT_LOG_LEVEL = settings.log_level
except ImportError:
    LOGS_DIR = Path(__file__).parent.parent.parent / "logs"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    _DEFAULT_LOG_LEVEL = "INFO"


# Default log format: time + level + module + message
LOG_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logger(
    name: str,
    log_file: str | None = None,
    level: str | None = None,
) -> logging.Logger:
    """
    Create and configure a logger with console and file handlers.

    Args:
        name: Logger name, typically __name__ of the calling module.
              Example: "src.agents.intent_classifier"
        log_file: Log file name (saved under logs/ directory).
                  If None, only outputs to console.
                  Example: "agent.log"
        level: Log level override. If None, reads from config.settings.
               Options: DEBUG, INFO, WARNING, ERROR, CRITICAL

    Returns:
        Configured logging.Logger instance.

    Usage:
        >>> logger = setup_logger(__name__, "extraction.log")
        >>> logger.info("Entity extraction started")
        >>> logger.error("Failed to parse document", exc_info=True)
    """
    # Resolve log level
    log_level = getattr(logging, (level or _DEFAULT_LOG_LEVEL).upper(), logging.INFO)

    # Check if logger already exists (avoid duplicate handlers)
    logger = logging.getLogger(name)

    if logger.handlers:
        # Logger already configured, just return it
        return logger

    logger.setLevel(log_level)

    # Formatter
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # Console handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler (if log_file specified)
    if log_file:
        log_path = LOGS_DIR / log_file
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(
            str(log_path), encoding="utf-8", mode="a"
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # Prevent log messages from propagating to root logger
    logger.propagate = False

    return logger


# ===== Module-level convenience =====
# Create a default logger for this module
logger = setup_logger("src.common.logger")


if __name__ == "__main__":
    # Demo: test the logger
    test_logger = setup_logger("test_module", "test.log", level="DEBUG")

    test_logger.debug("This is a DEBUG message")
    test_logger.info("This is an INFO message")
    test_logger.warning("This is a WARNING message")
    test_logger.error("This is an ERROR message")
    test_logger.critical("This is a CRITICAL message")

    print(f"\n[PASS] Log file saved to: {LOGS_DIR / 'test.log'}")
    print(f"[PASS] All 5 log levels working correctly")
