"""
app/agents/intent_agent.py — Gemini-powered intent & slot extraction agent.
"""

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

import google.generativeai as genai

from app.models import ServiceType

logger = logging.getLogger(__name__)

SERVICE_KEYWORDS = {
    ServiceType.HAIRCUT: ["haircut", "hair cut", "cut", "trim", "hair"],
    ServiceType.BEARD: ["beard", "shave", "mustache"],
    ServiceType.COLOR: ["color", "colour", "dye", "highlight"],
    ServiceType.FACIAL: ["facial", "face", "skin"],
    ServiceType.MANICURE: ["manicure", "nails", "nail", "pedicure"],
    ServiceType.PEDICURE: ["pedicure", "feet"],
}


class IntentAgent:
    """Uses Gemini Flash to extract appointment slots from natural language."""

    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(
            "gemini-1.5-flash",
            generation_config=genai.GenerationConfig(
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )

    # ── Service Extraction ────────────────────────────────────────────────────

    def extract_service(self, text: str) -> Optional[ServiceType]:
        """Keyword matching (fast, no LLM call needed)."""
        text_lower = text.lower()
        for service, keywords in SERVICE_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return service
        return None

    # ── Date Extraction ───────────────────────────────────────────────────────

    def extract_date(self, text: str) -> Optional[str]:
        """Use Gemini to parse natural language dates. Returns YYYY-MM-DD."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        prompt = f"""Today is {today}.
The user said: "{text}"
Extract the appointment date the user wants. Return JSON: {{"date": "YYYY-MM-DD"}}
If you cannot determine a date, return {{"date": null}}."""
        try:
            resp = self.model.generate_content(prompt)
            data = json.loads(resp.text)
            return data.get("date")
        except Exception as e:
            logger.warning(f"Date extraction failed: {e}")
            return None

    # ── Time Extraction ───────────────────────────────────────────────────────

    def extract_time(self, text: str) -> Optional[str]:
        """Parse time from natural language. Returns HH:MM (24h)."""
        prompt = f"""The user wants to book at: "{text}"
Extract the time in 24-hour format. Return JSON: {{"time": "HH:MM"}}
If unclear, return {{"time": null}}."""
        try:
            resp = self.model.generate_content(prompt)
            data = json.loads(resp.text)
            return data.get("time")
        except Exception as e:
            logger.warning(f"Time extraction failed: {e}")
            return None

    # ── Name Extraction ───────────────────────────────────────────────────────

    def extract_name(self, text: str) -> str:
        """Extract customer name, fallback to raw text."""
        prompt = f"""The user was asked for their name and said: "{text}"
Return just their name as plain text, properly capitalized. No JSON."""
        try:
            resp = self.model.generate_content(prompt)
            return resp.text.strip()
        except Exception:
            return text.strip().title()
