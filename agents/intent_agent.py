"""
Intent extraction agent using Google Gemini.
Extracts service, date, time, and customer name from natural language messages.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

import google.generativeai as genai

logger = logging.getLogger(__name__)


@dataclass
class BookingIntent:
    service: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    customer_name: Optional[str] = None
    confirmed: bool = False
    raw_message: str = ""


class IntentAgent:
    """Extracts appointment booking intent using Gemini 2.0 Flash."""

    SYSTEM_PROMPT = """You are an appointment booking assistant for a salon.
Extract booking details from the customer's message.
Return a JSON object with these fields:
- service: one of [haircut, facial, manicure, pedicure, hair_color, massage, other]
- date: ISO format YYYY-MM-DD or null
- time: 24h format HH:MM or null
- customer_name: string or null
- confirmed: boolean (true if customer explicitly confirms a booking)

Be liberal in interpretation. "tmr" means tomorrow, "2pm" means 14:00.
Return ONLY valid JSON, no explanation."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash-lite"):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(
            model,
            system_instruction=self.SYSTEM_PROMPT,
        )

    def extract(self, message: str, context: list[dict] | None = None) -> BookingIntent:
        """Extract booking intent from a customer WhatsApp message."""
        try:
            prompt = f"Customer message: {message}"
            if context:
                ctx_text = "\n".join(
                    f"{m['role']}: {m['content']}" for m in context[-4:]
                )
                prompt = f"Previous conversation:\n{ctx_text}\n\nCurrent message: {message}"

            response = self.model.generate_content(prompt)
            raw = response.text.strip()

            # Strip markdown fences if present
            raw = re.sub(r"^```json\n?|^```\n?|\n?```$", "", raw, flags=re.MULTILINE)
            data = json.loads(raw)

            return BookingIntent(
                service=data.get("service"),
                date=data.get("date"),
                time=data.get("time"),
                customer_name=data.get("customer_name"),
                confirmed=bool(data.get("confirmed", False)),
                raw_message=message,
            )
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Intent extraction failed: %s", e)
            return BookingIntent(raw_message=message)

    def generate_response(self, intent: BookingIntent, missing_fields: list[str]) -> str:
        """Generate a natural language follow-up response for missing booking info."""
        prompts = {
            "service": "What service would you like to book? (e.g. haircut, facial, massage)",
            "date": "What date works for you?",
            "time": "What time would you prefer?",
            "customer_name": "May I have your name for the booking?",
        }
        if missing_fields:
            return prompts.get(missing_fields[0], "Could you provide more details?")
        return "Great! Let me check availability for you."
