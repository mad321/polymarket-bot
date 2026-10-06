"""
Position discovery
==================
Pulls the wallets' open positions straight from Polymarket's public Data API
(v2), so new trades show up without editing config.json.

- WALLET_ADDRESS must be the Polymarket *proxy* wallet (the deposit address
  shown on your Polymarket profile), not the signer/EOA key address. Several
  wallets can be comma-separated; the bot's TRADING_WALLET is always added.
- config.json is now optional overrides, matched by market slug:
  name (Arabic label), stop_loss, take_profit, notes, closed (hide).
  They skip the bot's TRADING_WALLET unless an entry names it in "wallet".
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


def fetch_wallet_positions(address: str, max_pages: int = 10):
    """
    Raw open positions for a wallet from Data API v2 (v1 is retired on
    October 24, 2026). Follows the cursor pagination. Raises on errors.
    """
    rows, cursor = [], None
    for _ in range(max_pages):
        params = {"user": address, "status": "OPEN", "limit": 100}
        if cursor:
            params["cursor"] = cursor
        r = requests.get(f"{DATA_API}/v2/positions", params=params, timeout=15)
        r.raise_for_status()
        body = r.json()
        rows.extend(body.get("data") or [])
        cursor = (body.get("pagination") or {}).get("next_cursor")
        if not cursor:
            break
    return rows


def _from_wallet(raw, overrides, wallet=""):
    out = []
    for p in raw:
        # Resolved markets (redeemable) and dust are not "open" positions
        if p.get("redeemable") or float(p.get("current_size") or 0) < MIN_SHARES:
            continue
        slug = p.get("slug", "")
        ov = overrides.get(slug, {})
        if ov.get("closed"):
            continue

        buy = round(float(p.get("avg_price") or 0) * 100, 1)
        cur = p.get("current_price")
        cur = round(float(cur) * 100, 1) if cur is not None else None
        stop, tp = _default_levels(buy)
        title = p.get("title", slug)
        outcome = p.get("outcome", "")

        out.append({
            "id": p.get("token_id") or slug,
            "wallet": wallet,
            "name": ov.get("name") or (f"{title} — {outcome}" if outcome else title),
            "title": title,
            "outcome": outcome,
            "slug": slug,
            "url": f"https://polymarket.com/event/{p.get('event_slug') or slug}",
            "shares": round(float(p.get("current_size") or 0), 2),
            "buy_price": buy,
            "current_price": cur,
            "stop_loss": ov.get("stop_loss", stop),
            "take_profit": ov.get("take_profit", tp),
            "pnl": round(float(p["percent_pnl"]), 1) if p.get("percent_pnl") is not None else None,
            "pnl_usd": round(float(p["unrealized_pnl"]), 2) if p.get("unrealized_pnl") is not None else None,
            "end_date": p.get("end_date"),
            "notes": ov.get("notes", ""),
        })
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


def watched_wallets():
    """
    Wallets to watch: WALLET_ADDRESS (comma-separated for several) plus the
    bot's trading wallet (TRADING_WALLET), lowercased and without duplicates.
    """
    raw = f"{os.environ.get('WALLET_ADDRESS') or ''},{os.environ.get('TRADING_WALLET') or ''}"
    wallets = []
    for address in raw.split(","):
        address = address.strip().lower()
        if address and address not in wallets:
            wallets.append(address)
    return wallets


def overrides_for(config, wallet):
    """
    config.json overrides for one wallet, by slug. An entry with a "wallet"
    field applies to that wallet only. An entry without one applies to every
    wallet except the bot's TRADING_WALLET: those entries were written for
    earlier trades, and a new bot trade in the same market must get levels
    from its own buy price, not someone else's stop.
    """
    trading = (os.environ.get("TRADING_WALLET") or "").strip().lower()
    out = {}
    for c in config:
        if not c.get("slug"):
            continue
        scope = (c.get("wallet") or "").strip().lower()
        if scope == wallet or (not scope and wallet != trading):
            out[c["slug"]] = c
    return out


def load_positions():
    """
    Returns (positions, source, error).
    source is "wallet" or "config"; error is a message when a wallet lookup
    failed. If every wallet failed, falls back to config.json.
    """
    config = load_config()
    wallets = watched_wallets()
    if not wallets:
        return _from_config(config), "config", None

    positions, errors = [], []
    for wallet in wallets:
        try:
            positions += _from_wallet(fetch_wallet_positions(wallet), overrides_for(config, wallet), wallet)
        except Exception as e:
            logger.error(f"تعذر جلب صفقات المحفظة {wallet[:8]}…: {e}")
            errors.append(str(e))

    error = "; ".join(errors) or None
    if len(errors) == len(wallets):
        return _from_config(config), "config", error
    positions.sort(key=lambda x: x.get("end_date") or "")
    return positions, "wallet", error
