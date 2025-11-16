from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Mapping

import httpx
from fastapi import FastAPI
from httpx import ASGITransport


@dataclass
class InternalApiResult:
    status_code: int | None
    duration_ms: float
    ok: bool
    response_headers: dict[str, str]
    response_body_excerpt: str | None
    error: str | None = None


async def perform_internal_request(
    app: FastAPI | None,
    base_url: str,
    *,
    method: str,
    path: str,
    query: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    json_body: Any = None,
    timeout_ms: int = 5000,
) -> InternalApiResult:
    """Execute a HTTP call against the current FastAPI app using httpx."""

    normalized_path = path if path.startswith("/") else f"/{path}"
    timeout = httpx.Timeout(timeout_ms / 1000)
    start = perf_counter()
    try:
        client_kwargs: dict[str, Any] = {"timeout": timeout}
        if app is not None:
            client_kwargs["transport"] = ASGITransport(app=app)
            client_kwargs["base_url"] = base_url.rstrip("/") or "http://testserver"
        else:
            client_kwargs["base_url"] = base_url.rstrip("/")

        async with httpx.AsyncClient(**client_kwargs) as client:
            response = await client.request(
                method=method.upper(),
                url=normalized_path,
                params=query or None,
                headers=headers or None,
                json=json_body,
            )
    except httpx.RequestError as exc:
        duration = (perf_counter() - start) * 1000
        return InternalApiResult(
            status_code=None,
            duration_ms=round(duration, 3),
            ok=False,
            response_headers={},
            response_body_excerpt=None,
            error=str(exc),
        )

    duration = (perf_counter() - start) * 1000
    excerpt = _build_excerpt(response.text)
    headers_payload = {k: v for k, v in list(response.headers.items())[:10]}
    return InternalApiResult(
        status_code=response.status_code,
        duration_ms=round(duration, 3),
        ok=response.is_success,
        response_headers=headers_payload,
        response_body_excerpt=excerpt,
        error=None,
    )


def _build_excerpt(body: str, limit: int = 2048) -> str:
    if len(body) <= limit:
        return body
    return f"{body[: limit - 3]}..."
