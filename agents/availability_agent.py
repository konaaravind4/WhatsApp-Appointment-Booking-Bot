"""
Availability agent — checks free slots via Redis and simulates Flink stream.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import redis

logger = logging.getLogger(__name__)

SLOT_INTERVAL_MINUTES = 30
BUSINESS_HOURS = (9, 20)  # 9 AM – 8 PM


class AvailabilityAgent:
    """Manages appointment slots using Redis as the time-series slot store."""

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self._seed_default_slots()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def check_slot(self, date: str, time: str, service: str) -> bool:
        """Return True if the requested slot is available."""
        key = self._slot_key(date, time, service)
        status = self.redis.get(key)
        return status != "booked"

    def reserve_slot(self, date: str, time: str, service: str, booking_id: str) -> bool:
        """Atomically reserve a slot. Returns True on success."""
        key = self._slot_key(date, time, service)
        # SET NX with 24h TTL
        result = self.redis.set(key, f"booked:{booking_id}", nx=True, ex=86400)
        return bool(result)

    def release_slot(self, date: str, time: str, service: str) -> None:
        """Release a previously reserved slot."""
        key = self._slot_key(date, time, service)
        self.redis.delete(key)

    def get_available_slots(self, date: str, service: str) -> list[str]:
        """Return available time slots for a given date and service."""
        slots = []
        start = datetime.strptime(f"{date} {BUSINESS_HOURS[0]:02d}:00", "%Y-%m-%d %H:%M")
        end = datetime.strptime(f"{date} {BUSINESS_HOURS[1]:02d}:00", "%Y-%m-%d %H:%M")

        current = start
        while current < end:
            t = current.strftime("%H:%M")
            if self.check_slot(date, t, service):
                slots.append(t)
            current += timedelta(minutes=SLOT_INTERVAL_MINUTES)
        return slots

    def suggest_alternatives(self, date: str, service: str, n: int = 3) -> list[str]:
        """Suggest up to n available slots on the given or next available day."""
        for offset in range(3):
            d = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=offset)).strftime("%Y-%m-%d")
            slots = self.get_available_slots(d, service)
            if slots:
                return [f"{d} {s}" for s in slots[:n]]
        return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _slot_key(date: str, time: str, service: str) -> str:
        return f"slot:{date}:{time}:{service}"

    def _seed_default_slots(self) -> None:
        """Pre-populate tomorrow's slots as available (demo only)."""
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        for service in ["haircut", "facial", "manicure", "pedicure", "hair_color", "massage"]:
            slots = self.get_available_slots(tomorrow, service)
            # Just touch existing keys so they exist — don't overwrite booked ones
            _ = slots  # no-op; keys are absent = available
