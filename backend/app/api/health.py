from app.utils.responses import success_response
from fastapi import APIRouter

router = APIRouter()


@router.get("/healthz")
def read_healthz() -> dict:
    """Basic liveness probe endpoint."""

    return success_response({"status": "ok"})
