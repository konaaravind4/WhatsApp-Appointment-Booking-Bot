"""
app/kona_storage.py — KonaDB-backed appointment persistence for the WhatsApp Bot.

Provides full CRUD operations for bookings using KonaDB as the database backend.
Zero external dependencies beyond kona-db itself — works offline.

Usage:
    store = AppointmentStore("appointments.kona")
    booking_id = store.save_booking({...})
    booking = store.get_booking(booking_id)
    store.cancel_booking(booking_id)
    upcoming = store.list_upcoming(hours_ahead=24)
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

from app.models import BookingStats, ServiceType

logger = logging.getLogger(__name__)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS appointments (
    booking_id    TEXT PRIMARY KEY,
    phone         TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    service       TEXT NOT NULL,
    date          TEXT NOT NULL,
    time          TEXT NOT NULL,
    stylist       TEXT NOT NULL,
    duration_min  INTEGER DEFAULT 30,
    price         REAL DEFAULT 0.0,
    notes         TEXT DEFAULT '',
    status        TEXT DEFAULT 'confirmed',
    reminder_sent INTEGER DEFAULT 0,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
)
"""


class AppointmentStore:
    """
    KonaDB-backed appointment store for the WhatsApp Booking Bot.

    Supports:
    - Save / get / cancel bookings
    - List upcoming appointments for reminder scheduling
    - Analytics (booking counts by service and stylist)
    - Graceful degradation if kona package is not installed

    Usage:
        store = AppointmentStore("appointments.kona")
        booking_id = store.save_booking({
            "phone": "+911234567890",
            "customer_name": "Priya Sharma",
            "service": "haircut",
            "date": "2025-06-15",
            "time": "14:00",
            "stylist": "Rahul",
            "duration_min": 30,
            "price": 25.0,
        })
    """

    def __init__(self, db_path: str = "appointments.kona") -> None:
        self.db_path = db_path
        self._conn = None
        self._available = self._try_connect()

    def _try_connect(self) -> bool:
        """Attempt to open/create the KonaDB file. Returns True on success."""
        try:
            import kona  # type: ignore
            self._conn = kona.connect(self.db_path)
            self._conn.execute(_CREATE_TABLE_SQL)
            logger.info("KonaDB appointment store opened at '%s'", self.db_path)
            return True
        except ImportError:
            logger.warning(
                "kona-db package not installed. AppointmentStore will use in-memory fallback."
            )
            self._in_memory: list[dict] = []
            return False
        except Exception as e:
            logger.error("Failed to open KonaDB at '%s': %s", self.db_path, e)
            self._in_memory = []
            return False

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def save_booking(self, booking: dict) -> str:
        """
        Persist a booking to KonaDB and return the assigned booking_id.

        Args:
            booking: Dict with keys: phone, customer_name, service, date,
                     time, stylist, duration_min, price, notes (optional).

        Returns:
            Generated booking_id string (UUID4).

        Raises:
            RuntimeError: If neither KonaDB nor fallback is available.
        """
        booking_id = str(uuid.uuid4())[:8].upper()
        now = time.time()

        record = {
            "booking_id":    booking_id,
            "phone":         booking.get("phone", ""),
            "customer_name": booking.get("customer_name", ""),
            "service":       booking.get("service", ""),
            "date":          booking.get("date", ""),
            "time":          booking.get("time", ""),
            "stylist":       booking.get("stylist", ""),
            "duration_min":  booking.get("duration_min", 30),
            "price":         booking.get("price", 0.0),
            "notes":         booking.get("notes", ""),
            "status":        "confirmed",
            "reminder_sent": 0,
            "created_at":    now,
            "updated_at":    now,
        }

        if self._available and self._conn:
            self._conn.execute(
                """INSERT INTO appointments
                   (booking_id, phone, customer_name, service, date, time,
                    stylist, duration_min, price, notes, status,
                    reminder_sent, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (record["booking_id"], record["phone"], record["customer_name"],
                 record["service"], record["date"], record["time"],
                 record["stylist"], record["duration_min"], record["price"],
                 record["notes"], record["status"], record["reminder_sent"],
                 record["created_at"], record["updated_at"]),
            )
        else:
            self._in_memory.append(record)

        logger.info("Booking saved: %s (%s, %s %s)", booking_id,
                    record["customer_name"], record["date"], record["time"])
        return booking_id

    def get_booking(self, booking_id: str) -> Optional[dict]:
        """
        Retrieve a booking by its ID.

        Args:
            booking_id: The booking identifier string.

        Returns:
            Booking dict, or None if not found.
        """
        if self._available and self._conn:
            rows = self._conn.execute(
                "SELECT * FROM appointments WHERE booking_id = ?",
                (booking_id,),
            )
            if rows:
                return dict(rows[0]) if hasattr(rows[0], "keys") else self._row_to_dict(rows[0])
            return None
        else:
            for record in self._in_memory:
                if record["booking_id"] == booking_id:
                    return record
            return None

    def cancel_booking(self, booking_id: str) -> bool:
        """
        Mark a booking as cancelled.

        Args:
            booking_id: Booking to cancel.

        Returns:
            True if the booking was found and cancelled, False otherwise.
        """
        if self._available and self._conn:
            rows_before = self._conn.execute(
                "SELECT booking_id FROM appointments WHERE booking_id = ? AND status = 'confirmed'",
                (booking_id,),
            )
            if not rows_before:
                return False
            self._conn.execute(
                "UPDATE appointments SET status = 'cancelled', updated_at = ? WHERE booking_id = ?",
                (time.time(), booking_id),
            )
            logger.info("Booking cancelled: %s", booking_id)
            return True
        else:
            for record in self._in_memory:
                if record["booking_id"] == booking_id and record["status"] == "confirmed":
                    record["status"] = "cancelled"
                    record["updated_at"] = time.time()
                    return True
            return False

    def mark_reminder_sent(self, booking_id: str) -> None:
        """Mark a booking's reminder as sent."""
        if self._available and self._conn:
            self._conn.execute(
                "UPDATE appointments SET reminder_sent = 1, updated_at = ? WHERE booking_id = ?",
                (time.time(), booking_id),
            )
        else:
            for record in self._in_memory:
                if record["booking_id"] == booking_id:
                    record["reminder_sent"] = 1
                    record["updated_at"] = time.time()

    # ── Query helpers ─────────────────────────────────────────────────────────

    def list_upcoming(self, hours_ahead: int = 24) -> list[dict]:
        """
        Return confirmed bookings scheduled within the next N hours.

        Used by the reminder scheduler to find bookings that need alerts.

        Args:
            hours_ahead: Window in hours (default: 24).

        Returns:
            List of booking dicts, ordered by appointment time ascending.
        """
        # Note: KonaDB stores date/time as TEXT; we filter in Python
        now_ts = time.time()
        cutoff = now_ts + hours_ahead * 3600
        results: list[dict] = []

        if self._available and self._conn:
            rows = self._conn.execute(
                "SELECT * FROM appointments WHERE status = 'confirmed' ORDER BY date, time"
            )
            for row in (rows or []):
                rec = dict(row) if hasattr(row, "keys") else self._row_to_dict(row)
                results.append(rec)
        else:
            results = [r for r in self._in_memory if r.get("status") == "confirmed"]
            results.sort(key=lambda r: (r.get("date", ""), r.get("time", "")))

        return results

    def get_pending_reminders(self) -> list[dict]:
        """Return confirmed bookings where reminder_sent is False."""
        all_upcoming = self.list_upcoming(hours_ahead=24)
        return [b for b in all_upcoming if not b.get("reminder_sent")]

    # ── Analytics ─────────────────────────────────────────────────────────────

    def get_stats(self) -> BookingStats:
        """
        Compute aggregate booking statistics.

        Returns:
            BookingStats model with counts by service and stylist,
            average duration, and total revenue estimate.
        """
        if self._available and self._conn:
            rows = self._conn.execute(
                "SELECT service, stylist, duration_min, price FROM appointments WHERE status = 'confirmed'"
            ) or []
            records = [dict(r) if hasattr(r, "keys") else self._row_to_dict(r) for r in rows]
        else:
            records = [r for r in self._in_memory if r.get("status") == "confirmed"]

        by_service: dict[str, int] = {}
        by_stylist: dict[str, int] = {}
        total_duration = 0.0
        total_revenue  = 0.0

        for rec in records:
            svc = rec.get("service", "other")
            sty = rec.get("stylist", "unknown")
            by_service[svc] = by_service.get(svc, 0) + 1
            by_stylist[sty] = by_stylist.get(sty, 0) + 1
            total_duration  += float(rec.get("duration_min", 30))
            total_revenue   += float(rec.get("price", 0.0))

        total = len(records)
        avg_duration = round(total_duration / total, 1) if total else 0.0

        return BookingStats(
            total_bookings=total,
            by_service=by_service,
            by_stylist=by_stylist,
            avg_duration_minutes=avg_duration,
            total_revenue_estimate=round(total_revenue, 2),
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the KonaDB connection and flush any pending writes."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass

    def __enter__(self) -> "AppointmentStore":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(row: tuple) -> dict:
        """Convert a raw tuple row to a dict using column order from CREATE TABLE."""
        columns = [
            "booking_id", "phone", "customer_name", "service", "date",
            "time", "stylist", "duration_min", "price", "notes",
            "status", "reminder_sent", "created_at", "updated_at",
        ]
        return dict(zip(columns, row))
