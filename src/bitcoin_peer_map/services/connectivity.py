"""External network health and BTC price state."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import requests


class ConnectivityService:
    def __init__(self, stop_event: threading.Event):
        self._stop_event = stop_event
        self._lock = threading.RLock()
        self._checker_lock = threading.Lock()
        self._checker: threading.Thread | None = None
        self._on_change: Callable[[str, dict[str, Any]], None] | None = None
        self.internet_state = "green"
        self.consecutive_successes = 0
        self.failure_started_at: float | None = None
        self.api_consecutive_failures = 0
        self.api_prompt_count = 0
        self.api_prompt_at = 0.0
        self.geoip_api_disabled = False
        self.last_known_price: str | None = None
        self.last_price_currency = "USD"
        self.last_price_error: str | None = None

    def set_change_callback(self, callback: Callable[[str, dict[str, Any]], None]) -> None:
        self._on_change = callback

    def _set_state(self, state: str) -> None:
        with self._lock:
            if self.internet_state == state:
                return
            previous = self.internet_state
            self.internet_state = state
        print(f"Internet state changed from {previous} to {state}")
        if self._on_change:
            self._on_change(
                "connectivity",
                {
                    "internet_state": state,
                    "api_available": self.api_consecutive_failures < 5,
                },
            )

    def network_failure(self, *, geoip_api: bool = False) -> None:
        with self._lock:
            self.consecutive_successes = 0
            if self.internet_state == "green":
                self.failure_started_at = time.time()
            if geoip_api:
                self.api_consecutive_failures += 1
        self._set_state("yellow")
        self._ensure_checker()

    def network_success(self, *, geoip_api: bool = False) -> None:
        with self._lock:
            if geoip_api:
                self.api_consecutive_failures = 0
            if self.internet_state == "green":
                return
            self.consecutive_successes += 1
            if self.consecutive_successes < 4:
                return
            self.consecutive_successes = 0
            self.failure_started_at = None
            self.api_prompt_count = 0
            self.api_prompt_at = 0
        self._set_state("green")

    def _ensure_checker(self) -> None:
        with self._checker_lock:
            if self._checker and self._checker.is_alive():
                return
            self._checker = threading.Thread(
                target=self._check_loop,
                daemon=True,
                name="connectivity-monitor",
            )
            self._checker.start()

    def _check_loop(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                if self.internet_state == "green":
                    return
            try:
                response = requests.head("https://www.google.com", timeout=2)
                available = response.status_code < 500
            except requests.RequestException:
                available = False
            if available:
                self.network_success()
            else:
                with self._lock:
                    self.consecutive_successes = 0
                    failure_age = (
                        time.time() - self.failure_started_at if self.failure_started_at else 0
                    )
                if failure_age >= 10:
                    self._set_state("red")
            self._stop_event.wait(2)

    def fetch_price(self, currency: str) -> float | None:
        currency = currency.upper()
        with self._lock:
            if self.internet_state == "red":
                return self._cached_price(currency)
        try:
            response = requests.get(
                f"https://api.coinbase.com/v2/prices/BTC-{currency}/spot",
                timeout=5,
            )
            response.raise_for_status()
            amount = response.json().get("data", {}).get("amount")
            if not amount:
                raise ValueError("Coinbase response did not include a price")
            with self._lock:
                self.last_known_price = str(amount)
                self.last_price_currency = currency
                self.last_price_error = None
            self.network_success()
            return float(amount)
        except (requests.RequestException, TypeError, ValueError) as exc:
            with self._lock:
                self.last_price_error = f"Coinbase API error: {exc}"
            self.network_failure()
            return self._cached_price(currency)

    def _cached_price(self, currency: str) -> float | None:
        with self._lock:
            if self.last_known_price and self.last_price_currency == currency:
                return float(self.last_known_price)
        return None

    def toggle_geoip_api(self) -> bool:
        with self._lock:
            self.geoip_api_disabled = not self.geoip_api_disabled
            if self.geoip_api_disabled:
                self.api_prompt_count = 0
                self.api_prompt_at = 0
            return self.geoip_api_disabled

    def acknowledge_prompt(self) -> None:
        with self._lock:
            self.api_prompt_at = time.time()
            self.api_prompt_count += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            should_prompt = False
            if (
                self.api_consecutive_failures >= 5
                and self.internet_state == "green"
                and not self.geoip_api_disabled
            ):
                elapsed = time.time() - self.api_prompt_at if self.api_prompt_at else float("inf")
                should_prompt = (
                    self.api_prompt_count == 0
                    or (self.api_prompt_count <= 3 and elapsed >= self.api_prompt_count * 60)
                    or (self.api_prompt_count > 3 and elapsed >= 300)
                )
            return {
                "internet_state": self.internet_state,
                "api_available": self.api_consecutive_failures < 5,
                "api_consecutive_failures": self.api_consecutive_failures,
                "last_price_error": self.last_price_error,
                "last_known_price": self.last_known_price,
                "last_price_currency": self.last_price_currency,
                "geo_db_only_mode": self.geoip_api_disabled,
                "api_down_prompt": should_prompt,
            }
