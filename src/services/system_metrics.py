"""Container CPU, memory, disk, and network metrics."""

from __future__ import annotations

import math
import os
import threading
import time
from pathlib import Path
from typing import Any


class DualEma:
    def __init__(self, fast_seconds: float, slow_seconds: float):
        self.fast_seconds = fast_seconds
        self.slow_seconds = slow_seconds
        self.fast: float | None = None
        self.slow: float | None = None

    def update(self, value: float, elapsed: float) -> float:
        if self.fast is None or self.slow is None:
            self.fast = self.slow = value
            return value
        fast_alpha = 1 - math.exp(-elapsed / self.fast_seconds)
        slow_alpha = 1 - math.exp(-elapsed / self.slow_seconds)
        self.fast += fast_alpha * (value - self.fast)
        self.slow += slow_alpha * (value - self.slow)
        deviation = abs(value - self.slow) / max(self.slow, 1.0)
        blend = min(deviation * 2, 1.0)
        return self.slow + blend * (self.fast - self.slow)


class SystemMetrics:
    def __init__(self, stop_event: threading.Event):
        self._stop_event = stop_event
        self._lock = threading.Lock()
        self._latest: dict[str, Any] | None = None
        self._previous_network: tuple[int, int, float] | None = None
        self._previous_cpu: tuple[int, int, list[int]] | None = None
        self._network_rx_ema = DualEma(0.8, 2.5)
        self._network_tx_ema = DualEma(0.8, 2.5)
        self._cpu_ema = DualEma(0.6, 1.5)
        self._memory_ema = DualEma(0.5, 2.0)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._sample_loop, daemon=True, name="system-metrics"
        )
        self._thread.start()

    def latest(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._latest) if self._latest else None

    def stop(self) -> None:
        if self._thread:
            self._thread.join(timeout=2)

    @staticmethod
    def _network_totals() -> tuple[int, int]:
        received = sent = 0
        for line in Path("/proc/net/dev").read_text().splitlines():
            if ":" not in line:
                continue
            interface, data = line.split(":", 1)
            if interface.strip() == "lo":
                continue
            fields = data.split()
            if len(fields) >= 9:
                received += int(fields[0])
                sent += int(fields[8])
        return received, sent

    @staticmethod
    def _cpu_values() -> tuple[int, int, list[int]]:
        fields = Path("/proc/stat").read_text().splitlines()[0].split()
        values = [int(value) for value in fields[1:9]]
        return values[3] + values[4], sum(values), values

    @staticmethod
    def _memory_values() -> tuple[float, int, int]:
        values: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value, *_ = line.split()
            if key in {"MemTotal:", "MemAvailable:"}:
                values[key] = int(value)
        total = values["MemTotal:"]
        available = values["MemAvailable:"]
        return (1 - available / total) * 100, round((total - available) / 1024), round(total / 1024)

    def _sample_loop(self) -> None:
        while not self._stop_event.is_set():
            self._sample()
            self._stop_event.wait(0.2)

    def _sample(self) -> None:
        now = time.time()
        rx_rate = tx_rate = 0.0
        cpu_percent: float | None = None
        memory_percent: float | None = None
        used_memory = total_memory = None
        try:
            received, sent = self._network_totals()
            if self._previous_network:
                previous_rx, previous_tx, previous_at = self._previous_network
                elapsed = now - previous_at
                if elapsed > 0:
                    rx_rate = max(0, (received - previous_rx) / elapsed)
                    tx_rate = max(0, (sent - previous_tx) / elapsed)
            self._previous_network = received, sent, now
        except (OSError, ValueError):
            pass

        try:
            idle, total, values = self._cpu_values()
            if self._previous_cpu:
                previous_idle, previous_total, _ = self._previous_cpu
                delta_total = total - previous_total
                if delta_total > 0:
                    cpu_percent = 100 * (1 - (idle - previous_idle) / delta_total)
            self._previous_cpu = idle, total, values
        except (OSError, ValueError, IndexError):
            pass

        try:
            memory_percent, used_memory, total_memory = self._memory_values()
        except (OSError, ValueError, KeyError):
            pass

        elapsed = 0.2
        snapshot = {
            "rx_bps": round(self._network_rx_ema.update(rx_rate, elapsed), 1),
            "tx_bps": round(self._network_tx_ema.update(tx_rate, elapsed), 1),
            "cpu_pct": round(self._cpu_ema.update(cpu_percent, elapsed), 1)
            if cpu_percent is not None
            else None,
            "mem_pct": round(self._memory_ema.update(memory_percent, elapsed), 1)
            if memory_percent is not None
            else None,
            "mem_used_mb": used_memory,
            "mem_total_mb": total_memory,
            "ts": now,
        }
        with self._lock:
            self._latest = snapshot

    def summary(self) -> dict[str, Any]:
        snapshot = self.latest() or {}
        summary = {
            "cpu_pct": snapshot.get("cpu_pct"),
            "mem_pct": snapshot.get("mem_pct"),
            "cpu_breakdown": None,
            "mem_used_mb": snapshot.get("mem_used_mb"),
            "mem_total_mb": snapshot.get("mem_total_mb"),
        }
        try:
            uptime = float(Path("/proc/uptime").read_text().split()[0])
            days, remainder = divmod(int(uptime), 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes = remainder // 60
            summary["uptime"] = (
                f"{days}d {hours}h {minutes}m"
                if days
                else f"{hours}h {minutes}m"
                if hours
                else f"{minutes}m"
            )
            summary["uptime_sec"] = int(uptime)
        except (OSError, ValueError, IndexError):
            pass
        try:
            load = Path("/proc/loadavg").read_text().split()
            summary.update(load_1=float(load[0]), load_5=float(load[1]), load_15=float(load[2]))
        except (OSError, ValueError, IndexError):
            pass
        try:
            disk = os.statvfs("/")
            total = disk.f_blocks * disk.f_frsize
            free = disk.f_bavail * disk.f_frsize
            used = total - disk.f_bfree * disk.f_frsize
            summary.update(
                disk_total_gb=round(total / 1e9, 1),
                disk_used_gb=round(used / 1e9, 1),
                disk_free_gb=round(free / 1e9, 1),
                disk_pct=round(used / total * 100, 1) if total else 0,
            )
        except OSError:
            pass
        return summary
