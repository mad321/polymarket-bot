"""
Alert delivery
==============
Sends monitor alerts to every configured channel and keeps a small status
record for /api/alerts/status. The status never contains tokens or phone
numbers, only which settings are missing and the last result per channel.

Telegram (recommended for personal alerts):
  TELEGRAM_BOT_TOKEN  token from @BotFather
  TELEGRAM_CHAT_ID    your chat id: press Start in your bot, then open
                      https://api.telegram.org/bot<TOKEN>/getUpdates
                      and copy the number after "chat":{"id":

WhatsApp (Meta Cloud API): WHATSAPP_TOKEN, PHONE_NUMBER_ID, RECIPIENT_PHONE.
  Plain-text messages only arrive within 24 hours of your last message to the
  business number. Outside that window Meta accepts the request and drops the
  message later (error 131047, reported only to a webhook), so "accepted"
  here does not mean delivered.
"""

import os
import logging
import threading
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_status = {}  # channel -> counters and last result


def _env(name):
    return (os.environ.get(name) or "").strip()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _redact(text, secret):
    # The Telegram token is part of the request URL, so it shows up in
    # connection errors. Never let it reach the logs or the status endpoint.
    return text.replace(secret, "***") if secret else text


def _record(channel, ok, error=None):
    with _lock:
        s = _status.setdefault(channel, {
            "accepted": 0, "failed": 0,
            "last_accepted_at": None, "last_error": None, "last_error_at": None,
        })
        if ok:
            s["accepted"] += 1
            s["last_accepted_at"] = _now()
        else:
            s["failed"] += 1
            s["last_error"] = error
            s["last_error_at"] = _now()


def telegram_api(method, payload, timeout=10):
    """Calls a Telegram Bot API method. Returns (result, error), the token redacted."""
    token = _env("TELEGRAM_BOT_TOKEN")
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/{method}", json=payload, timeout=timeout)
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.ok and data.get("ok"):
            return data.get("result"), None
        error = f"HTTP {r.status_code}: {data.get('description') or r.text[:200]}"
    except Exception as e:
        error = str(e)
    return None, _redact(error, token)


def send_telegram(message, reply_markup=None):
    payload = {"chat_id": _env("TELEGRAM_CHAT_ID"), "text": message, "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    _, error = telegram_api("sendMessage", payload)
    if error is None:
        _record("telegram", True)
        return True
    logger.error(f"[TELEGRAM ERROR] {error}")
    _record("telegram", False, error)
    return False


def send_whatsapp(message, reply_markup=None):  # buttons are Telegram-only
    token = _env("WHATSAPP_TOKEN")
    try:
        r = requests.post(
            f"https://graph.facebook.com/v19.0/{_env('PHONE_NUMBER_ID')}/messages",
            json={
                "messaging_product": "whatsapp",
                "to": _env("RECIPIENT_PHONE"),
                "type": "text",
                "text": {"body": message},
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if r.ok:
            _record("whatsapp", True)
            return True
        try:
            err = r.json().get("error", {})
            error = f"HTTP {r.status_code}: [{err.get('code')}] {err.get('message')}"
        except ValueError:
            error = f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        error = str(e)
    error = _redact(error, token)
    logger.error(f"[WHATSAPP ERROR] {error}")
    _record("whatsapp", False, error)
    return False


CHANNELS = {
    "telegram": (("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"), send_telegram),
    "whatsapp": (("WHATSAPP_TOKEN", "PHONE_NUMBER_ID", "RECIPIENT_PHONE"), send_whatsapp),
}


def configured_channels():
    return [name for name, (keys, _) in CHANNELS.items() if all(_env(k) for k in keys)]


def send_alert(message, reply_markup=None):
    """Sends to every configured channel (buttons on Telegram only).
    True if at least one channel accepted it."""
    channels = configured_channels()
    if not channels:
        logger.warning(f"[ALERT NOT SENT: no channel configured] {message}")
        return False
    results = [CHANNELS[name][1](message, reply_markup) for name in channels]
    return any(results)


def status():
    with _lock:
        snapshot = {name: dict(s) for name, s in _status.items()}
    return {
        name: {
            "configured": all(_env(k) for k in keys),
            "missing_settings": [k for k in keys if not _env(k)],
            **snapshot.get(name, {}),
        }
        for name, (keys, _) in CHANNELS.items()
    }
