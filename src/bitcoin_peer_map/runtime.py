"""Composition root for application services and worker lifecycle."""

from __future__ import annotations

import threading

from .preferences import PreferenceStore
from .rpc import BitcoinRpcClient
from .services.connectivity import ConnectivityService
from .services.geoip import GeoDatabase
from .services.node import NodeService
from .services.peers import PeerService
from .services.system_metrics import SystemMetrics
from .services.updates import UpdateService
from .settings import AppSettings


class AppRuntime:
    def __init__(self, settings: AppSettings, version: str):
        self.settings = settings
        self.stop_event = threading.Event()
        self.preferences_store = PreferenceStore(settings.data_dir / "settings.json")
        self.preferences = self.preferences_store.load()
        if settings.geoip_auto_update_override is not None:
            self.preferences.geoip_auto_update = settings.geoip_auto_update_override

        self.rpc = BitcoinRpcClient(settings)
        self.geo_database = GeoDatabase(settings.data_dir, settings.geoip_enabled)
        self.connectivity = ConnectivityService(self.stop_event)
        self.metrics = SystemMetrics(self.stop_event)
        self.peers = PeerService(
            self.rpc,
            self.geo_database,
            self.connectivity,
            self.metrics,
            self.stop_event,
        )
        self.node = NodeService(
            self.rpc,
            self.connectivity,
            self.geo_database,
            lambda: self.preferences.geoip_auto_update,
        )
        self.updates = UpdateService(settings.github_repository, version)
        self._geoip_update_thread: threading.Thread | None = None

    def start(self) -> None:
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.preferences_store.save(self.preferences)
        self.geo_database.initialize()
        self.metrics.start()
        self.peers.start()
        if self.geo_database.enabled and self.preferences.geoip_auto_update:
            self._geoip_update_thread = threading.Thread(
                target=self.geo_database.update,
                daemon=True,
                name="geoip-dataset-update",
            )
            self._geoip_update_thread.start()

    def stop(self) -> None:
        self.peers.stop()

    def toggle_geoip_auto_update(self) -> bool:
        self.preferences.geoip_auto_update = not self.preferences.geoip_auto_update
        self.preferences_store.save(self.preferences)
        return self.preferences.geoip_auto_update
