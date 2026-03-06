"""
Confirmation agent — finalises bookings and sends WhatsApp reply messages.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import redis

logger = logging.getLogger(__name__)


@dataclass
class Booking:
    booking_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8].upper())
    customer_name: str = ""
    phone: str = ""
    service: str = ""
    date: str = ""
    time: str = ""
    status: str = "pending"  # pending | confirmed | cancelled
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class ConfirmationAgent:
    """Handles booking confirmation, storage, and reminder scheduling."""

    BOOKING_TTL = 60 * 60 * 48  # 48 hours

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis = redis.from_url(redis_url, decode_responses=True)

    # ------------------------------------------------------------------
    # Core flow
    # ------------------------------------------------------------------

    def create_booking(
        self,
        customer_name: str,
        phone: str,
        service: str,
        date: str,
        time: str,
    ) -> Booking:
        booking = Booking(
            customer_name=customer_name,
            phone=phone,
            service=service,
            date=date,
            time=time,
            status="confirmed",
        )
        self._store(booking)
        self._schedule_reminder(booking)
        return booking

    def cancel_booking(self, booking_id: str) -> bool:
        key = f"booking:{booking_id}"
        if not self.redis.exists(key):
            return False
        self.redis.hset(key, "status", "cancelled")
        return True

    def get_booking(self, booking_id: str) -> Optional[Booking]:
        key = f"booking:{booking_id}"
        data = self.redis.hgetall(key)
        if not data:
            return None
        return Booking(**data)

    # ------------------------------------------------------------------
    # Message generation
    # ------------------------------------------------------------------

    @staticmethod
    def confirmation_message(booking: Booking) -> str:
        return (
            f"✅ *Booking Confirmed!*\n\n"
            f"📋 *Booking ID:* #{booking.booking_id}\n"
            f"👤 *Name:* {booking.customer_name}\n"
            f"💇 *Service:* {booking.service.replace('_', ' ').title()}\n"
            f"📅 *Date:* {booking.date}\n"
            f"🕐 *Time:* {booking.time}\n\n"
            f"We'll send you a reminder 1 hour before your appointment.\n"
            f"To cancel, reply: CANCEL #{booking.booking_id}"
        )

    @staticmethod
    def reminder_message(booking: Booking) -> str:
        return (
            f"⏰ *Appointment Reminder*\n\n"
            f"Your {booking.service.replace('_', ' ').title()} is in *1 hour*!\n"
            f"📅 {booking.date} at {booking.time}\n\n"
            f"See you soon! 💇"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _store(self, booking: Booking) -> None:
        key = f"booking:{booking.booking_id}"
        self.redis.hset(key, mapping={
            "booking_id": booking.booking_id,
            "customer_name": booking.customer_name,
            "phone": booking.phone,
            "service": booking.service,
            "date": booking.date,
            "time": booking.time,
            "status": booking.status,
            "created_at": booking.created_at,
        })
        self.redis.expire(key, self.BOOKING_TTL)

    def _schedule_reminder(self, booking: Booking) -> None:
        """Store a reminder task key so a scheduler can pick it up."""
        try:
            appt_dt = datetime.strptime(f"{booking.date} {booking.time}", "%Y-%m-%d %H:%M")
            reminder_dt = appt_dt - timedelta(hours=1)
            reminder_ts = int(reminder_dt.timestamp())
            self.redis.zadd(
                "reminders",
                {booking.booking_id: reminder_ts},
            )
        except ValueError as e:
            logger.warning("Could not schedule reminder: %s", e)
