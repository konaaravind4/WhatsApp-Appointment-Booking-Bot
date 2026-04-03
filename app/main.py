"""
app/main.py — Flask webhook handler for WhatsApp Business API (Twilio gateway).

Handles:
  - GET  /webhook  → Twilio verification challenge
  - POST /webhook  → Incoming WhatsApp messages from users
"""

import os
import logging
from flask import Flask, request, jsonify, Response
from dotenv import load_dotenv

from app.agents.coordinator import CoordinatorAgent
from app.redis_cache import SessionStore
from app.models import IncomingMessage

load_dotenv()

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ─── App Setup ────────────────────────────────────────────────────────────────
app = Flask(__name__)
session_store = SessionStore(redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"))
coordinator = CoordinatorAgent(
    gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
    waba_token=os.getenv("WABA_TOKEN", ""),
    phone_number_id=os.getenv("PHONE_NUMBER_ID", ""),
    verify_token=os.getenv("WHATSAPP_VERIFY_TOKEN", ""),
    session_store=session_store,
)


# ─── Webhook Verification ─────────────────────────────────────────────────────
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    """WhatsApp Business API webhook verification (hub challenge)."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == os.getenv("WHATSAPP_VERIFY_TOKEN"):
        logger.info("✅ Webhook verified")
        return Response(challenge, status=200, mimetype="text/plain")

    logger.warning("❌ Webhook verification failed")
    return jsonify({"error": "Forbidden"}), 403


# ─── Incoming Messages ────────────────────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def receive_message():
    """Handle incoming WhatsApp messages."""
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"error": "Empty payload"}), 400

    try:
        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            # Acknowledgement / status update, not a message
            return jsonify({"status": "ok"}), 200

        msg_data = messages[0]
        from_number = msg_data.get("from")
        text = msg_data.get("text", {}).get("body", "").strip()

        if not from_number or not text:
            return jsonify({"status": "ignored"}), 200

        incoming = IncomingMessage(from_number=from_number, text=text)
        logger.info(f"📨 From {from_number}: {text}")

        # Delegate to coordinator agent (async processing)
        coordinator.handle(incoming)
        return jsonify({"status": "processing"}), 200

    except Exception as exc:
        logger.exception(f"Error handling message: {exc}")
        return jsonify({"error": "Internal server error"}), 500


# ─── Health ───────────────────────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "whatsapp-appointment-bot"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
