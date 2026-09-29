"""
CampusConnect — Vercel ASGI Application Entrypoint
Exposes the FastAPI application instance defined in app.main.
"""

from app.main import app

__all__ = ["app"]
