"""
app/agents/availability_agent.py — Real-time slot availability checker.

In production: queries Apache Flink REST API for live calendar streams.
In demo/test mode: uses a simple in-memory schedule.
"""

import logging
import os
import random
from typing import Optional, Tuple

import httpx

from app.models import ServiceType

logger = logging.getLogger(__name__)

STYLISTS = ["Rahul", "Priya", "Vikram", "Anita", "Suresh"]
SERVICE_DURATIONS = {
    ServiceType.HAIRCUT: 30,
    ServiceType.BEARD: 20,
    ServiceType.COLOR: 90,
    ServiceType.FACIAL: 60,
    ServiceType.MANICURE: 45,
    ServiceType.PEDICURE: 45,
    ServiceType.OTHER: 30,
}


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
