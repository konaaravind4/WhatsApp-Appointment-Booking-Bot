"""
Flask webhook gateway for WhatsApp Business API (Twilio).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os

from flask import Flask, Response, abort, jsonify, request

from orchestrator import BookingOrchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
orchestrator = BookingOrchestrator()

TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "whatsapp-bot-secret")


# ── Health check ──────────────────────────────────────────────────────────


@app.get("/health")
def health() -> Response:
    return jsonify({"status": "ok", "service": "whatsapp-appointment-bot"})


# ── WhatsApp Cloud API webhook verification ───────────────────────────────


@app.get("/webhook")
def verify_webhook() -> Response:
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("Webhook verified successfully.")
        return Response(challenge, status=200, mimetype="text/plain")
    abort(403)


# ── Inbound messages ──────────────────────────────────────────────────────


@app.post("/webhook")
def handle_webhook() -> Response:
    data = request.get_json(force=True, silent=True) or {}

    try:
        entry = data["entry"][0]["changes"][0]["value"]
        messages = entry.get("messages", [])
        if not messages:
            return jsonify({"status": "no_message"}), 200

        msg = messages[0]
        phone = msg["from"]
        text = msg.get("text", {}).get("body", "")

        if not text:
            return jsonify({"status": "non_text_message"}), 200

        logger.info("Inbound from %s: %s", phone, text[:60])
        reply = orchestrator.process_message(phone, text)

        # In production, send reply via WhatsApp API here
        logger.info("Reply to %s: %s", phone, reply[:80])
        return jsonify({"status": "ok", "reply": reply}), 200

    except (KeyError, IndexError, TypeError) as e:
        logger.warning("Malformed webhook payload: %s", e)
        return jsonify({"status": "ignored"}), 200


# ── Twilio fallback endpoint ──────────────────────────────────────────────


@app.post("/twilio/reply")
def twilio_reply() -> Response:
    """Twilio-compatible webhook endpoint (returns TwiML)."""
    phone = request.form.get("From", "").replace("whatsapp:", "")
    body = request.form.get("Body", "")

    if not phone or not body:
        return Response("<Response/>", mimetype="text/xml")

    logger.info("Twilio inbound from %s: %s", phone, body[:60])
    reply_text = orchestrator.process_message(phone, body)

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{reply_text}</Message>
</Response>"""
    return Response(twiml, mimetype="text/xml")


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
