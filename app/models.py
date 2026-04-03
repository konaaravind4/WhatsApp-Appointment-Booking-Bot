"""
app/models.py — Pydantic schemas for the WhatsApp Appointment Bot.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


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
    service: Optional[ServiceType] = None
    date: Optional[str] = None           # YYYY-MM-DD
    time: Optional[str] = None           # HH:MM (24h)
    customer_name: Optional[str] = None
    stylist: Optional[str] = None
    duration_minutes: int = 60


class SessionData(BaseModel):
    phone: str
    state: ConversationState = ConversationState.GREETING
    slot: AppointmentSlot = Field(default_factory=AppointmentSlot)
    message_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class BookingConfirmation(BaseModel):
    booking_id: str
    customer_name: str
    service: ServiceType
    date: str
    time: str
    stylist: str
    confirmation_message: str
