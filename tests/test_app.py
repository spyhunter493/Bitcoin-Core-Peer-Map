from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app import create_app
from settings import AppSettings


class FakeRuntime:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.metrics = FakeMetrics()

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class FakeMetrics:
    def summary(self) -> dict[str, float]:
        return {"cpu_pct": 12.5}


def settings(tmp_path: Path) -> AppSettings:
    return AppSettings.from_env(
        {
            "BITCOIN_RPC_HOST": "bitcoin",
            "BITCOIN_RPC_USER": "bpm",
            "BITCOIN_RPC_PASSWORD": "secret",
            "BPM_DATA_DIR": str(tmp_path),
            "BPM_BUILD_REVISION": "abcdef0123456789abcdef0123456789abcdef01",
        }
    )


def test_application_factory_serves_health_dashboard_and_assets(tmp_path: Path) -> None:
    runtime: Any = FakeRuntime()
    app = create_app(settings(tmp_path), runtime)

    with TestClient(app) as client:
        assert runtime.started is True
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/api/stats").json() == {"system_stats": {"cpu_pct": 12.5}}
        dashboard = client.get("/")
        assert "Bitcoin Peer Map" in dashboard.text
        assert "abcdef0" in dashboard.text
        assert dashboard.headers["cache-control"] == "no-cache"
        assert 'data-asset-revision="abcdef0123456789abcdef0123456789abcdef01"' in dashboard.text
        assert "/static/js/app.js?v=abcdef0123456789abcdef0123456789abcdef01" in dashboard.text
        assert (
            "https://github.com/spyhunter493/bitcoin-peer-map/commit/"
            "abcdef0123456789abcdef0123456789abcdef01" in dashboard.text
        )
        assert "bc1qnngus06lk0e60e05yq902e9edx7kt4kcuuuy72" in dashboard.text
        assert "Created by" not in dashboard.text

        unversioned_asset = client.get("/static/js/app.js", headers={"Accept-Encoding": "identity"})
        assert unversioned_asset.status_code == 200
        assert unversioned_asset.headers["cache-control"] == ("public, max-age=0, must-revalidate")

        versioned_asset = client.get(
            "/static/js/app.js?v=abcdef0123456789abcdef0123456789abcdef01",
            headers={"Accept-Encoding": "gzip"},
        )
        assert versioned_asset.status_code == 200
        assert versioned_asset.headers["cache-control"] == ("public, max-age=31536000, immutable")
        assert versioned_asset.headers["content-encoding"] == "gzip"

        assert client.get("/api/changes").status_code == 404
        assert client.get("/api/netspeed").status_code == 404
        assert client.get("/api/update-check").status_code == 404

    assert runtime.stopped is True
