"""
Stream processor — simulates Apache Flink real-time booking event stream.
Processes booking events from a Redis stream and routes them to handlers.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from typing import Any

import redis

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
STREAM_KEY = "booking-events"
GROUP_NAME = "booking-processors"
CONSUMER_NAME = "flink-worker-1"


class BookingStreamProcessor:
    """
    Simulates Apache Flink consumer with Redis Streams as the message broker.
    Processes events: booking_created, booking_cancelled, slot_queried.
    """

    def __init__(self):
        self.redis = redis.from_url(REDIS_URL, decode_responses=True)
        self._running = True
        self._setup_consumer_group()

        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _setup_consumer_group(self) -> None:
        try:
            self.redis.xgroup_create(STREAM_KEY, GROUP_NAME, id="$", mkstream=True)
        except redis.ResponseError:
            pass  # group already exists

    def publish_event(self, event_type: str, data: dict[str, Any]) -> str:
        """Publish a booking event to the stream. Returns message ID."""
        payload = {"event": event_type, "data": json.dumps(data)}
        return self.redis.xadd(STREAM_KEY, payload)

    def run(self) -> None:
        """Main consumer loop — reads and processes events from the stream."""
        logger.info("Stream processor started. Listening on '%s'...", STREAM_KEY)
        while self._running:
            try:
                messages = self.redis.xreadgroup(
                    GROUP_NAME,
                    CONSUMER_NAME,
                    {STREAM_KEY: ">"},
                    count=10,
                    block=1000,
                )
                if not messages:
                    continue

                for _stream, entries in messages:
                    for msg_id, fields in entries:
                        self._process(msg_id, fields)
                        self.redis.xack(STREAM_KEY, GROUP_NAME, msg_id)

            except redis.ConnectionError as e:
                logger.error("Redis connection error: %s. Retrying in 3s...", e)
                time.sleep(3)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _process(self, msg_id: str, fields: dict) -> None:
        event = fields.get("event")
        data = json.loads(fields.get("data", "{}"))
        logger.info("Processing event [%s] id=%s", event, msg_id)

        handlers = {
            "booking_created": self._on_booking_created,
            "booking_cancelled": self._on_booking_cancelled,
            "slot_queried": self._on_slot_queried,
        }
        handler = handlers.get(event)
        if handler:
            handler(data)
        else:
            logger.warning("Unknown event type: %s", event)

    def _on_booking_created(self, data: dict) -> None:
        booking_id = data.get("booking_id")
        service = data.get("service")
        logger.info("✅ New booking created: %s (%s)", booking_id, service)
        # Update analytics counter
        self.redis.hincrby("analytics:bookings", service or "unknown", 1)
        self.redis.hincrby("analytics:bookings", "total", 1)

    def _on_booking_cancelled(self, data: dict) -> None:
        booking_id = data.get("booking_id")
        logger.info("❌ Booking cancelled: %s", booking_id)
        self.redis.hincrby("analytics:bookings", "cancelled", 1)

    def _on_slot_queried(self, data: dict) -> None:
        date = data.get("date")
        service = data.get("service")
        logger.info("🔍 Slot queried: %s %s", date, service)
        self.redis.hincrby("analytics:queries", service or "unknown", 1)

    def _shutdown(self, *_) -> None:
        logger.info("Shutting down stream processor...")
        self._running = False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s — %(message)s")
    processor = BookingStreamProcessor()
    processor.run()
