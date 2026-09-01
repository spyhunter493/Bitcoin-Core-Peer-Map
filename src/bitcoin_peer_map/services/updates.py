"""Repository version checks."""

from __future__ import annotations

import threading
import time
from typing import Any

import requests


def is_newer_version(current: str, candidate: str) -> bool:
    try:
        current_parts = [int(part) for part in current.split(".")]
        candidate_parts = [int(part) for part in candidate.split(".")]
    except ValueError:
        return False
    length = max(len(current_parts), len(candidate_parts))
    current_parts.extend([0] * (length - len(current_parts)))
    candidate_parts.extend([0] * (length - len(candidate_parts)))
    return candidate_parts > current_parts


class UpdateService:
    def __init__(self, repository: str, version: str):
        self.version = version
        self.version_url = f"https://raw.githubusercontent.com/{repository}/main/VERSION"
        self.changelog_url = f"https://raw.githubusercontent.com/{repository}/main/CHANGELOG.md"
        self._lock = threading.Lock()
        self._checked_at = 0.0
        self._latest: str | None = None
        self._changes: str | None = None

    def check(self) -> dict[str, Any]:
        with self._lock:
            if time.time() - self._checked_at < 1800 and self._latest is not None:
                return self._result()
            latest = None
            changes = None
            try:
                response = requests.get(f"{self.version_url}?cb={int(time.time())}", timeout=5)
                if response.status_code == 200:
                    latest = response.text.strip()
            except requests.RequestException:
                pass
            if latest and is_newer_version(self.version, latest):
                try:
                    response = requests.get(self.changelog_url, timeout=5)
                    if response.status_code == 200:
                        changes = response.text.strip()
                except requests.RequestException:
                    pass
            self._latest = latest or self.version
            self._changes = changes
            self._checked_at = time.time()
            return self._result()

    def _result(self) -> dict[str, Any]:
        latest = self._latest or self.version
        return {
            "current": self.version,
            "latest": latest,
            "available": is_newer_version(self.version, latest),
            "changes": self._changes or "",
        }
