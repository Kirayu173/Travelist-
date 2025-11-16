from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from .service import AdminService, get_admin_service

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

__all__ = ["AdminService", "get_admin_service", "templates"]
