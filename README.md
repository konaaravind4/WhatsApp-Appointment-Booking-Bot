# WhatsApp Appointment Booking Bot 📅

> **Intelligent WhatsApp bot for automated appointment scheduling — with RAG-powered smart suggestions, KonaDB appointment storage, and conflict detection.**

[![Python](https://img.shields.io/badge/python-3.10+-blue)](https://python.org)
[![WhatsApp](https://img.shields.io/badge/WhatsApp-Business_API-brightgreen)](https://developers.facebook.com/docs/whatsapp)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Stars](https://img.shields.io/github/stars/konaaravind4/WhatsApp-Appointment-Booking-Bot?style=social)](https://github.com/konaaravind4/WhatsApp-Appointment-Booking-Bot)

An intelligent WhatsApp bot that handles end-to-end appointment booking through natural conversation — understanding intent, checking availability, avoiding conflicts, and confirming bookings automatically.

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| **Natural Language Booking** | Understands "book a slot tomorrow at 3pm" or "schedule for next Monday morning" |
| **Conflict Detection** | Automatically checks for double-bookings |
| **Multi-Service Support** | Configure multiple service types with different durations |
| **Reminder Notifications** | Sends WhatsApp reminders 24h and 1h before appointment |
| **Cancellation & Rescheduling** | Handles changes via conversation |
| **🆕 KonaDB Storage** | All appointments stored in KonaDB (replaces SQLite) |
| **🆕 RAG Smart Suggestions** | Suggests available slots based on past preferences |
| **🆕 Ecosystem API** | Expose appointments via REST for cross-project queries |

---

## 🏗️ Architecture

```
WhatsApp User Message
        │
        ▼
Webhook Receiver (FastAPI)
        │
        ▼
Intent Classifier
  ├── BOOK_APPOINTMENT
  ├── CANCEL_APPOINTMENT
  ├── RESCHEDULE
  ├── CHECK_AVAILABILITY
  └── UNKNOWN
        │
        ▼
Appointment Manager
  ├── Slot Finder (checks KonaDB for conflicts)
  ├── RAG Suggestion (similar past bookings)
  └── Confirmation Flow
        │
        ▼
WhatsApp Reply + KonaDB Save + Reminder Scheduler
```

---

## 🚀 Quick Start

```bash
git clone https://github.com/konaaravind4/WhatsApp-Appointment-Booking-Bot
cd WhatsApp-Appointment-Booking-Bot
cp .env.example .env
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Configuration

```env
WHATSAPP_TOKEN=your_whatsapp_business_api_token
WHATSAPP_PHONE_ID=your_phone_number_id
VERIFY_TOKEN=your_webhook_verify_token
GEMINI_API_KEY=your_gemini_key        # for NLU
KONA_DB_PATH=appointments.kona        # appointment storage
```

---

## 💬 Sample Conversation

```
User:  Hi, I'd like to book an appointment for a haircut tomorrow

Bot:   Sure! I have these slots available tomorrow (Tuesday, June 2):
       1️⃣  10:00 AM - 10:30 AM
       2️⃣  2:00 PM  - 2:30 PM
       3️⃣  4:30 PM  - 5:00 PM
       
       Which time works for you?

User:  The 2pm slot please

Bot:   ✅ Booked! Appointment confirmed:
       📅 Tuesday, June 2 at 2:00 PM
       ✂️  Service: Haircut (30 min)
       📍 Location: Main Street Salon
       
       You'll receive a reminder 1 hour before. 
       Reply CANCEL to cancel.

User:  Actually can we reschedule to 4:30?

Bot:   ✅ Rescheduled! New time: Tuesday, June 2 at 4:30 PM
```

---

## 💾 KonaDB Storage (New!)

All appointments are stored in [KonaDB](https://github.com/konaaravind4/kona-db) for persistence and analytics:

```python
import kona

conn = kona.connect("appointments.kona")

# Query appointments
upcoming = conn.execute("""
    SELECT * FROM appointments 
    WHERE scheduled_at > ? AND status = 'confirmed'
    ORDER BY scheduled_at ASC
""", (time.time(),))

# Analytics
conn.execute("""
    SELECT service, COUNT(*) as bookings, 
           AVG(duration_minutes) as avg_duration
    FROM appointments
    WHERE created_at > ?
    GROUP BY service
    ORDER BY bookings DESC
""", (week_ago,))
```

---

## 🌍 Ecosystem Integration

```
WhatsApp-Appointment-Booking-Bot
     │
     ├── KonaDB ──────────────────────────────────► Appointment persistence
     │                                               (shared with other projects)
     │
     └── AI SQL Analyst ──────────────────────────► Query appointments in plain English
         "How many haircut appointments were booked this week?"
```

---

## 📄 License

MIT © [konaaravind4](https://github.com/konaaravind4)
