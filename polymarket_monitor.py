"""
Polymarket Price Monitor
========================
Checks the open positions every 30 seconds (discovered from the wallet, see
positions.py) and sends an alert when a price reaches its stop-loss or
take-profit. It never places orders itself: alerts for the bot's own wallet
carry a sell button, and a sale happens only when you confirm it in Telegram
(telegram_actions.py, trading.py).

Alerts go to every channel configured in alerts.py (Telegram and/or WhatsApp).
Runs as a background thread of the web app (polymarket_bot.py); its state is
served at /api/alerts/status.

Optional settings:
  ALERT_COOLDOWN  seconds before re-alerting the same position (default 3600)
  STARTUP_ALERT   "0" to skip the "monitor started" message
  ALERT_TZ        time zone for alert timestamps (default Asia/Riyadh)
"""

import os
import time
import logging
from datetime import datetime, timezone

import pytz
import requests

import alerts
import trading
import telegram_actions
from positions import get_price_by_slug, load_positions

logger = logging.getLogger(__name__)

# ─── CONFIG ──────────────────────────────────────────────────────────────────

POLYMARKET_API = "https://clob.polymarket.com"

CHECK_INTERVAL = 30          # seconds between price checks
RETRY_AFTER_FAILURE = 300    # seconds before retrying an alert no channel accepted
ALERT_COOLDOWN = int(os.environ.get("ALERT_COOLDOWN", 3600))

try:
    ALERT_TZ = pytz.timezone(os.environ.get("ALERT_TZ", "Asia/Riyadh"))
except pytz.UnknownTimeZoneError:
    ALERT_TZ = pytz.utc

# Read by /api/alerts/status.
STATE = {
    "running": False,
    "started_at": None,
    "last_check_at": None,
    "positions": 0,
    "past_level": 0,
    "source": None,
    "error": None,
    "alert_cooldown_seconds": ALERT_COOLDOWN,
}

STARTUP_MESSAGE = (
    "✅ مراقب بوليماركت بدأ العمل.\n"
    "ستصلك هنا التنبيهات عند وصول أي صفقة لوقف الخسارة أو الهدف."
)

# ─── HELPERS ─────────────────────────────────────────────────────────────────

def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_price_by_token_id(token_id: str) -> float | None:
    """Current sell price (cents) for a CLOB token ID, or None on error."""
    try:
        url = f"{POLYMARKET_API}/price?token_id={token_id}&side=sell"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        price = r.json().get("price")
        if price is not None:
            return round(float(price) * 100, 1)
    except Exception as e:
        logger.error(f"Error fetching token {token_id[:12]}...: {e}")
    return None


def get_price(position: dict) -> float | None:
    """Fallback when the wallet did not report a current price."""
    if "token_id" in position:
        return get_price_by_token_id(position["token_id"])
    if position.get("slug"):
        return get_price_by_slug(position["slug"])
    return None


def level_hit(position: dict, price: float) -> str | None:
    """"stop_loss" or "take_profit" when the price is at or past that level."""
    stop, tp = position.get("stop_loss"), position.get("take_profit")
    if stop and price <= stop:
        return "stop_loss"
    if tp and price >= tp:
        return "take_profit"
    return None


def _signed_usd(value: float) -> str:
    # The left-to-right mark keeps the sign before the number in RTL messages.
    value = round(value, 2)
    return f"‎{'-' if value < 0 else '+'}${abs(value):.2f}"


def _in_trading_wallet(pos: dict) -> bool:
    wallet = trading.trading_wallet()
    return bool(wallet) and pos.get("wallet") == wallet


def format_alert(pos: dict, price: float, reason: str) -> str:
    """Alert message in Arabic."""
    hit_stop = reason == "stop_loss"
    level = pos["stop_loss"] if hit_stop else pos["take_profit"]
    lines = [
        "🔴 تنبيه بوليماركت: وقف الخسارة" if hit_stop else "🟢 تنبيه بوليماركت: وصل للهدف",
        f"الصفقة: {pos['name']}",
        f"السعر الحالي: {price}¢ (الحد: {level}¢)",
        f"الإجراء: {'بيع فوري - وقف الخسارة' if hit_stop else 'خذ الأرباح'}",
        f"الأسهم: {pos['shares']}",
    ]
    if _in_trading_wallet(pos):
        lines.append("المحفظة: محفظة البوت")
    if pos.get("pnl_usd") is not None:
        lines.append(f"الربح / الخسارة: {_signed_usd(pos['pnl_usd'])}")
    if pos.get("url"):
        lines.append(pos["url"])
    lines.append(f"الوقت: {datetime.now(ALERT_TZ):%H:%M}")
    return "\n".join(lines)

# ─── MAIN LOOP ────────────────────────────────────────────────────────────────

def check_once(next_alert_at: dict[str, float]) -> None:
    """One pass over the positions; sends the alerts that are due."""
    positions, source, error = load_positions()
    now = time.time()
    past_level = 0

    for pos in positions:
        price = pos.get("current_price")
        if price is None:
            price = get_price(pos)
        if price is None:
            logger.warning(f"{pos['name']}: could not fetch price")
            continue

        reason = level_hit(pos, price)
        if not reason:
            continue
        past_level += 1

        pid = pos.get("id") or pos.get("name", "unknown")
        if now < next_alert_at.get(pid, 0):
            continue
        # Positions of the bot's own wallet get a sell button (Telegram only).
        buttons = (telegram_actions.sell_button(pos["id"])
                   if trading.enabled() and _in_trading_wallet(pos) else None)
        sent = alerts.send_alert(format_alert(pos, price, reason), buttons)
        next_alert_at[pid] = now + (ALERT_COOLDOWN if sent else RETRY_AFTER_FAILURE)
        logger.info(f"{reason} alert for {pos['name']} at {price}¢: "
                    f"{'sent' if sent else 'not sent'}")

    STATE.update(last_check_at=_utc_now(), positions=len(positions),
                 past_level=past_level, source=source, error=error)
    logger.info(f"Checked {len(positions)} position(s) from {source}, "
                f"{past_level} at or past a level"
                + (f" (wallet error: {error})" if error else ""))


def main():
    channels = alerts.configured_channels()
    logger.info(f"Polymarket monitor starting: every {CHECK_INTERVAL}s, "
                f"cooldown {ALERT_COOLDOWN}s, channels: {', '.join(channels) or 'none'}")
    STATE.update(running=True, started_at=_utc_now())

    if os.environ.get("STARTUP_ALERT", "1") != "0":
        alerts.send_alert(STARTUP_MESSAGE)

    next_alert_at: dict[str, float] = {}   # position id → earliest next alert
    try:
        while True:
            try:
                check_once(next_alert_at)
            except Exception as e:
                # Keep the thread alive: one bad pass must not end the monitoring.
                STATE["error"] = str(e)
                logger.exception("Monitor check failed")
            time.sleep(CHECK_INTERVAL)
    finally:
        STATE["running"] = False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
