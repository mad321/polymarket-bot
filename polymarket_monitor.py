"""
Polymarket Price Monitor - WhatsApp Alert Bot
=============================================
Monitors open Polymarket positions every 30 seconds.
Positions are discovered from the wallet (WALLET_ADDRESS) — see positions.py.
Sends WhatsApp alert when price drops below stop-loss threshold.

Deploy on Render as a Background Worker.
Set environment variables: WHATSAPP_TOKEN, PHONE_NUMBER_ID, RECIPIENT_PHONE
"""

import os
import json
import time
import requests
from datetime import datetime

from positions import load_positions

# ─── CONFIG ──────────────────────────────────────────────────────────────────

POLYMARKET_API = "https://clob.polymarket.com"
GAMMA_API      = "https://gamma-api.polymarket.com"

WHATSAPP_TOKEN    = os.environ.get("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID   = os.environ.get("PHONE_NUMBER_ID", "")
RECIPIENT_PHONE   = os.environ.get("RECIPIENT_PHONE", "")   # e.g. "966501234567"

CONFIG_FILE   = "config.json"
CHECK_INTERVAL = 30   # seconds between price checks
ALERT_COOLDOWN = 300  # seconds before re-alerting same position (5 min)

# ─── HELPERS ─────────────────────────────────────────────────────────────────

def load_config():
    """Load positions config from JSON file."""
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def get_price_by_slug(slug: str) -> float | None:
    """
    Fetch current YES price for a market by its slug.
    Returns price as integer (0-100 cents) or None on error.
    """
    try:
        url = f"{GAMMA_API}/markets?slug={slug}"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        if not data:
            return None
        market = data[0]
        prices = market.get("outcomePrices", [])
        # outcomePrices = ["0.72", "0.28"] → YES is index 0
        if prices:
            return round(float(prices[0]) * 100, 1)   # convert to cents
    except Exception as e:
        print(f"[ERROR] fetching {slug}: {e}")
    return None

def get_price_by_token_id(token_id: str) -> float | None:
    """
    Fetch price directly by CLOB token ID.
    Returns price as integer (0-100 cents) or None on error.
    """
    try:
        url = f"{POLYMARKET_API}/price?token_id={token_id}&side=sell"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        price = data.get("price")
        if price is not None:
            return round(float(price) * 100, 1)
    except Exception as e:
        print(f"[ERROR] fetching token {token_id[:12]}...: {e}")
    return None

def get_price(position: dict) -> float | None:
    """Auto-detect how to fetch price based on config fields."""
    if "token_id" in position:
        return get_price_by_token_id(position["token_id"])
    elif "slug" in position:
        return get_price_by_slug(position["slug"])
    return None

def send_whatsapp(message: str):
    """Send WhatsApp message via Meta Cloud API."""
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID or not RECIPIENT_PHONE:
        print(f"[WHATSAPP NOT CONFIGURED] Would send: {message}")
        return False
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": RECIPIENT_PHONE,
        "type": "text",
        "text": {"body": message}
    }
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        r.raise_for_status()
        print(f"[WHATSAPP SENT] {message[:60]}...")
        return True
    except Exception as e:
        print(f"[WHATSAPP ERROR] {e}")
        return False

def format_alert(pos: dict, price: float, reason: str) -> str:
    """Format alert message in Arabic."""
    emoji = "🔴" if reason == "stop_loss" else "🟢"
    action = "بيع فوري - وقف الخسارة" if reason == "stop_loss" else "خذ الأرباح"
    return (
        f"{emoji} تنبيه بوليماركت\n"
        f"المباراة: {pos['name']}\n"
        f"السعر الحالي: {price}¢\n"
        f"الحد: {pos['stop_loss'] if reason == 'stop_loss' else pos['take_profit']}¢\n"
        f"الإجراء: {action}\n"
        f"الأسهم: {pos['shares']}\n"
        f"الوقت: {datetime.now().strftime('%H:%M:%S')}"
    )

# ─── MAIN LOOP ────────────────────────────────────────────────────────────────

def main():
    print("=" * 50)
    print("Polymarket Monitor Bot - Starting")
    print(f"Check interval: {CHECK_INTERVAL}s | Alert cooldown: {ALERT_COOLDOWN}s")
    print("=" * 50)

    last_alert_time: dict[str, float] = {}   # position_id → timestamp

    while True:
        try:
            active, source, error = load_positions()
        except Exception as e:
            print(f"[ERROR] loading positions: {e}")
            time.sleep(60)
            continue

        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Checking {len(active)} position(s) from {source}..."
              + (f" (wallet error: {error})" if error else ""))

        for pos in active:
            pid   = pos.get("id", pos.get("name", "unknown"))
            price = pos.get("current_price")
            if price is None:
                price = get_price(pos)

            if price is None:
                print(f"  ⚠️  {pos['name']}: could not fetch price")
                continue

            print(f"  {pos['name']}: {price}¢  (stop: {pos.get('stop_loss','—')}¢  tp: {pos.get('take_profit','—')}¢)")

            # Cooldown check
            now = time.time()
            last = last_alert_time.get(pid, 0)
            if now - last < ALERT_COOLDOWN:
                continue

            # Stop-loss alert
            stop = pos.get("stop_loss")
            if stop and price <= stop:
                msg = format_alert(pos, price, "stop_loss")
                if send_whatsapp(msg):
                    last_alert_time[pid] = now

            # Take-profit alert
            tp = pos.get("take_profit")
            if tp and price >= tp:
                msg = format_alert(pos, price, "take_profit")
                if send_whatsapp(msg):
                    last_alert_time[pid] = now

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
