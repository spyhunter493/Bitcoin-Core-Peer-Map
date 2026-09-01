"""FastAPI dependencies shared by API routers."""

from fastapi import Request

from ..runtime import AppRuntime


def runtime_from(request: Request) -> AppRuntime:
    return request.app.state.runtime
