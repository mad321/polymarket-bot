"""
Telegram commands and sell buttons
==================================
Long-polls Telegram for commands and button taps (no public webhook to
secure) and acts only on messages from TELEGRAM_CHAT_ID.

  /positions          the bot wallet's positions, each with a sell button
  🔴 بيع الآن          shows the minimum sale price and asks for confirmation
  ✅ تأكيد البيع       sells (or simulates in dry-run); valid for 2 minutes

Only one process may poll a bot token: run the web app with one worker.
"""

import os
import time
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import alerts
import trading

logger = logging.getLogger(__name__)

CONFIRM_TTL = 120   # seconds a confirmation button stays valid
POLL_TIMEOUT = 25   # Telegram long-poll wait, in seconds

# Read by /api/alerts/status. Chat ids appear only as their last 3 digits.
STATE = {
    "running": False,
    "last_update_at": None,
    "last_error": None,
    "last_reply_error": None,
    "ignored_other_chat": 0,
    "last_ignored_chat_ends_with": None,
    "chat_id_setting": None,
}

# Direction marks and other invisible characters that RTL keyboards and
# copy-paste slip into "/start" or a copied chat id.
_INVISIBLE = dict.fromkeys(map(ord, "​‌‍‎‏‪‫‬‭"
                                    "‮⁦⁧⁨⁩﻿ "))


def _clean(text):
    return str(text).translate(_INVISIBLE).strip()

HELP = (
    "أوامر البوت:\n"
    "/positions صفقات محفظة البوت، مع زر بيع لكل صفقة.\n\n"
    "التنبيهات تصلك هنا تلقائياً. تنبيهات صفقات محفظة البوت يأتي معها زر \"🔴 بيع الآن\"."
)


def _chat_id():
    return _clean(os.environ.get("TELEGRAM_CHAT_ID") or "")


def sell_button(asset_id):
    key = trading.position_key(asset_id)
    return {"inline_keyboard": [[{"text": "🔴 بيع الآن", "callback_data": f"s:{key}"}]]}


def _cents(price):
    return f"{(Decimal(price) * 100).normalize():f}¢"


def _usd(value):
    return f"${Decimal(value):.2f}"


def _reply(text, markup=None):
    payload = {"chat_id": _chat_id(), "text": text, "disable_web_page_preview": True}
    if markup:
        payload["reply_markup"] = markup
    _, error = alerts.telegram_api("sendMessage", payload)
    if error:
        STATE["last_reply_error"] = error
        logger.error(f"[TELEGRAM REPLY ERROR] {error}")


def _close(message, note):
    """Appends a note to a message and removes its buttons, so it cannot be tapped twice."""
    alerts.telegram_api("editMessageText", {
        "chat_id": _chat_id(),
        "message_id": message.get("message_id"),
        "text": f"{message.get('text') or ''}\n\n{note}",
        "reply_markup": {"inline_keyboard": []},
    })


def _answer(callback, text=""):
    alerts.telegram_api("answerCallbackQuery", {"callback_query_id": callback.get("id"), "text": text})


def _unavailable():
    """Why selling is off, or None when it is available."""
    if not trading.enabled():
        return "البيع من تيليجرام غير مفعّل. لتفعيله أضف TRADING_ENABLED بقيمة 1 في Render."
    if not trading.configured():
        return "إعدادات التداول ناقصة: أضف TRADING_WALLET و TRADING_PRIVATE_KEY في Render."
    return None


def _dry_run_note():
    return "🧪 وضع التجربة: لن يُرسل أي أمر حقيقي.\n" if trading.dry_run() else ""

# ─── COMMANDS ────────────────────────────────────────────────────────────────

def handle_command(text):
    command = text.strip().split()[0].split("@")[0].lower()
    if command != "/positions":
        _reply(HELP)
        return
    reason = _unavailable()
    if reason:
        _reply(reason)
        return
    try:
        positions = trading.list_positions()
    except trading.TradingError as e:
        _reply(f"⚠️ {e}")
        return
    if not positions:
        _reply(_dry_run_note() + "لا توجد صفقات مفتوحة في محفظة البوت.")
        return
    _reply(_dry_run_note() + f"صفقات محفظة البوت: {len(positions)}")
    for p in positions:
        _reply(f"{p['name']}\nالأسهم: {p['shares']}\nالسعر الحالي: {_cents(p['current_price'])}",
               sell_button(p["asset_id"]))

# ─── BUTTONS ─────────────────────────────────────────────────────────────────

def handle_callback(callback):
    data = callback.get("data") or ""
    message = callback.get("message") or {}
    if data == "x":
        _answer(callback, "أُلغي")
        _close(message, "✖️ أُلغي البيع.")
        return
    reason = _unavailable()
    if reason:
        _answer(callback)
        _reply(reason)
        return
    kind, _, rest = data.partition(":")
    if kind == "s":
        _ask_confirmation(callback, rest)
    elif kind == "c":
        _confirm(callback, message, rest)
    else:
        _answer(callback)


def _ask_confirmation(callback, key):
    _answer(callback, "جارٍ حساب سعر البيع…")
    try:
        q = trading.quote(key)
    except trading.TradingError as e:
        _reply(f"⚠️ {e}")
        return
    lines = [
        f"{_dry_run_note()}تأكيد بيع: {q['name']}",
        f"الأسهم: {q['shares']}",
        f"أقل سعر مقبول: {_cents(q['price'])} (السعر الحالي {_cents(q['current_price'])})",
        f"المبلغ المتوقع: {_usd(q['proceeds'])} تقريباً",
        "الزر صالح لمدة دقيقتين.",
    ]
    if q["current_price"] and q["price"] < q["current_price"] * Decimal("0.8"):
        lines.append("⚠️ المشترون قليلون: بيع كل الأسهم الآن يكون بسعر أقل بكثير من السعر الحالي.")
    data = f"c:{key}:{q['price'].normalize():f}:{q['shares']:f}:{int(time.time())}"  # ≤ 64 bytes
    _reply("\n".join(lines), {"inline_keyboard": [[
        {"text": "✅ تأكيد البيع", "callback_data": data},
        {"text": "✖️ إلغاء", "callback_data": "x"},
    ]]})


def _confirm(callback, message, rest):
    try:
        key, price, shares, issued_at = rest.split(":")
        price, shares, issued_at = Decimal(price), Decimal(shares), int(issued_at)
    except (ValueError, InvalidOperation):
        _answer(callback, "زر غير صالح")
        return
    if time.time() - issued_at > CONFIRM_TTL:
        _answer(callback, "انتهت صلاحية التأكيد")
        _close(message, "⌛ انتهت صلاحية هذا التأكيد. اضغط \"بيع الآن\" مرة أخرى لسعر جديد.")
        return
    _answer(callback, "جارٍ البيع…")
    _close(message, "⏳ جارٍ التنفيذ…")
    try:
        result = trading.sell(key, shares, price)
    except trading.TradingError as e:
        _reply(f"⚠️ {e}")
        return
    except Exception:
        logger.exception("Sell failed unexpectedly")
        # The order may or may not have reached Polymarket: say so plainly.
        _reply("⚠️ حدث خطأ غير متوقع أثناء البيع. افتح /positions أو بوليماركت وتحقق من الصفقة "
               "قبل أن تحاول مرة أخرى.")
        return
    _reply(result_text(result))


def result_text(r):
    if r["status"] == "dry_run":
        return (f"🧪 تجربة ناجحة: كان البوت سيبيع {r['shares']} سهم من {r['name']} "
                f"بسعر لا يقل عن {_cents(r['min_price'])}. لم يُرسل أي أمر حقيقي.")
    if not r["ok"]:
        return f"❌ لم يتم البيع: {r.get('message') or r['status']}"
    if r["status"] == "delayed":
        return "⏳ قُبل أمر البيع، لكن هذا السوق يؤخر التنفيذ قليلاً. تحقق من الصفقة بعد دقيقة."
    text = f"✅ تم البيع: {r['name']}"
    sold, received = Decimal(r.get("sold") or 0), Decimal(r.get("received") or 0)
    # Show the fill only when it is plausible in shares and dollars.
    if 0 < sold <= Decimal(r["shares"]) + Decimal("0.01") and 0 <= received <= sold:
        text += f"\nبِيع {sold.normalize():f} سهم مقابل {_usd(received)}"
    return f"{text}\nرقم الأمر: {r.get('order_id')}"

# ─── POLLING ─────────────────────────────────────────────────────────────────

def _authorized(update):
    message = update.get("message") or (update.get("callback_query") or {}).get("message") or {}
    chat = _clean((message.get("chat") or {}).get("id", ""))
    if chat and chat == _chat_id():
        return True
    STATE["ignored_other_chat"] += 1
    STATE["last_ignored_chat_ends_with"] = chat[-3:]
    logger.info(f"Ignored a Telegram update from chat …{chat[-3:]}")
    return False


def handle_update(update):
    if not _authorized(update):
        return
    try:
        if "callback_query" in update:
            handle_callback(update["callback_query"])
            return
        text = _clean((update.get("message") or {}).get("text") or "")
        if text.startswith("/"):
            handle_command(text)
        elif text:
            _reply(HELP)
    except Exception:
        logger.exception("Telegram update failed")
        _reply("⚠️ حدث خطأ غير متوقع، حاول مرة أخرى بعد قليل.")


def poll_forever():
    STATE["running"] = True
    raw = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    STATE["chat_id_setting"] = {"ends_with": _chat_id()[-3:], "has_hidden_characters": _chat_id() != raw}
    alerts.telegram_api("setMyCommands", {"commands": [
        {"command": "positions", "description": "صفقات محفظة البوت وأزرار البيع"},
    ]})
    trading.check_geoblock()

    # Skip whatever arrived while the bot was down: an old tap must not act now.
    offset = None
    pending, _ = alerts.telegram_api("getUpdates", {"offset": -1, "timeout": 0})
    if pending:
        offset = pending[-1]["update_id"] + 1

    while True:
        payload = {"timeout": POLL_TIMEOUT, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        updates, error = alerts.telegram_api("getUpdates", payload, timeout=POLL_TIMEOUT + 10)
        if error:
            # A 409 means another instance polls too, e.g. while Render
            # swaps deploys; the old one stops shortly.
            STATE["last_error"] = error
            time.sleep(5)
            continue
        for update in updates or []:
            offset = update["update_id"] + 1
            STATE["last_update_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            try:
                handle_update(update)
            except Exception:
                logger.exception("Telegram update failed")
