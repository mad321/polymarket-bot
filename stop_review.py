"""
Stop-loss / take-profit review ("what if")
==========================================
Do the alert levels help? For the first stop-loss or take-profit alert of each
position it records what selling every share right then would have paid: down
the real bids, minus the taker fee. Once the market resolves it compares that
with holding to the end, and reports which was better. After 20 to 30 alerts
the totals say whether the levels protect you or cost you.

It only records and reports: it never sells, and does not change the alerts.

The monitor thread calls record(); the ledger loop in paper_trading.py merges
the records into the ledger it keeps pinned in Telegram (the bot can find only
one pinned message, so both share that file) and settles them.
"""

import json
import logging
import threading
from datetime import datetime, timezone

import requests

import trading

logger = logging.getLogger(__name__)

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
KINDS = {"stop_loss": "وقف الخسارة", "take_profit": "الهدف"}

ACTIVE = False   # set by the ledger loop: records are kept only while it runs
_lock = threading.Lock()
_pending = []    # recorded by the monitor thread, merged by the ledger loop
_seen = set()    # keys already recorded, so each alert is priced once


def _key(pos, reason):
    return f"{pos.get('wallet', '')}:{pos.get('id')}:{reason}"


def find_market(token_id):
    """The Gamma market holding this token: id, question, fee rate, or None."""
    for closed in ("false", "true"):
        r = requests.get(f"{GAMMA}/markets", params={"clob_token_ids": token_id, "closed": closed}, timeout=15)
        r.raise_for_status()
        markets = r.json()
        if markets:
            m = markets[0]
            rate = (m.get("feeSchedule") or {}).get("rate", 0) if m.get("feesEnabled") else 0
            return {"market_id": str(m["id"]), "question": m.get("question"), "fee_rate": float(rate)}
    return None


def simulate_sell(bids, shares, fee_rate):
    """Sells `shares` down the bids, best first. Returns shares sold and
    dollars received after the taker fee."""
    sold = proceeds = 0.0
    for price, size in sorted(((float(b["price"]), float(b["size"])) for b in bids), reverse=True):
        if sold >= shares:
            break
        if not 0 < price < 1:
            continue
        take = min(size, shares - sold)
        sold += take
        proceeds += take * price - take * fee_rate * price * (1 - price)
    return round(sold, 2), round(proceeds, 4)


def record(pos, reason, price):
    """Called by the monitor when a position is at or past a level."""
    if not ACTIVE or not str(pos.get("id") or "").isdigit():
        return  # no ledger to keep it in, or not a wallet position (no token id)
    key = _key(pos, reason)
    with _lock:
        if key in _seen:
            return
        _seen.add(key)
    try:
        market = find_market(pos["id"])
        if market is None:
            raise ValueError("market not found")
        r = requests.get(f"{CLOB}/book", params={"token_id": pos["id"]}, timeout=15)
        r.raise_for_status()
        bids = r.json().get("bids") or []
    except Exception as e:
        logger.warning(f"[REVIEW] pricing the {reason} alert of {pos.get('name')}: {e}")
        with _lock:
            _seen.discard(key)  # try again on the next check
        return
    shares = float(pos.get("shares") or 0)
    sold, proceeds = simulate_sell(bids, shares, market["fee_rate"])
    best_bid = max((float(b["price"]) for b in bids), default=None)
    in_bot_wallet = bool(trading.trading_wallet()) and (pos.get("wallet") or "").lower() == trading.trading_wallet()
    entry = {
        "key": key, "kind": reason, "token_id": str(pos["id"]), "market_id": market["market_id"],
        "name": pos.get("name"), "wallet": "bot" if in_bot_wallet else "main",
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "price": price, "best_bid": best_bid, "buy_price": pos.get("buy_price"),
        "level": pos.get(reason), "shares": shares, "sold_shares": sold, "proceeds": proceeds,
    }
    with _lock:
        _pending.append(entry)
    logger.info(f"[REVIEW] recorded the {reason} alert of {pos.get('name')}: sell now ${proceeds:.2f}")


def _section(ledger):
    return ledger.setdefault("level_alerts", {"open": [], "closed": []})


def merge(ledger):
    """Moves new records into the ledger (under the ledger lock). True if any."""
    with _lock:
        pending, _pending[:] = list(_pending), []
    section = _section(ledger)
    known = {a["key"] for a in section["open"] + section["closed"]}
    added = [e for e in pending if e["key"] not in known]
    section["open"].extend(added)
    with _lock:
        _seen.update(known, (e["key"] for e in added))
    return bool(added)


def fetch_payout(market_id, token_id):
    """What one share of the token paid at resolution (1, 0 or 0.5), or None."""
    r = requests.get(f"{GAMMA}/markets/{market_id}", timeout=15)
    r.raise_for_status()
    m = r.json()
    if not m.get("closed"):
        return None
    try:
        tokens = [str(t) for t in json.loads(m["clobTokenIds"])]
        prices = [float(p) for p in json.loads(m["outcomePrices"])]
        payout = prices[tokens.index(str(token_id))]
    except (KeyError, ValueError, TypeError):
        return None
    if not all(p in (0, 0.5, 1) for p in prices) or abs(sum(prices) - 1) > 1e-9:
        return None  # closed but not settled yet
    return payout


def open_entries(ledger):
    return [(e["market_id"], e["token_id"]) for e in _section(ledger)["open"]]


def _usd(value):
    return f"${value:.2f}"


def settle(ledger, payouts, now_iso):
    """Settles the records whose market resolved. Returns messages."""
    section, messages = _section(ledger), []
    for e in list(section["open"]):
        payout = payouts.get((e["market_id"], e["token_id"]))
        if payout is None:
            continue
        held = e["shares"] * payout
        sold = e["proceeds"] + (e["shares"] - e["sold_shares"]) * payout  # unsold shares stay held
        e.update(payout=payout, held_value=round(held, 4), sold_value=round(sold, 4), closed_at=now_iso)
        section["open"].remove(e)
        section["closed"].append(e)
        title = f"📊 مراجعة تنبيه {KINDS[e['kind']]}: {e['name']}"
        if e["best_bid"] is None:
            messages.append(f"{title}\nلم يكن هناك مشترون عند التنبيه، والانتظار حتى الحسم أعطى {_usd(held)}")
            continue
        diff = held - sold
        verdict = ("لا فرق يُذكر" if abs(diff) < 0.01
                   else f"{'الانتظار' if diff > 0 else 'البيع'} كان أفضل بـ {_usd(abs(diff))}")
        messages.append(f"{title}\n"
                        f"لو بعت عند التنبيه (أفضل سعر شراء {e['best_bid'] * 100:.1f}¢): {_usd(sold)}\n"
                        f"الانتظار حتى الحسم: {_usd(held)}\n"
                        f"← {verdict}")
    return messages


def summary_lines(ledger):
    section = _section(ledger)
    lines = []
    for kind, label in KINDS.items():
        done = [e for e in section["closed"] if e["kind"] == kind]
        if not done:
            continue
        sold = sum(e["sold_value"] for e in done)
        held = sum(e["held_value"] for e in done)
        diff = held - sold
        verdict = ("لا فرق يُذكر" if abs(diff) < 0.01
                   else f"{'الانتظار' if diff > 0 else 'البيع'} أفضل بـ {_usd(abs(diff))}")
        lines.append(f"مراجعة تنبيهات {label} ({len(done)} حُسمت): لو بعت عند كل تنبيه {_usd(sold)}، "
                     f"ولو انتظرت {_usd(held)} ← {verdict}")
    if section["open"]:
        lines.append(f"تنبيهات تنتظر حسم السوق للمراجعة: {len(section['open'])}")
    return lines
