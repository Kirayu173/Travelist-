from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict

from app.core.settings import settings

_TOOL_LOGGERS: dict[str, logging.Logger] = {}


def _build_tool_logger(name: str) -> logging.Logger:
    log_dir = Path(settings.log_directory).resolve() / "tools"
    log_dir.mkdir(parents=True, exist_ok=True)
    logfile = log_dir / f"{name}.log"

    logger = logging.getLogger(f"agent_tool.{name}")
    logger.setLevel(settings.log_level)
    logger.propagate = False  # keep tool logs separate from app log

    if not logger.handlers:
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | tool=%(tool)s | event=%(event)s | "
            "status=%(status)s | err=%(error_code)s | msg=%(message)s | "
            "request=%(request)s | response=%(response)s | raw=%(raw_input)s | "
            "output=%(output)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler = RotatingFileHandler(
            logfile,
            maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backup_count,
            encoding="utf-8",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


def get_tool_logger(name: str) -> logging.Logger:
    if name not in _TOOL_LOGGERS:
        _TOOL_LOGGERS[name] = _build_tool_logger(name)
    return _TOOL_LOGGERS[name]


def log_tool_event(
    tool_name: str,
    *,
    event: str,
    status: str = "ok",
    request: Dict[str, Any] | None = None,
    response: Any = None,
    raw_input: Any = None,
    output: Any = None,
    error_code: str | None = None,
    message: str | None = None,
) -> None:
    logger = get_tool_logger(tool_name)
    level = logging.INFO if status == "ok" else logging.WARNING
    logger.log(
        level,
        message or "tool.event",
        extra={
            "tool": tool_name,
            "event": event,
            "status": status,
            "error_code": error_code,
            "request": request,
            "response": response,
            "raw_input": raw_input,
            "output": output,
        },
    )
