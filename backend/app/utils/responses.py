from typing import Any


def success_response(data: Any, msg: str = "ok", code: int = 0) -> dict[str, Any]:
    """Return payload formatted per project contract."""
    return {"code": code, "msg": msg, "data": data}


def error_response(msg: str, code: int = 10001, data: Any = None) -> dict[str, Any]:
    return {"code": code, "msg": msg, "data": data}
