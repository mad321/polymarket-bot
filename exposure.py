"""
Position size alert
===================
A binary bet can lose everything in it, so the size of a position is its real
stop-loss. This warns when one event holds more than EXPOSURE_ALERT_PCT
(default 5%) of the trading capital. All markets of an event, across the
watched wallets, count together: they usually win or lose together (the four
"Saudi Arabia military action against Yemen on September …" positions are one
bet, not four).

Capital = cash (pUSD, Polymarket's collateral token, read from Polygon with a
public RPC call: no key) + the value of the open positions at their current
price. It only alerts: nothing is sold.

Settings:
  EXPOSURE_ALERT_PCT   limit per event in percent (default 5; 0 turns it off)
"""

import os
import time
import logging

import requests

import positions as positions_module

logger = logging.getLogger(__name__)

RPC_URL = "https://polygon.drpc.org"
PUSD = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"  # 6 decimals
CHECK_EVERY = 600         # seconds between capital checks
REALERT_AFTER = 24 * 3600  # an event still over the limit is repeated once a day

ACTIVE = False  # set by the monitor loop; direct check_once() calls (tests) skip it

# Read by /api/alerts/status. No balances: the page is public.
STATE = {"limit_pct": None, "last_check_at": None, "events_over_limit": 0, "error": None}

_last_check = 0.0
_last_alert = {}  # event -> time of its last alert


def limit_pct():
    try:
        return float(os.environ.get("EXPOSURE_ALERT_PCT") or 5)
    except ValueError:
        return 5.0


def wallet_cash(address):
    """pUSD balance of a wallet, in dollars."""
    data = "0x70a08231" + address.lower().removeprefix("0x").rjust(64, "0")  # balanceOf(address)
    r = requests.post(RPC_URL, json={"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                                     "params": [{"to": PUSD, "data": data}, "latest"]}, timeout=15)
    r.raise_for_status()
    body = r.json()
    if "result" not in body:
        raise ValueError(f"RPC error: {body.get('error')}")
    return int(body["result"], 16) / 1e6


def value(pos):
    return float(pos.get("shares") or 0) * float(pos.get("current_price") or 0) / 100


def over_limit(positions, cash, pct):
    """Events above pct of capital: [(event, value, share, names)], biggest first."""
    capital = cash + sum(value(p) for p in positions)
    if capital <= 0:
        return capital, []
    events = {}
    for p in positions:
        e = events.setdefault(p.get("event") or p.get("slug") or p.get("id"), {"value": 0.0, "names": []})
        e["value"] += value(p)
        e["names"].append(p.get("title") or p.get("name"))
    out = [(event, e["value"], e["value"] / capital * 100, e["names"])
           for event, e in events.items() if e["value"] / capital * 100 > pct]
    return capital, sorted(out, key=lambda x: -x[1])


def format_alert(items, capital, cash, pct):
    lines = [
        "⚖️ تنبيه حجم الصفقة",
        f"رأس مالك في بوليماركت: ${capital:.2f} (نقد ${cash:.2f} + صفقات ${capital - cash:.2f})",
        f"الحد: {pct:g}% = ${capital * pct / 100:.2f} للحدث الواحد. تجاوزه:",
    ]
    for _, val, share, names in items:
        others = len(names) - 1
        more = ("" if others == 0 else " وسوق أخرى في نفس الحدث" if others == 1
                else f" و{others} أسواق أخرى في نفس الحدث")
        lines.append(f"• {names[0]}{more}: ${val:.2f} ({share:.1f}%)")
    lines.append("الأسواق في نفس الحدث تُحسب معاً لأنها تربح أو تخسر معاً غالباً. "
                 "القيمة بالسعر الحالي، والبيع الفعلي قد يكون أقل. هذا تنبيه فقط: البوت لا يبيع شيئاً.")
    return "\n".join(lines)


def check(positions, send, now=None):
    """Every CHECK_EVERY seconds: alerts the events over the limit (each at
    most once a day). `send` delivers the message; returns True if it did."""
    global _last_check
    pct = limit_pct()
    now = now or time.time()
    if not ACTIVE or pct <= 0 or now - _last_check < CHECK_EVERY:
        return False
    _last_check = now
    STATE["limit_pct"] = pct
    try:
        cash = sum(wallet_cash(w) for w in positions_module.watched_wallets())
    except Exception as e:
        STATE["error"] = f"{type(e).__name__}: {e}"[:300]
        logger.warning(f"[EXPOSURE] reading cash: {STATE['error']}")
        return False
    capital, items = over_limit(positions, cash, pct)
    STATE.update(last_check_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                 events_over_limit=len(items), error=None)
    due = [item for item in items if now - _last_alert.get(item[0], 0) >= REALERT_AFTER]
    if not due:
        return False
    if not send(format_alert(due, capital, cash, pct)):
        return False
    for item in due:
        _last_alert[item[0]] = now
    return True
