"""Peer address parsing and presentation helpers."""

from __future__ import annotations

import ipaddress

CONNECTION_TYPE_ABBREVIATIONS = {
    "outbound-full-relay": "OFR",
    "block-relay-only": "BLO",
    "inbound": "INB",
    "manual": "MAN",
    "addr-fetch": "FET",
    "feeler": "FEL",
}


def network_type(address: str) -> str:
    value = address.lower()
    if ".onion" in value:
        return "onion"
    if ".i2p" in value:
        return "i2p"
    host, _ = split_peer_address(address)
    if host.lower().startswith(("fc", "fd")):
        return "cjdns"
    if ":" in host:
        return "ipv6"
    return "ipv4"


def split_peer_address(address: str) -> tuple[str, str]:
    if address.startswith("["):
        closing = address.find("]")
        if closing == -1:
            return address, ""
        host = address[1:closing]
        port = address[closing + 2 :] if address[closing + 1 :].startswith(":") else ""
        return host, port
    if address.count(":") == 1:
        return tuple(address.rsplit(":", 1))  # type: ignore[return-value]
    return address, ""


def is_private_address(host: str) -> bool:
    if host in {"localhost", ""}:
        return True
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        return False


def is_public_address(peer_network: str, host: str) -> bool:
    return peer_network in {"ipv4", "ipv6"} and not is_private_address(host)


def normalize_peer_address(address: str, default_port: int = 8333) -> str:
    value = address.strip()
    if not value:
        raise ValueError("address is required")
    lower = value.lower()
    if ".b32.i2p" in lower:
        if not value.endswith(":0"):
            raise ValueError("I2P addresses must end with :0")
        return value
    if ".onion" in lower:
        return value if ":" in value else f"{value}:{default_port}"
    if value.startswith("["):
        if "]" not in value:
            raise ValueError("IPv6 addresses must use [address] notation")
        return value if "]:" in value else f"{value}:{default_port}"
    if value.count(":") > 1:
        return f"[{value}]:{default_port}"
    return value if ":" in value else f"{value}:{default_port}"


def format_bytes(value: int) -> str:
    if value < 1024:
        return f"{value}B"
    if value < 1024**2:
        return f"{value / 1024:.1f}KB"
    if value < 1024**3:
        return f"{value / 1024**2:.1f}MB"
    return f"{value / 1024**3:.2f}GB"


def abbreviate_connection_type(connection_type: str) -> str:
    if connection_type in CONNECTION_TYPE_ABBREVIATIONS:
        return CONNECTION_TYPE_ABBREVIATIONS[connection_type]
    return connection_type[:3].upper() if connection_type else "-"


def format_duration(seconds: int) -> str:
    units = (
        (86400, "d"),
        (3600, "h"),
        (60, "m"),
        (1, "s"),
    )
    parts: list[str] = []
    remainder = max(0, seconds)
    for divisor, suffix in units:
        amount, remainder = divmod(remainder, divisor)
        if amount:
            parts.append(f"{amount}{suffix}")
        if len(parts) == 2:
            break
    return "".join(parts) or "0s"
