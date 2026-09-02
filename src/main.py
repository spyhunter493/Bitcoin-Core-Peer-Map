"""Container process entrypoint."""

from __future__ import annotations

import sys
import time

import uvicorn

from app import create_app
from rpc import RpcAuthenticationError, RpcError
from runtime import AppRuntime
from settings import AppSettings, ConfigurationError


def _wait_for_rpc(runtime: AppRuntime) -> None:
    settings = runtime.settings
    deadline = time.monotonic() + settings.rpc_startup_timeout
    print(
        "Bitcoin Peer Map: checking Bitcoin RPC at "
        f"{settings.rpc_host}:{settings.rpc_port} ({settings.bitcoin_network})"
    )
    while True:
        try:
            runtime.rpc.check_connection()
            blockchain = runtime.rpc.call("getblockchaininfo")
            reported_network = blockchain.get("chain")
            if reported_network != settings.bitcoin_network:
                raise ConfigurationError(
                    "BITCOIN_NETWORK does not match the node: "
                    f"configured {settings.bitcoin_network}, node reports {reported_network}"
                )
            print("Bitcoin Peer Map: Bitcoin RPC is available")
            return
        except RpcAuthenticationError:
            raise
        except RpcError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(2)


def main() -> None:
    try:
        settings = AppSettings.from_env()
        runtime = AppRuntime(settings)
        _wait_for_rpc(runtime)
    except (ConfigurationError, RpcError) as exc:
        print(f"Bitcoin Peer Map: startup failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    uvicorn.run(
        create_app(settings, runtime),
        host=settings.listen_address,
        port=settings.listen_port,
        log_level="info",
        proxy_headers=True,
    )


if __name__ == "__main__":
    main()
