import importlib.metadata

__version__ = importlib.metadata.version("mem0ai")

from mem0.memory.main import AsyncMemory, Memory  # noqa

__all__ = ["__version__", "Memory", "AsyncMemory"]
