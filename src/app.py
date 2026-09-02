"""FastAPI application factory."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from api import geoip, node, peers, system
from runtime import AppRuntime
from settings import AppSettings


def create_app(settings: AppSettings, runtime: AppRuntime | None = None) -> FastAPI:
    package_dir = Path(__file__).resolve().parent
    templates = Jinja2Templates(directory=str(package_dir / "templates"))
    app_runtime = runtime or AppRuntime(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        app_runtime.start()
        try:
            yield
        finally:
            app_runtime.stop()

    app = FastAPI(
        title="Bitcoin Peer Map",
        description="Bitcoin peer monitoring and management dashboard",
        version=settings.build_revision,
        lifespan=lifespan,
    )
    app.state.runtime = app_runtime
    app.include_router(peers.router)
    app.include_router(node.router)
    app.include_router(geoip.router)
    app.include_router(system.router)

    repository_url = f"https://github.com/{settings.github_repository}"
    revision = settings.build_revision
    revision_url = (
        f"{repository_url}/commit/{revision}" if revision != "unknown" else repository_url
    )

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "revision": revision[:12] if revision != "unknown" else revision,
                "revision_url": revision_url,
                "cache_bust": int(time.time()),
                "repository_url": repository_url,
                "repository_discussions_url": f"{repository_url}/discussions",
            },
        )

    app.mount("/static", StaticFiles(directory=str(package_dir / "static")), name="static")
    return app
