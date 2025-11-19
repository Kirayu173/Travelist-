import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(r"d:/graduation_project/Travelist+")
BACKEND_DIR = PROJECT_ROOT / "backend"
for path in (PROJECT_ROOT, BACKEND_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.ai.local_memory_engine import LocalMemoryEngine
from app.core.settings import settings

engine = LocalMemoryEngine.create(settings)
print('provider', engine._provider)
