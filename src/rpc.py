"""Bitcoin Core and Bitcoin Knots JSON-RPC client."""

from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass
from typing import Any

import requests

from settings import AppSettings


class RpcError(RuntimeError):
    """A transport or Bitcoin JSON-RPC error."""


class RpcTransportError(RpcError):
    """A retryable network or HTTP transport failure."""


class RpcAuthenticationError(RpcError):
    """Bitcoin RPC rejected the configured credentials."""


@dataclass(frozen=True, slots=True)
class RpcConnectionInfo:
    scheme: str
    host: str
    port: int
    network: str


class BitcoinRpcClient:
    """Thread-local HTTP sessions over a shared immutable configuration."""

    def __init__(self, settings: AppSettings):
        self._settings = settings
        self._request_ids = itertools.count(1)
        self._local = threading.local()

    @property
    def connection_info(self) -> RpcConnectionInfo:
        return RpcConnectionInfo(
            scheme=self._settings.rpc_scheme,
            host=self._settings.rpc_host,
            port=self._settings.rpc_port,
            network=self._settings.bitcoin_network,
        )

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.auth = (
                self._settings.rpc_user,
                self._settings.rpc_password,
            )
            session.headers.update({"Content-Type": "application/json"})
            self._local.session = session
        return session

    def call(self, method: str, *params: Any, timeout: int | None = None) -> Any:
        payload = {
            "jsonrpc": "1.0",
            "id": next(self._request_ids),
            "method": method,
            "params": list(params),
        }
        try:
            response = self._session().post(
                self._settings.rpc_url,
                json=payload,
                timeout=timeout or self._settings.rpc_timeout,
                verify=self._settings.rpc_verify_tls,
            )
        except requests.RequestException as exc:
            raise RpcTransportError(f"Bitcoin RPC request failed: {exc}") from exc

        if response.status_code in {401, 403}:
            raise RpcAuthenticationError("Bitcoin RPC authentication failed")
        try:
            body = response.json()
        except ValueError as exc:
            raise RpcTransportError(
                f"Bitcoin RPC returned HTTP {response.status_code} without JSON"
            ) from exc

        error = body.get("error")
        if error:
            message = error.get("message", str(error)) if isinstance(error, dict) else str(error)
            raise RpcError(message)
        if response.status_code >= 400:
            raise RpcTransportError(f"Bitcoin RPC returned HTTP {response.status_code}")
        return body.get("result")

    def check_connection(self) -> dict[str, Any]:
        result = self.call("getnetworkinfo")
        if not isinstance(result, dict):
            raise RpcError("getnetworkinfo returned an unexpected response")
        return result
