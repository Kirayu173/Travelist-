from datetime import datetime, timezone

from app.core.settings import settings
from app.services.admin_service import get_api_summary, get_health_status
from app.utils.responses import success_response
from fastapi import APIRouter

router = APIRouter()


@router.get("/ping")
def admin_ping() -> dict:
    """Return quick admin heartbeat with version and server time."""

    payload = {
        "version": settings.app_version,
        "time": datetime.now(tz=timezone.utc).isoformat(),
    }
    return success_response(payload)


@router.get("/api/summary")
def admin_api_summary() -> dict:
    """Expose API usage metrics collected by the middleware."""

    return success_response(get_api_summary())


@router.get("/health")
def admin_health() -> dict:
    """Expose aggregated dependency health (placeholder)."""

    return success_response(get_health_status())
