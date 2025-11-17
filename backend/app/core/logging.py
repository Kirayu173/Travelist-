from __future__ import annotations

import logging
import logging.config
from pathlib import Path
from typing import Any, Dict

from app.core.settings import settings


def _build_logging_config(log_dir: Path) -> Dict[str, Any]:
    formatter = {
        "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        "datefmt": "%Y-%m-%d %H:%M:%S",
    }
    log_path = log_dir / "app.log"
    error_path = log_dir / "errors.log"
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"standard": formatter},
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": settings.log_level,
                "formatter": "standard",
            },
            "app_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": settings.log_level,
                "formatter": "standard",
                "filename": str(log_path),
                "maxBytes": settings.log_max_bytes,
                "backupCount": settings.log_backup_count,
                "encoding": "utf-8",
            },
            "error_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "ERROR",
                "formatter": "standard",
                "filename": str(error_path),
                "maxBytes": settings.log_max_bytes,
                "backupCount": settings.log_backup_count,
                "encoding": "utf-8",
            },
        },
        "root": {
            "level": settings.log_level,
            "handlers": ["console", "app_file", "error_file"],
        },
    }


def setup_logging() -> None:
    """Configure logging once at application start."""

    log_dir = Path(settings.log_directory).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    config = _build_logging_config(log_dir)
    logging.config.dictConfig(config)


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(name or "travelist")
