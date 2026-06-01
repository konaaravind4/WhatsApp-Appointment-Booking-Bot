"""
app/models.py — Pydantic schemas for the WhatsApp Appointment Bot.

Enhanced with:
- PRICE_ESTIMATES constant for all service types
- BookingStats model for analytics
- ReminderTask model for reminder scheduling
- New fields: booking_id, price_estimate, notes, reminder_sent on AppointmentSlot
- New fields: language, retry_count, last_intent on SessionData
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ── Service price estimates (INR) ─────────────────────────────────────────────
PRICE_ESTIMATES: dict[str, float] = {
    "haircut":   25.0,
    "beard":     15.0,
    "color":     80.0,
    "facial":    50.0,
    "manicure":  35.0,
    "pedicure":  40.0,
    "other":     20.0,
}


class ServiceType(str, Enum):
    HAIRCUT = "haircut"
    BEARD = "beard"
    COLOR = "color"
    FACIAL = "facial"
    MANICURE = "manicure"
    PEDICURE = "pedicure"
    OTHER = "other"


class ConversationState(str, Enum):
    GREETING = "greeting"
    COLLECTING_SERVICE = "collecting_service"
    COLLECTING_DATE = "collecting_date"
    COLLECTING_TIME = "collecting_time"
    COLLECTING_NAME = "collecting_name"
    CONFIRMING = "confirming"
    BOOKED = "booked"
    CANCELLED = "cancelled"


class IncomingMessage(BaseModel):
    from_number: str
    text: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AppointmentSlot(BaseModel):
    """Holds all collected slot information during a booking conversation."""
    service: Optional[ServiceType] = None
    date: Optional[str] = None                    # YYYY-MM-DD
    time: Optional[str] = None                    # HH:MM (24h)
    customer_name: Optional[str] = None
    stylist: Optional[str] = None
    duration_minutes: int = 60
    # Enhanced fields
    booking_id: Optional[str] = None              # Set after confirmation
    price_estimate: Optional[float] = None        # From PRICE_ESTIMATES
    notes: Optional[str] = None                   # Customer special requests
    reminder_sent: bool = False                   # True once reminder dispatched


class SessionData(BaseModel):
    """Full conversation session — one per WhatsApp number."""
    phone: str
    state: ConversationState = ConversationState.GREETING
    slot: AppointmentSlot = Field(default_factory=AppointmentSlot)
    message_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    # Enhanced fields
    language: str = "en"                          # Detected language code
    retry_count: int = 0                          # Consecutive failed extractions
    last_intent: Optional[str] = None             # Last classified user intent


class BookingStats(BaseModel):
    """Aggregate statistics across all bookings."""
    total_bookings: int
    by_service: dict[str, int]                    # service_name -> count
    by_stylist: dict[str, int]                    # stylist_name -> count
    avg_duration_minutes: float
    total_revenue_estimate: float                 # Sum of price estimates


class ReminderTask(BaseModel):
    """Scheduled appointment reminder to be dispatched via WhatsApp."""
    booking_id: str
    phone: str
    customer_name: str
    service: ServiceType
    appointment_datetime: str                     # ISO 8601
    scheduled_at: datetime                        # When to send the reminder
    sent: bool = False
    sent_at: Optional[datetime] = None


class BookingConfirmation(BaseModel):
    """Returned after a booking is confirmed and persisted."""
    booking_id: str
    customer_name: str
    service: ServiceType
    date: str
    time: str
    stylist: str
    price_estimate: Optional[float] = None
    confirmation_message: str
    reminder_task: Optional[ReminderTask] = None  # Scheduled reminder
