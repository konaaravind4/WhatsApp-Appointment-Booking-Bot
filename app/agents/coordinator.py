"""
app/agents/coordinator.py — A2A orchestrator that manages conversation flow
and delegates to specialist sub-agents.
"""

import logging
import threading
from app.models import IncomingMessage, SessionData, ConversationState
from app.redis_cache import SessionStore
from app.agents.intent_agent import IntentAgent
from app.agents.availability_agent import AvailabilityAgent
from app.agents.confirmation_agent import ConfirmationAgent

logger = logging.getLogger(__name__)


class CoordinatorAgent:
    """
    Main orchestrator: reads session state from Redis and routes the
    conversation to the appropriate sub-agent at each turn.
    """

    def __init__(
        self,
        gemini_api_key: str,
        waba_token: str,
        phone_number_id: str,
        verify_token: str,
        session_store: SessionStore,
    ):
        self.session_store = session_store
        self.intent_agent = IntentAgent(api_key=gemini_api_key)
        self.availability_agent = AvailabilityAgent()
        self.confirmation_agent = ConfirmationAgent(
            waba_token=waba_token,
            phone_number_id=phone_number_id,
        )

    def handle(self, msg: IncomingMessage) -> None:
        """Handle an incoming message in a background thread."""
        thread = threading.Thread(
            target=self._process, args=(msg,), daemon=True
        )
        thread.start()

    def _process(self, msg: IncomingMessage) -> None:
        try:
            session: SessionData = self.session_store.get_session(msg.from_number)
            session.message_count += 1
            reply = self._route(msg.text, session)
            self.session_store.save_session(session)
            self.confirmation_agent.send_text(msg.from_number, reply)
        except Exception:
            logger.exception(f"Error processing message from {msg.from_number}")
            self.confirmation_agent.send_text(
                msg.from_number,
                "Sorry, something went wrong. Please try again in a moment. 🙏",
            )

    def _route(self, text: str, session: SessionData) -> str:
        state = session.state

        if state == ConversationState.GREETING:
            session.state = ConversationState.COLLECTING_SERVICE
            return (
                "👋 Welcome to *Aravind Salon*! I'm your booking assistant.\n\n"
                "Which service would you like?\n"
                "• 💇 Haircut\n• 🧔 Beard trim\n• 🎨 Color\n• 💆 Facial\n• 💅 Manicure/Pedicure"
            )

        elif state == ConversationState.COLLECTING_SERVICE:
            slot = self.intent_agent.extract_service(text)
            if slot:
                session.slot.service = slot
                session.state = ConversationState.COLLECTING_DATE
                return f"Great choice! *{slot.value.title()}* it is. 💈\n\nWhat date works for you? (e.g. *15 March* or *tomorrow*)"
            return "I didn't quite catch that. Could you please choose a service from the list?"

        elif state == ConversationState.COLLECTING_DATE:
            date = self.intent_agent.extract_date(text)
            if date:
                session.slot.date = date
                session.state = ConversationState.COLLECTING_TIME
                return f"📅 Got it — *{date}*.\nWhat time would you prefer? (e.g. *10:00 AM* or *2 PM*)"
            return "I couldn't understand the date. Could you try again? (e.g. *March 15* or *tomorrow*)"

        elif state == ConversationState.COLLECTING_TIME:
            time = self.intent_agent.extract_time(text)
            if time:
                available, stylist = self.availability_agent.check(
                    session.slot.date, time, session.slot.service
                )
                if available:
                    session.slot.time = time
                    session.slot.stylist = stylist
                    session.state = ConversationState.COLLECTING_NAME
                    return f"✅ *{time}* is available with *{stylist}*!\n\nMay I have your name for the booking?"
                else:
                    return (
                        f"Sorry, *{time}* on {session.slot.date} is fully booked. 😔\n"
                        "Please choose another time."
                    )
            return "I couldn't parse the time. Please try again (e.g. *10 AM* or *14:30*)."

        elif state == ConversationState.COLLECTING_NAME:
            name = self.intent_agent.extract_name(text)
            session.slot.customer_name = name
            session.state = ConversationState.CONFIRMING
            s = session.slot
            return (
                f"📋 Please confirm your booking:\n\n"
                f"• 💈 Service: *{s.service.value.title()}*\n"
                f"• 📅 Date: *{s.date}*\n"
                f"• ⏰ Time: *{s.time}*\n"
                f"• 👤 Name: *{name}*\n"
                f"• 💆 Stylist: *{s.stylist}*\n\n"
                f"Reply *YES* to confirm or *NO* to cancel."
            )

        elif state == ConversationState.CONFIRMING:
            if text.strip().upper() == "YES":
                booking = self.confirmation_agent.create_booking(session.slot)
                session.state = ConversationState.BOOKED
                return (
                    f"🎉 *Booking Confirmed!*\n\n"
                    f"Booking ID: `{booking.booking_id}`\n"
                    f"See you on {booking.date} at {booking.time}! 🙌\n\n"
                    f"We'll send a reminder 1 hour before. Type *CANCEL* anytime to cancel."
                )
            else:
                session.state = ConversationState.GREETING
                return "No problem! Your booking has been cancelled. Type anything to start again. 👋"

        elif state == ConversationState.BOOKED:
            if "cancel" in text.lower():
                session.state = ConversationState.CANCELLED
                return "Your appointment has been cancelled. We hope to see you soon! 💙"
            return "You already have a booking! Type *CANCEL* to cancel or visit us soon. 😊"

        return "I'm not sure how to help with that. Type *Hi* to start a new booking."
