"""Peer list and peer-management endpoints."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ..runtime import AppRuntime
from .dependencies import runtime_from

router = APIRouter(prefix="/api")


class PeerIdRequest(BaseModel):
    peer_id: int | None = None


class AddressRequest(BaseModel):
    address: str = ""


@router.get("/peers")
def list_peers(runtime: AppRuntime = Depends(runtime_from)):
    return runtime.peers.list_peers()


@router.get("/changes")
def recent_changes(runtime: AppRuntime = Depends(runtime_from)):
    return runtime.peers.recent_changes()


@router.get("/events")
async def peer_events(request: Request, runtime: AppRuntime = Depends(runtime_from)):
    async def generate():
        yield {"event": "message", "data": json.dumps({"type": "connected"})}
        while not runtime.stop_event.is_set():
            if await request.is_disconnected():
                break
            signaled = await asyncio.to_thread(runtime.peers.update_event.wait, 2)
            if signaled:
                runtime.peers.update_event.clear()
                event_type = runtime.peers.last_update_type
            else:
                event_type = "keepalive"
            yield {"event": "message", "data": json.dumps({"type": event_type})}

    return EventSourceResponse(generate())


@router.post("/peer/connect")
async def connect_peer(payload: AddressRequest, runtime: AppRuntime = Depends(runtime_from)):
    return await runtime.node.connect(payload.address)


@router.post("/peer/disconnect")
async def disconnect_peer(payload: PeerIdRequest, runtime: AppRuntime = Depends(runtime_from)):
    return await runtime.node.disconnect(payload.peer_id)


@router.post("/peer/ban")
async def ban_peer(payload: PeerIdRequest, runtime: AppRuntime = Depends(runtime_from)):
    return await runtime.node.ban(payload.peer_id)


@router.post("/peer/unban")
async def unban_peer(payload: AddressRequest, runtime: AppRuntime = Depends(runtime_from)):
    return await runtime.node.unban(payload.address)


@router.get("/bans")
def list_bans(runtime: AppRuntime = Depends(runtime_from)):
    return runtime.node.bans()


@router.post("/bans/clear")
def clear_bans(runtime: AppRuntime = Depends(runtime_from)):
    return runtime.node.clear_bans()
