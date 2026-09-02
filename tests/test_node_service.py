from typing import Any

from rpc import RpcError
from services.node import NodeService


class Rpc:
    def call(self, method: str, *params: Any, **kwargs: Any) -> Any:
        del params, kwargs
        responses = {
            "getbestblockhash": "block-hash",
            "getblockheader": {"height": 1, "time": 2},
            "getblockchaininfo": {},
            "getindexinfo": {},
            "getnetworkinfo": {"connections": 3, "localaddresses": []},
            "getmempoolinfo": {"size": 4},
        }
        return responses[method]


class Connectivity:
    def __init__(self):
        self.price_fetched = False

    def fetch_price(self, currency: str) -> float:
        assert currency == "NZD"
        self.price_fetched = True
        return 123.45

    def snapshot(self) -> dict[str, Any]:
        assert self.price_fetched
        return {
            "last_known_price": "123.45",
            "last_price_currency": "NZD",
            "last_price_error": None,
            "internet_state": "green",
            "api_available": True,
            "geo_db_only_mode": False,
        }


class GeoDatabase:
    enabled = True

    def stats(self) -> dict[str, Any]:
        return {"status": "ok", "entries": 0}


class BlocksRpc:
    def call(self, method: str, *params: Any, **kwargs: Any) -> Any:
        del kwargs
        if method == "getblockchaininfo":
            return {"chain": "main", "blocks": 101}
        if method == "getblockhash":
            return f"hash-{params[0]}"
        if method == "getblock":
            height = int(str(params[0]).split("-")[1])
            return {
                "time": 1_700_000_000 + height,
                "size": height * 1000,
                "weight": height * 4000,
                "nTx": height - 90,
                "version": 536870912,
                "difficulty": 123_456_789_012_345,
            }
        raise AssertionError(f"unexpected RPC method {method}")


class ErrorRpc:
    def call(self, method: str, *params: Any, **kwargs: Any) -> Any:
        del method, params, kwargs
        raise RpcError("rpc unavailable")


def test_dashboard_info_snapshots_connectivity_after_price_fetch() -> None:
    service = NodeService(Rpc(), Connectivity(), GeoDatabase(), lambda: True)

    result = service.dashboard_info("nzd")

    assert result["btc_price"] == 123.45
    assert result["last_known_price"] == "123.45"
    assert result["last_price_currency"] == "NZD"


def test_recent_blocks_returns_tip_first_with_summary(monkeypatch) -> None:
    monkeypatch.setattr("services.node.time.time", lambda: 1_700_000_200)
    service = NodeService(BlocksRpc(), Connectivity(), GeoDatabase(), lambda: True)

    result = service.recent_blocks(2)

    assert result["success"] is True
    assert result["error"] is None
    assert [block["height"] for block in result["blocks"]] == [101, 100]
    assert result["blocks"][0]["hash"] == "hash-101"
    assert result["blocks"][0]["age_seconds"] == 99
    assert result["blocks"][1]["tx_count"] == 10
    assert result["summary"]["chain"] == "main"
    assert result["summary"]["tip_height"] == 101
    assert result["summary"]["count"] == 2
    assert result["summary"]["total_size"] == 201000
    assert result["summary"]["total_transactions"] == 21
    assert result["summary"]["avg_transactions"] == 10.5


def test_recent_blocks_reports_rpc_errors() -> None:
    service = NodeService(ErrorRpc(), Connectivity(), GeoDatabase(), lambda: True)

    result = service.recent_blocks(2)

    assert result == {
        "success": False,
        "summary": None,
        "blocks": [],
        "error": "rpc unavailable",
    }
