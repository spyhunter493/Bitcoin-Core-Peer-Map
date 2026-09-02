"""Container metrics, health, and event-stream endpoints."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from runtime import AppRuntime

from .dependencies import runtime_from

router = APIRouter()


@router.get("/healthz", include_in_schema=False)
def health():
    return {"status": "ok"}


@router.get("/api/stats")
def stats(runtime: AppRuntime = Depends(runtime_from)):
    return {"system_stats": runtime.metrics.summary()}


@router.get("/api/config")
def config(request: Request, runtime: AppRuntime = Depends(runtime_from)):
    settings = runtime.settings
    return {
        "bitcoin_rpc": {
            "scheme": settings.rpc_scheme,
            "host": settings.rpc_host,
            "port": settings.rpc_port,
            "network": settings.bitcoin_network,
            "verify_tls": settings.rpc_verify_tls,
            "timeout": settings.rpc_timeout,
            "startup_timeout": settings.rpc_startup_timeout,
            "username_configured": bool(settings.rpc_user),
            "password_configured": bool(settings.rpc_password),
            "password_file_configured": settings.rpc_password_file_configured,
            "endpoint": settings.rpc_url,
        },
        "server": {
            "listen_address": settings.listen_address,
            "listen_port": settings.listen_port,
        },
        "geoip": {
            "enabled": settings.geoip_enabled,
            "auto_update_override": settings.geoip_auto_update_override,
        },
        "build": {
            "revision": settings.build_revision,
            "revision_known": settings.build_revision != "unknown",
            "asset_revision": getattr(request.app.state, "asset_revision", "unknown"),
            "revision_url": getattr(request.app.state, "revision_url", None),
        },
        "repository": {
            "github": settings.github_repository,
            "url": getattr(request.app.state, "repository_url", None),
        },
        "data": {
            "data_dir": str(settings.data_dir),
        },
    }


@router.get("/api/stream/system")
async def system_stream(request: Request, runtime: AppRuntime = Depends(runtime_from)):
    async def generate():
        yield {"event": "message", "data": json.dumps({"type": "connected"})}
        while not runtime.stop_event.is_set():
            if await request.is_disconnected():
                break
            snapshot = runtime.metrics.latest()
            if snapshot:
                yield {"event": "system", "data": json.dumps(snapshot)}
            await asyncio.sleep(0.5)

    return EventSourceResponse(generate())
