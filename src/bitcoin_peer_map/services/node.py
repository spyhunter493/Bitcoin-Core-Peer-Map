"""Dashboard queries and peer-management operations against Bitcoin RPC."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from ..network import normalize_peer_address, split_peer_address
from ..rpc import BitcoinRpcClient, RpcError
from .connectivity import ConnectivityService
from .geoip import GeoDatabase


class NodeService:
    def __init__(
        self,
        rpc: BitcoinRpcClient,
        connectivity: ConnectivityService,
        geo_database: GeoDatabase,
        auto_update_enabled: Callable[[], bool],
    ):
        self.rpc = rpc
        self.connectivity = connectivity
        self.geo_database = geo_database
        self.auto_update_enabled = auto_update_enabled

    def dashboard_info(self, currency: str = "USD") -> dict[str, Any]:
        currency = currency.upper()
        price = self.connectivity.fetch_price(currency)
        connectivity = self.connectivity.snapshot()
        result: dict[str, Any] = {
            "btc_price": price,
            "btc_currency": currency,
            "last_block": None,
            "blockchain": None,
            "network_scores": None,
            "geo_db_stats": None,
            "connected": None,
            "mempool_size": None,
            "subversion": None,
            "last_known_price": connectivity["last_known_price"],
            "last_price_currency": connectivity["last_price_currency"],
            "last_price_error": connectivity["last_price_error"],
            "internet_state": connectivity["internet_state"],
            "api_available": connectivity["api_available"],
            "geo_db_only_mode": connectivity["geo_db_only_mode"],
        }

        try:
            block_hash = self.rpc.call("getbestblockhash", timeout=10)
            header = self.rpc.call("getblockheader", block_hash, timeout=10)
            result["last_block"] = {
                "height": header.get("height", 0),
                "time": header.get("time", 0),
            }
        except RpcError as exc:
            print(f"Could not load last block: {exc}")

        try:
            blockchain = self.rpc.call("getblockchaininfo", timeout=10)
            indexed = False
            try:
                indexed = "txindex" in self.rpc.call("getindexinfo", timeout=10)
            except RpcError:
                pass
            result["blockchain"] = {
                "size_gb": round(blockchain.get("size_on_disk", 0) / 1e9, 1),
                "pruned": blockchain.get("pruned", False),
                "indexed": indexed,
                "ibd": blockchain.get("initialblockdownload", False),
            }
        except RpcError as exc:
            print(f"Could not load blockchain details: {exc}")

        try:
            network = self.rpc.call("getnetworkinfo", timeout=10)
            result["subversion"] = network.get("subversion", "")
            result["connected"] = network.get("connections", 0)
            scores: dict[str, int | None] = {"ipv4": None, "ipv6": None}
            for local_address in network.get("localaddresses", []):
                address = local_address.get("address", "")
                if address.endswith((".onion", ".i2p")) or address.startswith(("fc", "fd")):
                    continue
                family = "ipv6" if ":" in address else "ipv4"
                score = local_address.get("score", 0)
                if scores[family] is None or score > scores[family]:
                    scores[family] = score
            result["network_scores"] = scores
        except RpcError as exc:
            print(f"Could not load network details: {exc}")

        try:
            result["mempool_size"] = self.rpc.call("getmempoolinfo", timeout=10).get("size", 0)
        except RpcError as exc:
            print(f"Could not load mempool details: {exc}")

        geo_stats = self.geo_database.stats()
        if geo_stats.get("entries", 0):
            oldest = geo_stats.get("oldest_updated")
            newest = geo_stats.get("last_updated")
            geo_stats["oldest_age_days"] = int((time.time() - oldest) / 86400) if oldest else None
            geo_stats["newest_age_days"] = int((time.time() - newest) / 86400) if newest else None
            geo_stats["newest_age_seconds"] = int(time.time() - newest) if newest else None
        geo_stats.update(
            auto_lookup=self.geo_database.enabled,
            auto_update=self.auto_update_enabled(),
            db_only_mode=connectivity["geo_db_only_mode"],
        )
        result["geo_db_stats"] = geo_stats
        return result

    def mempool(self, currency: str = "USD") -> dict[str, Any]:
        result = {"mempool": None, "btc_price": None, "error": None}
        try:
            result["mempool"] = self.rpc.call("getmempoolinfo")
        except RpcError as exc:
            result["error"] = str(exc)
        result["btc_price"] = self.connectivity.fetch_price(currency.upper())
        return result

    def blockchain(self) -> dict[str, Any]:
        try:
            return {"blockchain": self.rpc.call("getblockchaininfo"), "error": None}
        except RpcError as exc:
            return {"blockchain": None, "error": str(exc)}

    async def disconnect(self, peer_id: Any) -> dict[str, Any]:
        if peer_id is None:
            return {"success": False, "error": "peer_id is required"}
        try:
            await asyncio.to_thread(self.rpc.call, "disconnectnode", "", int(peer_id))
            return {"success": True}
        except (RpcError, TypeError, ValueError) as exc:
            return {"success": False, "error": str(exc)}

    async def ban(self, peer_id: Any) -> dict[str, Any]:
        if peer_id is None:
            return {"success": False, "error": "peer_id is required"}
        try:
            peers = await asyncio.to_thread(self.rpc.call, "getpeerinfo")
            peer = next((peer for peer in peers if peer.get("id") == int(peer_id)), None)
            if peer is None:
                return {"success": False, "error": f"Peer ID {peer_id} not found"}
            peer_network = peer.get("network", "ipv4")
            if peer_network not in {"ipv4", "ipv6"}:
                return {
                    "success": False,
                    "error": f"Cannot ban {peer_network.upper()} peers; only IPv4 and IPv6 addresses can be banned",
                }
            host, _ = split_peer_address(peer.get("addr", ""))
            await asyncio.to_thread(self.rpc.call, "setban", host, "add", 86400)
            return {"success": True, "banned_ip": host, "network": peer_network}
        except (RpcError, TypeError, ValueError) as exc:
            return {"success": False, "error": str(exc)}

    async def unban(self, address: str | None) -> dict[str, Any]:
        if not address:
            return {"success": False, "error": "address is required"}
        try:
            await asyncio.to_thread(self.rpc.call, "setban", address, "remove")
            return {"success": True}
        except RpcError as exc:
            return {"success": False, "error": str(exc)}

    def bans(self) -> dict[str, Any]:
        try:
            return {"success": True, "bans": self.rpc.call("listbanned")}
        except RpcError as exc:
            return {"success": False, "error": str(exc), "bans": []}

    def clear_bans(self) -> dict[str, Any]:
        try:
            self.rpc.call("clearbanned")
            return {"success": True}
        except RpcError as exc:
            return {"success": False, "error": str(exc)}

    async def connect(self, address: str) -> dict[str, Any]:
        try:
            normalized = normalize_peer_address(address)
            await asyncio.to_thread(self.rpc.call, "addnode", normalized, "onetry")
            return {"success": True, "address": normalized}
        except (RpcError, ValueError) as exc:
            return {"success": False, "error": str(exc)}
