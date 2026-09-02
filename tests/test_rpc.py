from typing import Any

import pytest

from rpc import BitcoinRpcClient, RpcAuthenticationError, RpcError
from settings import AppSettings


class Response:
    def __init__(self, status_code: int, body: dict[str, Any]):
        self.status_code = status_code
        self._body = body

    def json(self) -> dict[str, Any]:
        return self._body


class Session:
    def __init__(self, response: Response):
        self.response = response
        self.request: dict[str, Any] | None = None

    def post(self, url: str, **kwargs: Any) -> Response:
        self.request = {"url": url, **kwargs}
        return self.response


def settings() -> AppSettings:
    return AppSettings.from_env(
        {
            "BITCOIN_RPC_HOST": "bitcoin",
            "BITCOIN_RPC_USER": "bpm",
            "BITCOIN_RPC_PASSWORD": "secret",
        }
    )


def test_rpc_client_sends_json_rpc_request(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Session(Response(200, {"result": {"connections": 8}, "error": None}))
    client = BitcoinRpcClient(settings())
    monkeypatch.setattr(client, "_session", lambda: session)

    result = client.call("getnetworkinfo")

    assert result == {"connections": 8}
    assert session.request is not None
    assert session.request["url"] == "http://bitcoin:8332"
    assert session.request["json"]["method"] == "getnetworkinfo"
    assert session.request["json"]["params"] == []


def test_rpc_client_reports_authentication_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    client = BitcoinRpcClient(settings())
    monkeypatch.setattr(client, "_session", lambda: Session(Response(401, {})))

    with pytest.raises(RpcAuthenticationError, match="authentication failed"):
        client.call("getnetworkinfo")


def test_rpc_client_reports_bitcoin_error(monkeypatch: pytest.MonkeyPatch) -> None:
    response = Response(500, {"result": None, "error": {"code": -8, "message": "bad peer"}})
    client = BitcoinRpcClient(settings())
    monkeypatch.setattr(client, "_session", lambda: Session(response))

    with pytest.raises(RpcError, match="bad peer"):
        client.call("addnode", "invalid", "onetry")
