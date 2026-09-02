from pathlib import Path

import pytest

from main import _wait_for_rpc
from settings import AppSettings, ConfigurationError


class Rpc:
    def check_connection(self):
        return {"connections": 1}

    def call(self, method: str):
        assert method == "getblockchaininfo"
        return {"chain": "test"}


class Runtime:
    def __init__(self, settings: AppSettings):
        self.settings = settings
        self.rpc = Rpc()


def test_startup_rejects_network_mismatch(tmp_path: Path) -> None:
    settings = AppSettings.from_env(
        {
            "BITCOIN_RPC_HOST": "bitcoin",
            "BITCOIN_RPC_USER": "bpm",
            "BITCOIN_RPC_PASSWORD": "secret",
            "BPM_DATA_DIR": str(tmp_path),
            "BITCOIN_NETWORK": "main",
        }
    )

    with pytest.raises(ConfigurationError, match="does not match"):
        _wait_for_rpc(Runtime(settings))
