"""In-memory daily check counter.

No DB in this MVP, so this resets on restart — acceptable for a demo, but
worth knowing if you're staring at a "checks today" number that looks low
right after a redeploy. Not persisted, not shared across processes.
"""

from __future__ import annotations

from datetime import datetime, timezone


class DailyCounter:
    def __init__(self) -> None:
        self._day: str = self._today()
        self._count: int = 0

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def increment(self) -> None:
        today = self._today()
        if today != self._day:
            self._day = today
            self._count = 0
        self._count += 1

    @property
    def count(self) -> int:
        if self._today() != self._day:
            return 0
        return self._count
