"""
Tests for WhatsApp Appointment Bot agents.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, PropertyMock


# ── Intent Agent tests ────────────────────────────────────────────────────

class TestIntentAgent:
    @patch("agents.intent_agent.genai")
    def test_extract_full_intent(self, mock_genai):
        from agents.intent_agent import IntentAgent, BookingIntent

        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        mock_model.generate_content.return_value.text = (
            '{"service":"haircut","date":"2025-12-25","time":"14:00",'
            '"customer_name":"Alice","confirmed":false}'
        )

        agent = IntentAgent(api_key="test-key")
        intent = agent.extract("Book haircut on Christmas at 2pm for Alice")

        assert intent.service == "haircut"
        assert intent.date == "2025-12-25"
        assert intent.time == "14:00"
        assert intent.customer_name == "Alice"
        assert intent.confirmed is False

    @patch("agents.intent_agent.genai")
    def test_extract_partial_intent(self, mock_genai):
        from agents.intent_agent import IntentAgent

        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        mock_model.generate_content.return_value.text = (
            '{"service":"facial","date":null,"time":null,"customer_name":null,"confirmed":false}'
        )

        agent = IntentAgent(api_key="test-key")
        intent = agent.extract("I want a facial")
        assert intent.service == "facial"
        assert intent.date is None
        assert intent.time is None

    @patch("agents.intent_agent.genai")
    def test_extract_handles_json_error(self, mock_genai):
        from agents.intent_agent import IntentAgent

        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        mock_model.generate_content.return_value.text = "not valid json"

        agent = IntentAgent(api_key="test-key")
        intent = agent.extract("some message")
        assert intent.service is None  # graceful fallback

    @patch("agents.intent_agent.genai")
    def test_generate_response_for_missing_service(self, mock_genai):
        from agents.intent_agent import IntentAgent, BookingIntent

        mock_genai.GenerativeModel.return_value = MagicMock()
        agent = IntentAgent(api_key="test-key")
        intent = BookingIntent()
        response = agent.generate_response(intent, ["service"])
        assert "service" in response.lower() or "book" in response.lower()


# ── Availability Agent tests ──────────────────────────────────────────────

class TestAvailabilityAgent:
    @patch("agents.availability_agent.redis.from_url")
    def test_check_slot_available(self, mock_redis_fn):
        from agents.availability_agent import AvailabilityAgent

        mock_redis = MagicMock()
        mock_redis_fn.return_value = mock_redis
        mock_redis.get.return_value = None  # slot is free

        agent = AvailabilityAgent()
        assert agent.check_slot("2025-12-25", "10:00", "haircut") is True

    @patch("agents.availability_agent.redis.from_url")
    def test_check_slot_booked(self, mock_redis_fn):
        from agents.availability_agent import AvailabilityAgent

        mock_redis = MagicMock()
        mock_redis_fn.return_value = mock_redis
        mock_redis.get.return_value = "booked"

        agent = AvailabilityAgent()
        assert agent.check_slot("2025-12-25", "10:00", "haircut") is False

    @patch("agents.availability_agent.redis.from_url")
    def test_reserve_slot_success(self, mock_redis_fn):
        from agents.availability_agent import AvailabilityAgent

        mock_redis = MagicMock()
        mock_redis_fn.return_value = mock_redis
        mock_redis.set.return_value = True

        agent = AvailabilityAgent()
        result = agent.reserve_slot("2025-12-25", "10:00", "haircut", "phone123")
        assert result is True

    @patch("agents.availability_agent.redis.from_url")
    def test_reserve_slot_race_condition(self, mock_redis_fn):
        from agents.availability_agent import AvailabilityAgent

        mock_redis = MagicMock()
        mock_redis_fn.return_value = mock_redis
        mock_redis.set.return_value = None  # another process got it first

        agent = AvailabilityAgent()
        result = agent.reserve_slot("2025-12-25", "10:00", "haircut", "phone456")
        assert result is False


# ── Confirmation Agent tests ──────────────────────────────────────────────

class TestConfirmationAgent:
    @patch("agents.confirmation_agent.redis.from_url")
    def test_confirmation_message_format(self, mock_redis_fn):
        from agents.confirmation_agent import ConfirmationAgent, Booking

        mock_redis_fn.return_value = MagicMock()
        agent = ConfirmationAgent()
        booking = Booking(
            booking_id="ABC123",
            customer_name="Bob",
            service="haircut",
            date="2025-12-25",
            time="10:00",
            status="confirmed",
        )
        msg = ConfirmationAgent.confirmation_message(booking)
        assert "ABC123" in msg
        assert "Bob" in msg
        assert "Haircut" in msg
        assert "CANCEL" in msg

    @patch("agents.confirmation_agent.redis.from_url")
    def test_create_booking_stores_in_redis(self, mock_redis_fn):
        from agents.confirmation_agent import ConfirmationAgent

        mock_redis = MagicMock()
        mock_redis_fn.return_value = mock_redis

        agent = ConfirmationAgent()
        booking = agent.create_booking(
            customer_name="Alice",
            phone="+1234567890",
            service="facial",
            date="2025-12-26",
            time="14:00",
        )

        assert booking.status == "confirmed"
        assert booking.customer_name == "Alice"
        mock_redis.hset.assert_called_once()
