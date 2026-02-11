from __future__ import annotations

from fastapi import FastAPI

from app.core.config import logger
from app.student.db import init_db
from app.api import routes_exercises, routes_sessions, routes_sessions_stream

from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pathlib import Path

import logging
import os
from dataclasses import dataclass
from typing import Set

from dotenv import load_dotenv
from pathlib import Path

# לטעון .env מהשורש של הפרויקט
load_dotenv(dotenv_path=Path(__file__).parents[1] / ".env")


from app.domain.model import Subject

# טעינת .env פעם אחת בתחילת המודול
load_dotenv()

def create_app() -> FastAPI:
    logger.info("Creating FastAPI app")
    app = FastAPI(
        title="Shira Tutor",
        version="0.1.0",
    )

    # DB init
    init_db()

    # Routers
    app.include_router(routes_exercises.router)
    app.include_router(routes_sessions.router)
    app.include_router(routes_sessions_stream.router)

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        index_path = static_dir / "index.html"
        return HTMLResponse(index_path.read_text(encoding="utf-8"))

    return app


app = create_app()
