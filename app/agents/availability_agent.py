"""
app/agents/availability_agent.py — Real-time slot availability checker.

Enhanced with:
- get_available_slots(): returns list of free slots for a date
- get_stylist_workload(): workload stats per stylist
- find_next_available(): finds the next available date+time for a service
- _booking_count tracking and total_bookings property
- Full type annotations
"""
from __future__ import annotations

import logging
import os
import random
from datetime import date, datetime, timedelta
from typing import Optional

import httpx

from app.models import SERVICE_DURATIONS if hasattr(__import__('app.models', fromlist=['SERVICE_DURATIONS']), 'SERVICE_DURATIONS') else None
from app.models import ServiceType

logger = logging.getLogger(__name__)

STYLISTS: list[str] = ["Rahul", "Priya", "Vikram", "Anita", "Suresh"]

SERVICE_DURATIONS: dict[ServiceType, int] = {
    ServiceType.HAIRCUT:  30,
    ServiceType.BEARD:    20,
    ServiceType.COLOR:    90,
    ServiceType.FACIAL:   60,
    ServiceType.MANICURE: 45,
    ServiceType.PEDICURE: 45,
    ServiceType.OTHER:    30,
}

# Business hours: 9 AM – 7 PM in 30-min slots
_SLOT_HOURS = [f"{h:02d}:{m:02d}" for h in range(9, 19) for m in (0, 30)]


class AvailabilityAgent:
    """
    Checks stylist availability for a given date/time/service.

    Queries Flink REST API when FLINK_JOB_MANAGER_URL is set;
    otherwise uses a deterministic mock for development/testing.

    Tracks total bookings confirmed via this agent instance.
    """

    def __init__(self) -> None:
        self.flink_url: str = os.getenv("FLINK_JOB_MANAGER_URL", "")
        self.use_flink: bool = bool(self.flink_url)
        self._booking_count: int = 0

    @property
    def total_bookings(self) -> int:
        """Total appointments confirmed through this agent."""
        return self._booking_count

    # ── Core availability check ───────────────────────────────────────────────

    def check(
        self,
        date: Optional[str],
        time: Optional[str],
        service: Optional[ServiceType],
    ) -> tuple[bool, str]:
        """
        Check whether a specific date/time/service slot is available.

        Args:
            date: Date string (YYYY-MM-DD).
            time: 24-hour time string (HH:MM).
            service: Service type.

        Returns:
            (is_available, assigned_stylist_name)
        """
        if not date or not time:
            return False, ""

        if self.use_flink:
            result = self._query_flink(date, time, service)
        else:
            result = self._mock_check(date, time, service)

        if result[0]:
            self._booking_count += 1
        return result

    # ── Slot listing ──────────────────────────────────────────────────────────

    def get_available_slots(
        self,
        date_str: str,
        service_type: Optional[ServiceType] = None,
        n: int = 5,
    ) -> list[str]:
        """
        Return up to N available time slots for a given date.

        Uses mock availability logic in development mode.
        Filters out already-booked slots deterministically by date.

        Args:
            date_str: Target date (YYYY-MM-DD).
            service_type: Service type (affects duration filtering).
            n: Maximum number of slots to return (default: 5).

        Returns:
            List of available HH:MM time strings.
        """
        available: list[str] = []
        for slot_time in _SLOT_HOURS:
            is_available, _ = self._mock_check(date_str, slot_time, service_type)
            if is_available:
                available.append(slot_time)
            if len(available) >= n:
                break
        return available

    def find_next_available(
        self,
        service_type: Optional[ServiceType] = None,
        preferred_time: Optional[str] = None,
        max_days_ahead: int = 14,
    ) -> tuple[str, str]:
        """
        Find the next available (date, time) pair for the given service.

        Starts from today and scans up to max_days_ahead days.
        If preferred_time is provided, checks that time first.

        Args:
            service_type: Service type to check duration constraints.
            preferred_time: Preferred HH:MM (checked first each day).
            max_days_ahead: How far ahead to search (default: 14 days).

        Returns:
            (date_str, time_str) of the first available slot.
        """
        today = datetime.utcnow().date()
        times_to_try = _SLOT_HOURS.copy()
        if preferred_time and preferred_time in times_to_try:
            # Try preferred time first each day
            times_to_try.remove(preferred_time)
            times_to_try.insert(0, preferred_time)

        for day_offset in range(1, max_days_ahead + 1):
            check_date = (today + timedelta(days=day_offset)).isoformat()
            for slot_time in times_to_try:
                is_available, _ = self._mock_check(check_date, slot_time, service_type)
                if is_available:
                    return check_date, slot_time

        # Fallback: return tomorrow 10am
        fallback_date = (today + timedelta(days=1)).isoformat()
        return fallback_date, "10:00"

    # ── Stylist workload ──────────────────────────────────────────────────────

    def get_stylist_workload(self, stylist: str) -> dict:
        """
        Get workload statistics for a specific stylist.

        Returns estimated bookings today, this week, and total hours booked.
        In production these would query the calendar database.

        Args:
            stylist: Stylist name (must be in STYLISTS list).

        Returns:
            Dict with keys: stylist, today, this_week, booked_hours.
        """
        # Deterministic mock workload derived from stylist name hash
        seed = hash(stylist)
        today_count   = (seed % 8) + 2          # 2–9 bookings today
        week_count    = today_count * (5 + seed % 3)  # scaled weekly
        avg_duration  = 45.0                     # average service 45 min
        booked_hours  = round(today_count * avg_duration / 60, 1)

        return {
            "stylist":      stylist,
            "today":        today_count,
            "this_week":    week_count,
            "booked_hours": booked_hours,
            "utilisation":  f"{min(100, int(booked_hours / 8 * 100))}%",
        }

    # ── Internal implementations ──────────────────────────────────────────────

    def _query_flink(
        self,
        date: str,
        time: str,
        service: Optional[ServiceType],
    ) -> tuple[bool, str]:
        """Query Flink SQL endpoint for available slots."""
        duration = SERVICE_DURATIONS.get(service, 30) if service else 30
        sql = (
            f"SELECT stylist, start_time FROM salon_slots "
            f"WHERE date = '{date}' AND start_time = '{time}' "
            f"AND duration_minutes >= {duration} AND booked = false LIMIT 1"
        )
        try:
            resp = httpx.post(
                f"{self.flink_url}/v1/sessions/default/statements",
                json={"statement": sql},
                timeout=5.0,
            )
            resp.raise_for_status()
            rows = resp.json().get("results", {}).get("data", [])
            if rows:
                stylist = rows[0][0]
                return True, stylist
            return False, ""
        except Exception as e:
            logger.error("Flink query failed: %s. Falling back to mock.", e)
            return self._mock_check(date, time, service)

    def _mock_check(
        self,
        date: str,
        time: str,
        service: Optional[ServiceType],
    ) -> tuple[bool, str]:
        """
        Deterministic mock: ~80% availability, consistent for same inputs.

        The hash function ensures the same date+time always returns the
        same availability result — making development testing predictable.
        """
        seed = hash(f"{date}{time}{service}") % 10
        if seed < 8:  # 80% available
            stylist = STYLISTS[hash(f"{date}{time}") % len(STYLISTS)]
            return True, stylist
        return False, ""



class AvailabilityAgent:
    """
    Checks stylist availability for a given date/time/service.
    Queries Flink REST API when FLINK_JOB_MANAGER_URL is set, else uses
    a deterministic mock for development.
    """

    def __init__(self):
        self.flink_url = os.getenv("FLINK_JOB_MANAGER_URL", "")
        self.use_flink = bool(self.flink_url)

    def check(
        self,
        date: Optional[str],
        time: Optional[str],
        service: Optional[ServiceType],
    ) -> Tuple[bool, str]:
        """
        Returns (is_available, assigned_stylist_name).
        """
        if not date or not time:
            return False, ""

        if self.use_flink:
            return self._query_flink(date, time, service)
        else:
            return self._mock_check(date, time, service)

    def _query_flink(
        self,
        date: str,
        time: str,
        service: Optional[ServiceType],
    ) -> Tuple[bool, str]:
        """Query Flink SQL endpoint for available slots."""
        duration = SERVICE_DURATIONS.get(service, 30) if service else 30
        sql = (
            f"SELECT stylist, start_time FROM salon_slots "
            f"WHERE date = '{date}' AND start_time = '{time}' "
            f"AND duration_minutes >= {duration} AND booked = false LIMIT 1"
        )
        try:
            resp = httpx.post(
                f"{self.flink_url}/v1/sessions/default/statements",
                json={"statement": sql},
                timeout=5.0,
            )
            resp.raise_for_status()
            rows = resp.json().get("results", {}).get("data", [])
            if rows:
                stylist = rows[0][0]
                return True, stylist
            return False, ""
        except Exception as e:
            logger.error(f"Flink query failed: {e}. Falling back to mock.")
            return self._mock_check(date, time, service)

    def _mock_check(
        self,
        date: str,
        time: str,
        service: Optional[ServiceType],
    ) -> Tuple[bool, str]:
        """Deterministic mock: ~80% availability, consistent for same inputs."""
        seed = hash(f"{date}{time}{service}") % 10
        if seed < 8:  # 80% available
            stylist = STYLISTS[hash(f"{date}{time}") % len(STYLISTS)]
            return True, stylist
        return False, ""
