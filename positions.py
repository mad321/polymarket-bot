"""
Position discovery
==================
Pulls the wallet's open positions straight from Polymarket's public Data API,
so new trades show up without editing config.json.

- WALLET_ADDRESS must be the Polymarket *proxy* wallet (the deposit address
  shown on your Polymarket profile), not the signer/EOA key address.
- config.json is now optional overrides, matched by market slug:
  name (Arabic label), stop_loss, take_profit, notes, closed (hide).
- Positions without overrides get stop-loss / take-profit relative to the
  buy price: STOP_LOSS_PCT (default 30% below) and TAKE_PROFIT_PCT
  (default 50% above, capped at 99¢).
- If WALLET_ADDRESS is not set, falls back to the old config.json-only mode.
"""

import os
import json
import logging
import requests

logger = logging.getLogger(__name__)

DATA_API = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"
CONFIG_FILE = "config.json"

STOP_LOSS_PCT = float(os.environ.get("STOP_LOSS_PCT", 30))
TAKE_PROFIT_PCT = float(os.environ.get("TAKE_PROFIT_PCT", 50))
MIN_SHARES = float(os.environ.get("MIN_SHARES", 1))


def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []


def get_price_by_slug(slug: str):
    """Current YES price (cents) for a market slug, or None."""
    try:
        r = requests.get(f"{GAMMA_API}/markets", params={"slug": slug}, timeout=10)
        r.raise_for_status()
        data = r.json()
        if not data:
            return None
        prices = data[0].get("outcomePrices", [])
        if isinstance(prices, str):
            prices = json.loads(prices)
        if prices:
            return round(float(prices[0]) * 100, 1)
    except Exception as e:
        logger.error(f"خطأ في جلب سعر {slug}: {e}")
    return None


def _default_levels(buy_price):
    stop = round(buy_price * (1 - STOP_LOSS_PCT / 100), 1)
    tp = round(min(99, buy_price * (1 + TAKE_PROFIT_PCT / 100)), 1)
    return stop, tp


def fetch_wallet_positions(address: str):
    """Raw open positions for a proxy wallet. Raises on network/API errors."""
    r = requests.get(
        f"{DATA_API}/positions",
        params={"user": address, "sizeThreshold": MIN_SHARES, "limit": 500},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def _from_wallet(raw, overrides):
    out = []
    for p in raw:
        # Resolved markets (redeemable) and dust are not "open" positions
        if p.get("redeemable") or float(p.get("size") or 0) < MIN_SHARES:
            continue
        slug = p.get("slug", "")
        ov = overrides.get(slug, {})
        if ov.get("closed"):
            continue

        buy = round(float(p.get("avgPrice") or 0) * 100, 1)
        cur = p.get("curPrice")
        cur = round(float(cur) * 100, 1) if cur is not None else None
        stop, tp = _default_levels(buy)
        title = p.get("title", slug)
        outcome = p.get("outcome", "")

        out.append({
            "id": p.get("asset") or slug,
            "name": ov.get("name") or (f"{title} — {outcome}" if outcome else title),
            "title": title,
            "outcome": outcome,
            "slug": slug,
            "url": f"https://polymarket.com/event/{p.get('eventSlug') or slug}",
            "shares": round(float(p.get("size") or 0), 2),
            "buy_price": buy,
            "current_price": cur,
            "stop_loss": ov.get("stop_loss", stop),
            "take_profit": ov.get("take_profit", tp),
            "pnl": round(float(p["percentPnl"]), 1) if p.get("percentPnl") is not None else None,
            "pnl_usd": round(float(p["cashPnl"]), 2) if p.get("cashPnl") is not None else None,
            "end_date": p.get("endDate"),
            "notes": ov.get("notes", ""),
        })
    out.sort(key=lambda x: x.get("end_date") or "")
    return out


def _from_config(config):
    out = []
    for pos in config:
        if pos.get("closed"):
            continue
        slug = pos.get("slug", "")
        buy = pos.get("buy_price", 0)
        cur = get_price_by_slug(slug) if slug else None
        pnl = pnl_usd = None
        if cur is not None and buy:
            pnl = round((cur - buy) / buy * 100, 1)
            pnl_usd = round(pos.get("shares", 0) * (cur - buy) / 100, 2)
        out.append({
            "id": pos.get("id") or slug,
            "name": pos.get("name", slug),
            "title": pos.get("name", slug),
            "outcome": "",
            "slug": slug,
            "url": f"https://polymarket.com/event/{slug}",
            "shares": pos.get("shares", 0),
            "buy_price": buy,
            "current_price": cur,
            "stop_loss": pos.get("stop_loss", 0),
            "take_profit": pos.get("take_profit", 100),
            "pnl": pnl,
            "pnl_usd": pnl_usd,
            "end_date": None,
            "notes": pos.get("notes", ""),
        })
    return out


def load_positions():
    """
    Returns (positions, source, error).
    source is "wallet" or "config"; error is a message when the wallet
    lookup failed and we fell back to config.json.
    """
    config = load_config()
    address = (os.environ.get("WALLET_ADDRESS") or "").strip()
    if address:
        try:
            raw = fetch_wallet_positions(address)
            overrides = {c["slug"]: c for c in config if c.get("slug")}
            return _from_wallet(raw, overrides), "wallet", None
        except Exception as e:
            logger.error(f"تعذر جلب صفقات المحفظة: {e}")
            return _from_config(config), "config", str(e)
    return _from_config(config), "config", None
