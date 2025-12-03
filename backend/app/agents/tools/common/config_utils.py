from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def _candidate_env_paths() -> list[Path]:
    here = Path(__file__).resolve()
    candidates: list[Path] = []
    candidates.append(Path.cwd() / ".env")
    candidates.append(here.parent / ".env")
    for parent in here.parents:
        candidates.append(parent / ".env")
        if parent.parent == parent:
            break
    # remove duplicates, preserve order
    seen = set()
    uniq: list[Path] = []
    for p in candidates:
        if p not in seen:
            uniq.append(p)
            seen.add(p)
    return uniq


def load_env() -> bool:
    """Load environment variables from common locations; keep system env intact."""

    loaded = False
    for env_path in _candidate_env_paths():
        if env_path.exists():
            try:
                load_dotenv(env_path, override=False)
                logger.info("loaded_env_file", extra={"path": str(env_path)})
                loaded = True
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("load_env_failed", extra={"path": str(env_path), "error": str(exc)})
    if not loaded:
        logger.warning("load_env_not_found")
    return loaded


def get_key(key_name: str, default: str | None = None) -> str | None:
    """Fetch an API key from env, optionally with default."""

    return os.getenv(key_name, default)


def require_key(key_name: str) -> None:
    """Ensure key exists, otherwise raise for clearer diagnostics."""

    if not os.getenv(key_name):
        raise ValueError(f"API key '{key_name}' is not set; please configure environment.")
