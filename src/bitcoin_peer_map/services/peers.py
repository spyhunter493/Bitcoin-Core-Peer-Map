"""Peer polling, geolocation enrichment, and in-memory dashboard state."""

from __future__ import annotations

import queue
import threading
import time
from datetime import datetime
from typing import Any

import requests

from ..network import (
    abbreviate_connection_type,
    format_bytes,
    format_duration,
    is_private_address,
    is_public_address,
    network_type,
    split_peer_address,
)
from ..rpc import BitcoinRpcClient, RpcError
from .connectivity import ConnectivityService
from .geoip import GeoDatabase, is_valid_geo_data
from .system_metrics import SystemMetrics

GEO_API_URL = "http://ip-api.com/json"
GEO_API_FIELDS = (
    "status,continent,continentCode,country,countryCode,region,regionName,city,"
    "district,zip,lat,lon,timezone,offset,currency,isp,org,as,asname,mobile,"
    "proxy,hosting"
)
REFRESH_INTERVAL_SECONDS = 10
RECENT_CHANGE_SECONDS = 20
GEO_API_DELAY_SECONDS = 1.5


class PeerService:
    def __init__(
        self,
        rpc: BitcoinRpcClient,
        geo_database: GeoDatabase,
        connectivity: ConnectivityService,
        metrics: SystemMetrics,
        stop_event: threading.Event,
    ):
        self.rpc = rpc
        self.geo_database = geo_database
        self.connectivity = connectivity
        self.metrics = metrics
        self.stop_event = stop_event

        self._peers: list[dict[str, Any]] = []
        self._peers_lock = threading.Lock()
        self._changes: list[tuple[float, str, dict[str, Any]]] = []
        self._changes_lock = threading.Lock()
        self._geo_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._pending: set[str] = set()
        self._pending_lock = threading.Lock()
        self._geo_cache: dict[str, dict[str, Any]] = {}
        self._geo_cache_lock = threading.Lock()
        self._peer_addresses: dict[str, dict[str, str]] = {}
        self._peer_addresses_lock = threading.Lock()
        self._known_addresses: set[str] = set()
        self._known_addresses_lock = threading.Lock()
        self.update_event = threading.Event()
        self.last_update_type = "connected"
        self._threads: list[threading.Thread] = []

        self.connectivity.set_change_callback(self.broadcast)

    def start(self) -> None:
        self.refresh_known_addresses()
        self._threads = [
            threading.Thread(target=self._refresh_loop, daemon=True, name="peer-refresh"),
            threading.Thread(target=self._geo_loop, daemon=True, name="geoip-lookup"),
        ]
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.update_event.set()
        for thread in self._threads:
            thread.join(timeout=2)

    def broadcast(self, event_type: str, _data: dict[str, Any] | None = None) -> None:
        self.last_update_type = event_type
        self.update_event.set()

    def raw_peers(self) -> list[dict[str, Any]]:
        try:
            peers = self.rpc.call("getpeerinfo")
            return peers if isinstance(peers, list) else []
        except RpcError:
            return []

    def enabled_networks(self) -> list[str]:
        try:
            network_info = self.rpc.call("getnetworkinfo")
        except RpcError:
            return ["ipv4"]
        enabled = [
            item.get("name", "")
            for item in network_info.get("networks", [])
            if item.get("reachable")
        ]
        return enabled or ["ipv4"]

    def refresh_known_addresses(self) -> None:
        try:
            addresses = self.rpc.call("getnodeaddresses", 0)
        except RpcError:
            return
        known = {item.get("address", "") for item in addresses or [] if item.get("address")}
        with self._known_addresses_lock:
            self._known_addresses = known

    def _is_known_address(self, host: str) -> bool:
        with self._known_addresses_lock:
            return host in self._known_addresses

    def _refresh_loop(self) -> None:
        previous_ids: set[str] = set()
        address_refreshes = 0
        while not self.stop_event.is_set():
            peers = self.raw_peers()
            with self._peers_lock:
                self._peers = peers

            address_refreshes += 1
            if address_refreshes >= 6:
                self.refresh_known_addresses()
                address_refreshes = 0

            current_ids: set[str] = set()
            now = time.time()
            for peer in peers:
                peer_id = str(peer.get("id", ""))
                current_ids.add(peer_id)
                address = peer.get("addr", "")
                peer_network = peer.get("network", network_type(address))
                host, port = split_peer_address(address)
                with self._peer_addresses_lock:
                    self._peer_addresses[peer_id] = {
                        "ip": host,
                        "port": port,
                        "network": peer_network,
                    }
                if peer_id not in previous_ids and previous_ids:
                    with self._changes_lock:
                        self._changes.append(
                            (
                                now,
                                "connected",
                                {"ip": host, "port": port, "network": peer_network},
                            )
                        )

                if self.cached_geo(host) is None:
                    if is_public_address(peer_network, host):
                        self.queue_geo_lookup(host, peer_network)
                    else:
                        self._cache_private_address(host)

            for peer_id in previous_ids - current_ids:
                with self._peer_addresses_lock:
                    peer = self._peer_addresses.pop(peer_id, {})
                with self._changes_lock:
                    self._changes.append(
                        (
                            now,
                            "disconnected",
                            {
                                "ip": peer.get("ip", f"peer#{peer_id}"),
                                "port": peer.get("port", ""),
                                "network": peer.get("network", "?"),
                            },
                        )
                    )

            with self._changes_lock:
                self._changes = [
                    change for change in self._changes if now - change[0] < RECENT_CHANGE_SECONDS
                ]
            previous_ids = current_ids
            self.broadcast("peers_update")
            self.stop_event.wait(REFRESH_INTERVAL_SECONDS)

    def cached_geo(self, host: str) -> dict[str, Any] | None:
        with self._geo_cache_lock:
            return self._geo_cache.get(host)

    def _cache_private_address(self, host: str) -> None:
        with self._geo_cache_lock:
            self._geo_cache[host] = self._empty_geo("private")

    def queue_geo_lookup(self, host: str, peer_network: str) -> None:
        with self._pending_lock:
            if host in self._pending:
                return
            self._pending.add(host)
        self._geo_queue.put((host, peer_network))

    @staticmethod
    def _empty_geo(status: str) -> dict[str, Any]:
        return {
            "status": status,
            "continent": "",
            "continentCode": "",
            "country": "",
            "countryCode": "",
            "region": "",
            "regionName": "",
            "city": "",
            "district": "",
            "zip": "",
            "lat": 0,
            "lon": 0,
            "timezone": "",
            "offset": 0,
            "currency": "",
            "isp": "",
            "org": "",
            "as": "",
            "asname": "",
            "mobile": False,
            "proxy": False,
            "hosting": False,
        }

    @staticmethod
    def _normalize_geo(data: dict[str, Any], from_database: bool) -> dict[str, Any]:
        result = PeerService._empty_geo("ok")
        for key in result:
            if key != "status" and key in data:
                result[key] = data[key]
        if from_database:
            result["offset"] = data.get("utc_offset", 0)
            result["as"] = data.get("as_info", "")
        return result

    def _fetch_geo(self, host: str) -> dict[str, Any] | None:
        try:
            response = requests.get(f"{GEO_API_URL}/{host}?fields={GEO_API_FIELDS}", timeout=10)
            if response.status_code != 200:
                self.connectivity.network_failure(geoip_api=True)
                return None
            data = response.json()
            if data.get("status") == "success":
                self.connectivity.network_success(geoip_api=True)
                return data
        except (requests.RequestException, ValueError):
            self.connectivity.network_failure(geoip_api=True)
        return None

    def _geo_loop(self) -> None:
        deferred: list[tuple[str, str]] = []
        while not self.stop_event.is_set():
            try:
                host, peer_network = self._geo_queue.get(timeout=0.5)
            except queue.Empty:
                connectivity = self.connectivity.snapshot()
                if (
                    deferred
                    and connectivity["internet_state"] == "green"
                    and not connectivity["geo_db_only_mode"]
                ):
                    host, peer_network = deferred.pop(0)
                else:
                    continue

            data = self.geo_database.get(host)
            from_database = data is not None
            connectivity = self.connectivity.snapshot()
            skip_api = connectivity["geo_db_only_mode"] or connectivity["internet_state"] in {
                "yellow",
                "red",
            }
            if data is None and skip_api:
                if (host, peer_network) not in deferred:
                    deferred.append((host, peer_network))
            elif data is None:
                data = self._fetch_geo(host)
                if data and is_valid_geo_data(data):
                    self.geo_database.save(host, data)

            with self._geo_cache_lock:
                self._geo_cache[host] = (
                    self._normalize_geo(data, from_database)
                    if data
                    else self._empty_geo("unavailable")
                )
            with self._pending_lock:
                self._pending.discard(host)
            self.broadcast("geo_update")
            if not from_database and not skip_api:
                self.stop_event.wait(GEO_API_DELAY_SECONDS)

    def list_peers(self) -> list[dict[str, Any]]:
        with self._peers_lock:
            peers = list(self._peers)
        result: list[dict[str, Any]] = []
        service_names = {
            "NETWORK": "N",
            "WITNESS": "W",
            "NETWORK_LIMITED": "NL",
            "P2P_V2": "P",
            "COMPACT_FILTERS": "CF",
            "BLOOM": "B",
        }
        for peer in peers:
            address = peer.get("addr", "")
            peer_network = peer.get("network", network_type(address))
            host, port = split_peer_address(address)
            geo = self.cached_geo(host)
            if peer_network in {"onion", "i2p", "cjdns"} or is_private_address(host):
                location_status, location = "private", "PRIVATE"
            elif geo and geo.get("status") == "ok" and geo.get("city"):
                location_status = "ok"
                location = f"{geo['city']}, {geo.get('countryCode', '')}"
            elif geo and geo.get("status") == "unavailable":
                location_status, location = "unavailable", "UNAVAILABLE"
            else:
                location_status, location = "pending", "Stalking..."

            services = peer.get("servicesnames", [])
            connected_at = peer.get("conntime", 0)
            connected_for = (
                format_duration(int(time.time()) - connected_at) if connected_at else "-"
            )
            result.append(
                {
                    "id": peer.get("id"),
                    "network": peer_network,
                    "ip": host,
                    "port": port,
                    "direction": "IN" if peer.get("inbound") else "OUT",
                    "subver": peer.get("subver", "").replace("/", ""),
                    "city": geo.get("city", "") if geo else "",
                    "region": geo.get("region", "") if geo else "",
                    "regionName": geo.get("regionName", "") if geo else "",
                    "country": geo.get("country", "") if geo else "",
                    "countryCode": geo.get("countryCode", "") if geo else "",
                    "continent": geo.get("continent", "") if geo else "",
                    "continentCode": geo.get("continentCode", "") if geo else "",
                    "bytessent": peer.get("bytessent", 0),
                    "bytesrecv": peer.get("bytesrecv", 0),
                    "bytessent_fmt": format_bytes(peer.get("bytessent", 0)),
                    "bytesrecv_fmt": format_bytes(peer.get("bytesrecv", 0)),
                    "ping_ms": int((peer.get("pingtime") or 0) * 1000),
                    "conntime": connected_at,
                    "conntime_fmt": connected_for,
                    "version": peer.get("version", 0),
                    "connection_type": peer.get("connection_type", ""),
                    "connection_type_abbrev": abbreviate_connection_type(
                        peer.get("connection_type", "")
                    ),
                    "services": services,
                    "services_abbrev": " ".join(
                        service_names.get(name, name[:2]) for name in services
                    ),
                    "lat": geo.get("lat", 0) if geo else 0,
                    "lon": geo.get("lon", 0) if geo else 0,
                    "isp": geo.get("isp", "") if geo else "",
                    "district": geo.get("district", "") if geo else "",
                    "zip": geo.get("zip", "") if geo else "",
                    "timezone": geo.get("timezone", "") if geo else "",
                    "offset": geo.get("offset", 0) if geo else 0,
                    "currency": geo.get("currency", "") if geo else "",
                    "org": geo.get("org", "") if geo else "",
                    "as": geo.get("as", "") if geo else "",
                    "asname": geo.get("asname", "") if geo else "",
                    "mobile": geo.get("mobile", False) if geo else False,
                    "proxy": geo.get("proxy", False) if geo else False,
                    "hosting": geo.get("hosting", False) if geo else False,
                    "in_addrman": self._is_known_address(host),
                    "location": location,
                    "location_status": location_status,
                    "addr": address,
                    "minping": peer.get("minping"),
                    "lastsend": peer.get("lastsend"),
                    "lastrecv": peer.get("lastrecv"),
                    "startingheight": peer.get("startingheight"),
                    "synced_headers": peer.get("synced_headers"),
                    "synced_blocks": peer.get("synced_blocks"),
                    "transport_protocol_type": peer.get("transport_protocol_type", ""),
                    "session_id": peer.get("session_id", ""),
                    "addr_relay_enabled": peer.get("addr_relay_enabled"),
                    "bip152_hb_from": peer.get("bip152_hb_from", False),
                    "bip152_hb_to": peer.get("bip152_hb_to", False),
                    "relaytxes": peer.get("relaytxes"),
                    "last_transaction": peer.get("last_transaction", 0),
                    "last_block": peer.get("last_block", 0),
                    "timeoffset": peer.get("timeoffset", 0),
                    "addrlocal": peer.get("addrlocal", ""),
                    "permissions": peer.get("permissions", []),
                    "minfeefilter": peer.get("minfeefilter"),
                    "addr_processed": peer.get("addr_processed", 0),
                    "addr_rate_limited": peer.get("addr_rate_limited", 0),
                    "mapped_as": peer.get("mapped_as"),
                }
            )
        return result

    def recent_changes(self) -> list[dict[str, Any]]:
        with self._changes_lock:
            changes = list(self._changes)
        return [
            {"time": timestamp, "type": change_type, "peer": peer}
            for timestamp, change_type, peer in changes
        ]

    def stats(self) -> dict[str, Any]:
        peers = self.raw_peers()
        network_counts = {
            name: {"in": 0, "out": 0} for name in ("ipv4", "ipv6", "onion", "i2p", "cjdns")
        }
        for peer in peers:
            peer_network = peer.get("network", "ipv4")
            if peer_network in network_counts:
                direction = "in" if peer.get("inbound") else "out"
                network_counts[peer_network][direction] += 1
        with self._pending_lock:
            pending = len(self._pending)
        return {
            "connected": len(peers),
            "networks": network_counts,
            "enabled_networks": self.enabled_networks(),
            "geo_pending": pending,
            "last_update": datetime.now().strftime("%H:%M:%S"),
            "refresh_interval": REFRESH_INTERVAL_SECONDS,
            "system_stats": self.metrics.summary(),
            "geo_entry_count": self.geo_database.stats().get("entries", 0),
        }
