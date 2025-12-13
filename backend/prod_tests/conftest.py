from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

if os.environ.get("RUN_PROD_TESTS", "").strip() != "1":
    pytest.skip(
        "Production-data tests are disabled by default. Set RUN_PROD_TESTS=1 to run.",
        allow_module_level=True,
    )

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"
for path in (PROJECT_ROOT, BACKEND_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
