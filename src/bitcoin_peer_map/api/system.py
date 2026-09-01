"""Container metrics, health, and update endpoints."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from ..runtime import AppRuntime
from .dependencies import runtime_from

router = APIRouter()


@router.get("/healthz", include_in_schema=False)
def health():
    return {"status": "ok"}


@router.get("/api/stats")
def stats(runtime: AppRuntime = Depends(runtime_from)):
    return runtime.peers.stats()


@router.get("/api/netspeed")
def network_speed(runtime: AppRuntime = Depends(runtime_from)):
    return runtime.metrics.network_speed()


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


@router.get("/api/update-check")
def update_check(runtime: AppRuntime = Depends(runtime_from)):
    return runtime.updates.check()
