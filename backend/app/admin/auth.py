from __future__ import annotations

from app.core.logging import get_logger
from app.core.settings import settings
from fastapi import Header, Request

LOGGER = get_logger(__name__)


class AdminAuthError(Exception):
    """Raised when an admin endpoint is accessed without authorization."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


async def verify_admin_access(
    request: Request,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> None:
    token = settings.admin_api_token
    allowed_ips = set(settings.admin_allowed_ips)
    client_ip = request.client.host if request.client else None

    if not token and not allowed_ips:
        return  # auth disabled

    token_param = request.query_params.get("token")
    token_cookie = request.cookies.get("admin_token")
    provided_token = x_admin_token or token_param or token_cookie

    token_valid = token is not None and provided_token == token
    ip_valid = allowed_ips and client_ip in allowed_ips

    if token_valid or ip_valid:
        return

    LOGGER.warning(
        "admin.auth_failed",
        extra={
            "client_ip": client_ip,
            "token_provided": bool(x_admin_token),
        },
    )
    if token and not x_admin_token:
        message = "缺少 X-Admin-Token 请求头"
    else:
        message = "Admin 身份校验失败"
    raise AdminAuthError(message)


__all__ = ["AdminAuthError", "verify_admin_access"]
