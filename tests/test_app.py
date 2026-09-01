from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from bitcoin_peer_map.app import create_app
from bitcoin_peer_map.settings import AppSettings


class FakeRuntime:
    def __init__(self):
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


def settings(tmp_path: Path) -> AppSettings:
    return AppSettings.from_env(
        {
            "BITCOIN_RPC_HOST": "bitcoin",
            "BITCOIN_RPC_USER": "bpm",
            "BITCOIN_RPC_PASSWORD": "secret",
            "BPM_DATA_DIR": str(tmp_path),
        }
    )


def test_application_factory_serves_health_dashboard_and_assets(tmp_path: Path) -> None:
    runtime: Any = FakeRuntime()
    app = create_app(settings(tmp_path), runtime)

    with TestClient(app) as client:
        assert runtime.started is True
        assert client.get("/healthz").json() == {"status": "ok"}
        assert "Bitcoin Peer Map" in client.get("/").text
        assert client.get("/static/js/app.js").status_code == 200

    assert runtime.stopped is True
