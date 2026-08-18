from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import LoggingConfig


LOGGER_NAME = "wechat_auto_reply"


def configure_logging(config: LoggingConfig) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(_level(config.level))
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    config.file_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    file_handler = RotatingFileHandler(
        config.file_path,
        maxBytes=config.max_bytes,
        backupCount=config.backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def _level(value: str) -> int:
    level = getattr(logging, value.upper(), None)
    if not isinstance(level, int):
        raise ValueError(f"unknown log level: {value}")
    return level
