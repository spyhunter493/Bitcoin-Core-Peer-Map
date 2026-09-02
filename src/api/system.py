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
