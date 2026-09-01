import asyncio
import sqlite3
import threading
from pathlib import Path

import pytest

from bitcoin_peer_map import server


@pytest.mark.parametrize(
    ("network", "expected_flag"),
    [
        ("main", None),
        ("test", "-testnet"),
        ("signet", "-signet"),
        ("regtest", "-regtest"),
    ],
)
def test_config_builds_network_specific_cli_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, network: str, expected_flag: str | None
) -> None:
    config_file = tmp_path / "config.conf"
    config_file.write_text(
        '\n'.join(
            [
                'BITCOIN_CLI="/usr/bin/bitcoin-cli"',
                'BITCOIN_DATA_DIR="/data/Bitcoin Core"',
                'BITCOIN_CONFIG_FILE="/config/bitcoin.conf"',
                f'BITCOIN_NETWORK="{network}"',
            ]
        )
        + '\n'
    )
    monkeypatch.setattr(server, "CONFIG_FILE", config_file)

    node_config = server.NodeConfig()
    assert node_config.load() is True

    command = node_config.get_cli_command()
    assert command[:3] == [
        "/usr/bin/bitcoin-cli",
        "-datadir=/data/Bitcoin Core",
        "-conf=/config/bitcoin.conf",
    ]
    if expected_flag is None:
        assert len(command) == 3
    else:
        assert command[-1] == expected_flag


def test_config_load_fails_when_file_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "CONFIG_FILE", tmp_path / "missing.conf")
    assert server.NodeConfig().load() is False


def test_config_load_fails_without_bitcoin_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = tmp_path / "config.conf"
    config_file.write_text('BITCOIN_NETWORK="main"\n')
    monkeypatch.setattr(server, "CONFIG_FILE", config_file)

    assert server.NodeConfig().load() is False


def test_cli_info_uses_node_config(monkeypatch: pytest.MonkeyPatch) -> None:
    node_config = server.NodeConfig()
    node_config.cli = "/usr/bin/bitcoin-cli"
    node_config.data_dir = "/bitcoin"
    node_config.config_file = "/run/bitcoin-peer-map/bitcoin.conf"
    node_config.network = "main"
    monkeypatch.setattr(server, "node_config", node_config)

    result = asyncio.run(server.api_cli_info())

    assert result == {
        "cli_path": "/usr/bin/bitcoin-cli",
        "datadir": "/bitcoin",
        "conf": "/run/bitcoin-peer-map/bitcoin.conf",
        "network": "main",
        "base_command": "/usr/bin/bitcoin-cli -datadir=/bitcoin -conf=/run/bitcoin-peer-map/bitcoin.conf",
    }


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"lat": None, "lon": 10, "country": "NZ"},
        {"lat": 91, "lon": 10, "country": "NZ"},
        {"lat": -45, "lon": 181, "country": "NZ"},
        {"lat": 0, "lon": 0, "country": ""},
    ],
)
def test_invalid_geo_records_are_rejected(data: dict) -> None:
    assert server.is_valid_geo_data(data) is False


def test_valid_geo_record_is_accepted() -> None:
    assert server.is_valid_geo_data({"lat": -36.85, "lon": 174.76, "country": "New Zealand"}) is True


class StreamingResponse:
    def __init__(self, chunks: list[bytes], headers: dict[str, str] | None = None) -> None:
        self.chunks = chunks
        self.headers = headers or {}
        self.status_code = 200

    def __enter__(self) -> "StreamingResponse":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def iter_content(self, chunk_size: int):
        del chunk_size
        yield from self.chunks


def create_geo_database(path: Path, columns: tuple[str, ...], rows: list[tuple] | None = None) -> None:
    definitions = [f'"{column}" TEXT PRIMARY KEY' if column == "ip" else f'"{column}"' for column in columns]
    with sqlite3.connect(path) as conn:
        conn.execute(f"CREATE TABLE geo_cache ({','.join(definitions)})")
        if rows:
            placeholders = ",".join("?" for _ in columns)
            conn.executemany(f"INSERT INTO geo_cache VALUES ({placeholders})", rows)


def configure_geo_update(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    data_dir = tmp_path / "data"
    temp_dir = data_dir / "tmp"
    data_dir.mkdir()
    temp_dir.mkdir()
    database = data_dir / "geo.db"
    monkeypatch.setattr(server, "TMP_DIR", temp_dir)
    monkeypatch.setattr(server, "GEO_DB_FILE", database)
    monkeypatch.setattr(server, "geo_db_enabled", True)
    monkeypatch.setattr(server, "geo_db_update_lock", threading.Lock())
    return temp_dir, database


def test_geodb_update_rejects_oversized_stream_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_dir, _ = configure_geo_update(tmp_path, monkeypatch)
    monkeypatch.setattr(server, "GEO_DB_MAX_DOWNLOAD_BYTES", 10)
    monkeypatch.setattr(
        server.requests,
        "get",
        lambda *_args, **_kwargs: StreamingResponse([b"123456", b"78901"]),
    )

    result = server.api_geodb_update()

    assert result["success"] is False
    assert "size limit" in result["message"]
    assert list(temp_dir.iterdir()) == []


def test_geodb_update_rejects_unexpected_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_dir, _ = configure_geo_update(tmp_path, monkeypatch)
    remote_database = tmp_path / "wrong-schema.db"
    create_geo_database(remote_database, server.GEO_DB_COLUMNS[:-1])
    remote_bytes = remote_database.read_bytes()
    monkeypatch.setattr(
        server.requests,
        "get",
        lambda *_args, **_kwargs: StreamingResponse([remote_bytes]),
    )

    result = server.api_geodb_update()

    assert result == {"success": False, "message": "Downloaded database has an unexpected geo_cache schema"}
    assert list(temp_dir.iterdir()) == []


def test_geodb_update_merges_valid_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    temp_dir, local_database = configure_geo_update(tmp_path, monkeypatch)
    local_row = ("192.0.2.1",) + (None,) * (len(server.GEO_DB_COLUMNS) - 1)
    remote_row = ("198.51.100.1",) + (None,) * (len(server.GEO_DB_COLUMNS) - 1)
    create_geo_database(local_database, server.GEO_DB_COLUMNS, [local_row])
    remote_database = tmp_path / "remote.db"
    create_geo_database(remote_database, server.GEO_DB_COLUMNS, [remote_row])
    remote_bytes = remote_database.read_bytes()
    monkeypatch.setattr(
        server.requests,
        "get",
        lambda *_args, **_kwargs: StreamingResponse([remote_bytes]),
    )

    result = server.api_geodb_update()

    assert result == {"success": True, "message": "+1 new entries (2 total)"}
    with sqlite3.connect(local_database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM geo_cache").fetchone()[0] == 2
    assert list(temp_dir.iterdir()) == []


def test_geodb_update_rejects_concurrent_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configure_geo_update(tmp_path, monkeypatch)
    assert server.geo_db_update_lock.acquire(blocking=False)
    try:
        assert server.api_geodb_update() == {
            "success": False,
            "message": "Geo database update already in progress",
        }
    finally:
        server.geo_db_update_lock.release()
