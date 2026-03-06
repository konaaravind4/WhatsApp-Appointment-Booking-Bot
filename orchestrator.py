"""
A2A Orchestrator — coordinates Intent, Availability, and Confirmation agents.
Manages per-user conversation state stored in Redis.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import redis

from agents.intent_agent import BookingIntent, IntentAgent
from agents.availability_agent import AvailabilityAgent
from agents.confirmation_agent import ConfirmationAgent, Booking

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")


class BookingOrchestrator:
    """
    Multi-agent orchestrator that drives the full booking conversation flow:
    1. Extract intent (IntentAgent)
    2. Check availability (AvailabilityAgent)
    3. Confirm booking (ConfirmationAgent)
    """

    SESSION_TTL = 60 * 30  # 30-minute conversation window

    def __init__(self):
        self.intent_agent = IntentAgent(api_key=GEMINI_API_KEY)
        self.availability_agent = AvailabilityAgent(redis_url=REDIS_URL)
        self.confirmation_agent = ConfirmationAgent(redis_url=REDIS_URL)
        self.redis = redis.from_url(REDIS_URL, decode_responses=True)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def process_message(self, phone: str, message: str) -> str:
        """
        Process an inbound WhatsApp message and return the reply text.

        Flow:
          CANCEL <id>   → cancel booking
          otherwise     → extract intent → check availability → confirm
        """
        message = message.strip()

        # ── Cancellation shortcut ──────────────────────────────────────
        if message.upper().startswith("CANCEL"):
            parts = message.split()
            booking_id = parts[-1].lstrip("#") if len(parts) > 1 else ""
            if booking_id and self.confirmation_agent.cancel_booking(booking_id):
                return f"✅ Booking #{booking_id} has been cancelled. Hope to see you again!"
            return "❌ Could not find that booking. Please check your booking ID."

        # ── Load conversation history ──────────────────────────────────
        context = self._load_context(phone)

        # ── Extract intent ────────────────────────────────────────────
        intent = self.intent_agent.extract(message, context)
        self._save_context(phone, message, role="user")

        # ── Determine missing fields ──────────────────────────────────
        missing = self._missing_fields(intent)
        if missing:
            reply = self.intent_agent.generate_response(intent, missing)
            self._save_context(phone, reply, role="assistant")
            return reply

        # ── Check availability ────────────────────────────────────────
        if not self.availability_agent.check_slot(intent.date, intent.time, intent.service):
            alternatives = self.availability_agent.suggest_alternatives(intent.date, intent.service)
            if alternatives:
                alt_text = "\n".join(f"  • {a}" for a in alternatives)
                reply = (
                    f"😞 Sorry, {intent.time} on {intent.date} is not available.\n\n"
                    f"Here are the next available slots:\n{alt_text}\n\n"
                    f"Which works for you?"
                )
            else:
                reply = "😞 No slots available in the next 3 days. Please try another week."
            self._save_context(phone, reply, role="assistant")
            return reply

        # ── Reserve & confirm ─────────────────────────────────────────
        reserved = self.availability_agent.reserve_slot(
            intent.date, intent.time, intent.service, phone
        )
        if not reserved:
            # Race condition — another booking just took it
            reply = "⚡ That slot was just taken! Let me show you alternatives..."
            alternatives = self.availability_agent.suggest_alternatives(intent.date, intent.service)
            if alternatives:
                reply += "\n" + "\n".join(f"  • {a}" for a in alternatives)
            self._save_context(phone, reply, role="assistant")
            return reply

        booking = self.confirmation_agent.create_booking(
            customer_name=intent.customer_name or "Guest",
            phone=phone,
            service=intent.service,
            date=intent.date,
            time=intent.time,
        )
        reply = self.confirmation_agent.confirmation_message(booking)
        self._clear_context(phone)
        self._save_context(phone, reply, role="assistant")
        return reply

    # ------------------------------------------------------------------
    # Session helpers
    # ------------------------------------------------------------------

    def _load_context(self, phone: str) -> list[dict]:
        key = f"session:{phone}"
        raw = self.redis.lrange(key, 0, -1)
        context = []
        for item in raw:
            role, _, content = item.partition("|")
            context.append({"role": role, "content": content})
        return context

    def _save_context(self, phone: str, message: str, role: str) -> None:
        key = f"session:{phone}"
        self.redis.rpush(key, f"{role}|{message}")
        self.redis.expire(key, self.SESSION_TTL)

    def _clear_context(self, phone: str) -> None:
        self.redis.delete(f"session:{phone}")

    @staticmethod
    def _missing_fields(intent: BookingIntent) -> list[str]:
        missing = []
        if not intent.service:
            missing.append("service")
        if not intent.date:
            missing.append("date")
        if not intent.time:
            missing.append("time")
        if not intent.customer_name:
            missing.append("customer_name")
        return missing
