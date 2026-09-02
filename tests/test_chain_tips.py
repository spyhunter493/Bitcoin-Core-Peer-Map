from typing import Any

from rpc import RpcError
from services.node import NodeService


class Connectivity:
    def fetch_price(self, currency: str) -> float:
        del currency
        return 0.0

    def snapshot(self) -> dict[str, Any]:
        return {}


class GeoDatabase:
    enabled = True

    def stats(self) -> dict[str, Any]:
        return {}


class ChainTipsRpc:
    def call(self, method: str, *params: Any, **kwargs: Any) -> Any:
        del kwargs
        if method == "getchaintips":
            return [
                {"height": 98, "hash": "headers-hash", "branchlen": 1, "status": "headers-only"},
                {"height": 101, "hash": "active-hash", "branchlen": 0, "status": "active"},
                {"height": 99, "hash": "fork-hash", "branchlen": 2, "status": "valid-fork"},
            ]
        if method == "getblockchaininfo":
            return {"chain": "main", "blocks": 101, "bestblockhash": "active-hash"}
        if method == "getblockheader":
            times = {
                "active-hash": 1_700_000_101,
                "fork-hash": 1_700_000_099,
                "headers-hash": 1_700_000_098,
            }
            return {"time": times[params[0]]}
        raise AssertionError(f"unexpected RPC method {method}")


class ErrorRpc:
    def call(self, method: str, *params: Any, **kwargs: Any) -> Any:
        del method, params, kwargs
        raise RpcError("rpc unavailable")


def test_chain_tips_sorts_active_tip_first_and_counts_statuses(monkeypatch) -> None:
    monkeypatch.setattr("services.node.time.time", lambda: 1_700_000_200)
    service = NodeService(ChainTipsRpc(), Connectivity(), GeoDatabase(), lambda: True)

    result = service.chain_tips()

    assert result["success"] is True
    assert result["error"] is None
    assert [tip["status"] for tip in result["tips"]] == [
        "active",
        "valid-fork",
        "headers-only",
    ]
    assert result["tips"][0]["age_seconds"] == 99
    assert result["summary"]["chain"] == "main"
    assert result["summary"]["best_height"] == 101
    assert result["summary"]["best_hash"] == "active-hash"
    assert result["summary"]["total"] == 3
    assert result["summary"]["active_count"] == 1
    assert result["summary"]["non_active_count"] == 2
    assert result["summary"]["fork_count"] == 1
    assert result["summary"]["headers_only_count"] == 1
    assert result["summary"]["latest_non_active_height"] == 99
    assert result["summary"]["latest_non_active_status"] == "valid-fork"
    assert result["summary"]["counts_by_status"] == {
        "headers-only": 1,
        "active": 1,
        "valid-fork": 1,
    }


def test_chain_tips_reports_rpc_errors() -> None:
    service = NodeService(ErrorRpc(), Connectivity(), GeoDatabase(), lambda: True)

    result = service.chain_tips()

    assert result == {
        "success": False,
        "summary": None,
        "tips": [],
        "error": "rpc unavailable",
    }
