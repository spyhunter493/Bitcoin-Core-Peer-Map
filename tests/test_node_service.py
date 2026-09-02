from typing import Any

from bitcoin_peer_map.services.node import NodeService


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


def test_dashboard_info_snapshots_connectivity_after_price_fetch() -> None:
    service = NodeService(Rpc(), Connectivity(), GeoDatabase(), lambda: True)

    result = service.dashboard_info("nzd")

    assert result["btc_price"] == 123.45
    assert result["last_known_price"] == "123.45"
    assert result["last_price_currency"] == "NZD"
