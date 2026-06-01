"""
app/agents/intent_agent.py — Gemini-powered intent & slot extraction agent.

Enhanced with:
- detect_language(): auto-detects English/Hindi/Telugu from Unicode
- extract_phone_number(): regex-based phone extraction
- classify_urgency(): urgency level from keywords (urgent/normal/flexible)
- extract_price_query(): detects when user asks about pricing
- Full type annotations on all methods
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Optional

import google.generativeai as genai

from app.models import ServiceType

logger = logging.getLogger(__name__)

SERVICE_KEYWORDS: dict[ServiceType, list[str]] = {
    ServiceType.HAIRCUT:  ["haircut", "hair cut", "cut", "trim", "hair"],
    ServiceType.BEARD:    ["beard", "shave", "mustache", "shaving"],
    ServiceType.COLOR:    ["color", "colour", "dye", "highlight", "highlights"],
    ServiceType.FACIAL:   ["facial", "face", "skin", "glow"],
    ServiceType.MANICURE: ["manicure", "nails", "nail", "nail art"],
    ServiceType.PEDICURE: ["pedicure", "feet", "foot"],
}

# Urgency keyword lists
_URGENT_KEYWORDS    = ["urgent", "asap", "emergency", "today", "right now", "immediately"]
_FLEXIBLE_KEYWORDS  = ["next week", "whenever", "any day", "flexible", "no rush", "anytime"]

# Price keywords
_PRICE_KEYWORDS     = ["price", "cost", "charge", "fee", "rate", "how much", "expensive",
                       "cheap", "affordable", "rates", "pricing"]

# Phone regex (supports +91, 91, 0 prefixed Indian numbers; 10-digit core)
_PHONE_RE = re.compile(
    r"(?:\+91|91|0)?[\s\-]?([6-9]\d{9})"
)


class IntentAgent:
    """
    Gemini Flash-powered NLU agent for appointment slot extraction.

    Responsibilities:
    - Service type extraction (keyword matching — zero latency)
    - Date/time/name extraction (Gemini LLM — structured JSON output)
    - Language detection (Unicode range — zero latency)
    - Phone number extraction (regex — zero latency)
    - Urgency classification (keyword matching — zero latency)
    - Price query detection (keyword matching — zero latency)
    """

    def __init__(self, api_key: str) -> None:
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
        """
        Keyword-match service type from user text.

        Args:
            text: Raw user message.

        Returns:
            Matched ServiceType, or None if not found.
        """
        text_lower = text.lower()
        for service, keywords in SERVICE_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return service
        return None

    # ── Date Extraction ───────────────────────────────────────────────────────

    def extract_date(self, text: str) -> Optional[str]:
        """
        Parse a natural language date using Gemini Flash.

        Args:
            text: User message containing a date reference.

        Returns:
            ISO date string (YYYY-MM-DD), or None if not found.
        """
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
            logger.warning("Date extraction failed: %s", e)
            return None

    # ── Time Extraction ───────────────────────────────────────────────────────

    def extract_time(self, text: str) -> Optional[str]:
        """
        Parse appointment time from natural language.

        Args:
            text: User message containing a time reference.

        Returns:
            24-hour time string (HH:MM), or None if not found.
        """
        prompt = f"""The user wants to book at: "{text}"
Extract the time in 24-hour format. Return JSON: {{"time": "HH:MM"}}
If unclear, return {{"time": null}}."""
        try:
            resp = self.model.generate_content(prompt)
            data = json.loads(resp.text)
            return data.get("time")
        except Exception as e:
            logger.warning("Time extraction failed: %s", e)
            return None

    # ── Name Extraction ───────────────────────────────────────────────────────

    def extract_name(self, text: str) -> str:
        """
        Extract customer name from user message, with Gemini fallback.

        Args:
            text: User's response when asked for their name.

        Returns:
            Properly capitalised name string.
        """
        prompt = f"""The user was asked for their name and said: "{text}"
Return just their name as plain text, properly capitalized. No JSON."""
        try:
            resp = self.model.generate_content(prompt)
            return resp.text.strip()
        except Exception:
            return text.strip().title()

    # ── Language Detection ────────────────────────────────────────────────────

    def detect_language(self, text: str) -> str:
        """
        Detect the input language from Unicode character ranges.

        Detects English (Latin), Hindi (Devanagari), and Telugu scripts.
        Falls back to 'en' for mixed or unknown scripts.

        Args:
            text: User message text.

        Returns:
            Language code: 'en' | 'hi' | 'te'
        """
        devanagari_count = sum(1 for ch in text if "\u0900" <= ch <= "\u097F")
        telugu_count     = sum(1 for ch in text if "\u0C00" <= ch <= "\u0C7F")
        total = len(text.strip()) or 1

        if devanagari_count / total > 0.15:
            return "hi"
        if telugu_count / total > 0.15:
            return "te"
        return "en"

    # ── Phone Number Extraction ───────────────────────────────────────────────

    def extract_phone_number(self, text: str) -> Optional[str]:
        """
        Extract an Indian mobile number from text using regex.

        Handles formats: +91XXXXXXXXXX, 91XXXXXXXXXX, 0XXXXXXXXXX, XXXXXXXXXX

        Args:
            text: User message that may contain a phone number.

        Returns:
            10-digit mobile number string, or None if not found.
        """
        match = _PHONE_RE.search(text.replace(" ", ""))
        return match.group(1) if match else None

    # ── Urgency Classification ────────────────────────────────────────────────

    def classify_urgency(self, text: str) -> str:
        """
        Classify how urgently the user needs the appointment.

        Args:
            text: User message.

        Returns:
            'urgent' | 'normal' | 'flexible'
        """
        text_lower = text.lower()
        if any(kw in text_lower for kw in _URGENT_KEYWORDS):
            return "urgent"
        if any(kw in text_lower for kw in _FLEXIBLE_KEYWORDS):
            return "flexible"
        return "normal"

    # ── Price Query Detection ─────────────────────────────────────────────────

    def extract_price_query(self, text: str) -> bool:
        """
        Return True if the user is asking about pricing or costs.

        Args:
            text: User message.

        Returns:
            True if the message contains a price-related question.
        """
        text_lower = text.lower()
        return any(kw in text_lower for kw in _PRICE_KEYWORDS)

    # ── Intent Classification (high-level) ───────────────────────────────────

    def classify_intent(self, text: str) -> str:
        """
        High-level intent classification without LLM (keyword-based).

        Args:
            text: User message.

        Returns:
            Intent string: 'book' | 'cancel' | 'reschedule' | 'price_query' |
                           'availability_check' | 'greeting' | 'unknown'
        """
        text_lower = text.lower()
        if any(kw in text_lower for kw in ["book", "appointment", "reserve", "schedule"]):
            return "book"
        if any(kw in text_lower for kw in ["cancel", "cancellation", "stop"]):
            return "cancel"
        if any(kw in text_lower for kw in ["reschedule", "change time", "move", "shift"]):
            return "reschedule"
        if self.extract_price_query(text):
            return "price_query"
        if any(kw in text_lower for kw in ["available", "free slot", "open"]):
            return "availability_check"
        if any(kw in text_lower for kw in ["hi", "hello", "hey", "namaste"]):
            return "greeting"
        return "unknown"



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
