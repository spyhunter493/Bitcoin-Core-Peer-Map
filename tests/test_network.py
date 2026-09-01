import pytest

from bitcoin_peer_map.network import (
    format_duration,
    is_private_address,
    network_type,
    normalize_peer_address,
    split_peer_address,
)


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("1.2.3.4:8333", ("1.2.3.4", "8333")),
        ("[2001:db8::1]:8333", ("2001:db8::1", "8333")),
        ("example.onion:8333", ("example.onion", "8333")),
    ],
)
def test_split_peer_address(address: str, expected: tuple[str, str]) -> None:
    assert split_peer_address(address) == expected


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("1.2.3.4", "1.2.3.4:8333"),
        ("2001:4860:4860::8888", "[2001:4860:4860::8888]:8333"),
        ("example.onion", "example.onion:8333"),
        ("example.b32.i2p:0", "example.b32.i2p:0"),
    ],
)
def test_normalize_peer_address(address: str, expected: str) -> None:
    assert normalize_peer_address(address) == expected


def test_network_and_private_address_detection() -> None:
    assert network_type("[2001:4860:4860::8888]:8333") == "ipv6"
    assert network_type("example.onion:8333") == "onion"
    assert is_private_address("192.168.1.1") is True
    assert is_private_address("8.8.8.8") is False


def test_duration_uses_two_significant_units() -> None:
    assert format_duration(90061) == "1d1h"
    assert format_duration(61) == "1m1s"
