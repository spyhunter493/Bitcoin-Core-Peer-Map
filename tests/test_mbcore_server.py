from pathlib import Path

import pytest

from web import MBCoreServer as server


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
                'MBTC_CLI_PATH="/usr/bin/bitcoin-cli"',
                'MBTC_DATADIR="/data/Bitcoin Core"',
                'MBTC_CONF="/config/bitcoin.conf"',
                f'MBTC_NETWORK="{network}"',
            ]
        )
        + '\n'
    )
    monkeypatch.setattr(server, "CONFIG_FILE", config_file)

    config = server.Config()
    assert config.load() is True

    command = config.get_cli_command()
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
    assert server.Config().load() is False


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

