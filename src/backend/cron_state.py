"""
Shared cron state — accessed by both the background task and the settings router.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


_MAX_LOGS = 200   # keep last 200 entries in memory
_CRON_LOG = logging.getLogger("bsm.cron")


@dataclass
class LogEntry:
    ts: str       # ISO timestamp
    level: str    # INFO / WARN / ERROR
    msg: str


@dataclass
class CronState:
    is_running: bool = False
    last_scan_at: Optional[str] = None
    last_scan_count: int = 0
    last_saved: int = 0
    last_inserted: int = 0
    today_inserted: int = 0
    last_error: Optional[str] = None
    next_scan_in: Optional[float] = None
    total_scans: int = 0
    today_scans: int = 0
    today_key: Optional[str] = None
    last_activity_at: Optional[str] = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    _logs: deque = field(default_factory=lambda: deque(maxlen=_MAX_LOGS), repr=False, compare=False)
    _last_activity_monotonic: float = field(default=0.0, repr=False, compare=False)
    _blocked_total_seconds: float = field(default=0.0, repr=False, compare=False)
    _blocked_max_seconds: float = field(default=0.0, repr=False, compare=False)
    _blocked_count: int = field(default=0, repr=False, compare=False)

    # ------------------------------------------------------------------ #
    def _get_tz(self) -> "zoneinfo.ZoneInfo":
        import zoneinfo
        try:
            from bsm.settings import load_runtime_config
            tz_str = load_runtime_config().get("timezone", "Asia/Shanghai")
            return zoneinfo.ZoneInfo(tz_str)
        except Exception:
            return zoneinfo.ZoneInfo("Asia/Shanghai")

    def log(self, level: str, msg: str) -> None:
        tz = self._get_tz()
        entry = LogEntry(ts=datetime.now(tz).strftime("%H:%M:%S"), level=level, msg=msg)
        with self._lock:
            self._logs.append(entry)
            self.last_activity_at = datetime.now(tz).strftime("%Y-%m-%dT%H:%M:%S%z")
            self._last_activity_monotonic = time.monotonic()
        if level == "ERROR":
            _CRON_LOG.error(msg)
        elif level == "WARN":
            _CRON_LOG.warning(msg)
        else:
            _CRON_LOG.info(msg)

    def info(self, msg: str) -> None:
        self.log("INFO", msg)

    def warn(self, msg: str) -> None:
        self.log("WARN", msg)

    def error(self, msg: str) -> None:
        self.log("ERROR", msg)

    def get_logs(self, n: int = 20) -> List[dict]:
        with self._lock:
            entries = list(self._logs)[-n:]
        return [{"ts": e.ts, "level": e.level, "msg": e.msg} for e in entries]

    # ------------------------------------------------------------------ #
    def update_scan(self, count: int, saved: int, inserted: int, error: Optional[str] = None) -> None:
        with self._lock:
            tz = self._get_tz()
            now = datetime.now(tz)
            day_key = now.strftime("%Y-%m-%d")
            if self.today_key != day_key:
                self.today_key = day_key
                self.today_scans = 0
                self.today_inserted = 0
            self.last_scan_at = now.strftime("%Y-%m-%dT%H:%M:%S%z")
            self.last_scan_count = count
            self.last_saved = saved
            self.last_inserted = inserted
            self.today_inserted += inserted
            self.last_error = error
            self.total_scans += 1
            self.today_scans += 1
            self.last_activity_at = now.strftime("%Y-%m-%dT%H:%M:%S%z")
            self._last_activity_monotonic = time.monotonic()
            
        # Save outside lock to avoid potential deadlocks if set_metadata takes time.
        # DB failures here should not crash cron loop.
        try:
            self.save()
        except Exception as exc:
            _CRON_LOG.warning("Failed to persist cron state metadata: %s", exc)

    def set_next_scan_in(self, seconds: Optional[float]) -> None:
        with self._lock:
            self.next_scan_in = seconds

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "is_running": self.is_running,
                "last_scan_at": self.last_scan_at,
                "last_activity_at": self.last_activity_at,
                "last_scan_count": self.last_scan_count,
                "last_saved": self.last_saved,
                "last_inserted": self.last_inserted,
                "today_inserted": self.today_inserted,
                "last_error": self.last_error,
                "next_scan_in": self.next_scan_in,
                "total_scans": self.total_scans,
                "today_scans": self.today_scans,
            }

    def seconds_since_activity(self) -> Optional[float]:
        with self._lock:
            last = self._last_activity_monotonic
        if last <= 0:
            return None
        return max(0.0, time.monotonic() - last)

    def record_blocked_duration(self, seconds: float) -> None:
        blocked = max(0.0, float(seconds or 0.0))
        if blocked <= 0:
            return
        with self._lock:
            self._blocked_total_seconds += blocked
            self._blocked_count += 1
            if blocked > self._blocked_max_seconds:
                self._blocked_max_seconds = blocked

    def consume_blocked_stats(self) -> dict:
        with self._lock:
            payload = {
                "blocked_total_seconds": float(self._blocked_total_seconds),
                "blocked_max_seconds": float(self._blocked_max_seconds),
                "blocked_count": int(self._blocked_count),
            }
            self._blocked_total_seconds = 0.0
            self._blocked_max_seconds = 0.0
            self._blocked_count = 0
        return payload

    def load(self) -> None:
        """Load persistent stats from database."""
        from bsm.db import get_metadata
        with self._lock:
            self.total_scans = int(get_metadata("cron_total_scans", "0"))
            self.today_scans = int(get_metadata("cron_today_scans", "0"))
            self.today_inserted = int(get_metadata("cron_today_inserted", "0"))
            self.today_key = get_metadata("cron_today_key")
            self.last_scan_at = get_metadata("cron_last_scan_at")

    def save(self) -> None:
        """Save persistent stats to database."""
        from bsm.db import set_metadata
        with self._lock:
            set_metadata("cron_total_scans", str(self.total_scans))
            set_metadata("cron_today_scans", str(self.today_scans))
            set_metadata("cron_today_inserted", str(self.today_inserted))
            set_metadata("cron_today_key", self.today_key)
            if self.last_scan_at:
                set_metadata("cron_last_scan_at", self.last_scan_at)


# Singleton shared across the process
cron_state = CronState()
