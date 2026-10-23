"""
Trade journal: learning from every real trade
=============================================
After each real football trade closes ("Will <team> win?" Yes, in the watched
wallets), the bot records what happened and what it teaches:

  - the trade: league, team, whether it is on the elite list, average entry
    price, money in and out, return, and how it ended (held to the end, sold
    in profit, sold at a loss, deep loss below -30%);
  - what holding to the end would have paid (the market's resolution, read
    once it is settled): the question the paper tests keep raising;
  - the running statistics of every group the trade belongs to (entry price
    band, elite or not, league, how it ended): trades, win rate with its 95%
    range, net, and holding instead. A group is a "result" only from 30
    trades (CLAUDE.md rule 6); before that it is a "hypothesis".

A message goes to Telegram for each newly closed trade, and the groups show
on the private part of the dashboard. Nothing here changes a rule or places
an order: what the numbers say is for the owner (and the next Claude
session) to decide on, with LESSONS.md.

Source: Polymarket's public activity feed of each watched wallet (buys,
sells, redeems), from SINCE. The first run fills the journal quietly.

Settings:
  JOURNAL=0   turn it off
"""

import os
import json
import math
import logging
from datetime import datetime, timezone

import requests

import positions as positions_module

logger = logging.getLogger(__name__)

DATA_API = "https://data-api.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"
SINCE = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp())  # the current way of trading
CHECK_EVERY = 600       # seconds between reads of the activity feed
OUTCOME_EVERY = 1800    # seconds between resolution checks of a trade sold early
MIN_SAMPLE = 30
BREAK_EVEN = 0.57       # win rate at which ±20% exits break even after fees (LESSONS.md)
PRICE_BANDS = [(0, 0.55, "أقل من 55¢"), (0.55, 0.62, "55–62¢"), (0.62, 0.72, "62–72¢"), (0.72, 1.01, "72¢ فأكثر")]
ENDINGS = {"held": "حتى النهاية", "profit": "بيع بربح", "loss": "بيع بخسارة حتى −30%",
           "deep": "بيع بخسارة أسوأ من −30%"}

STATE = {"enabled": False, "last_check_at": None, "trades": 0, "error": None}

_last_check = 0.0
_outcome_checked = {}


def enabled():
    return (os.environ.get("JOURNAL") or "").strip() != "0"


def section(ledger):
    return ledger.setdefault("journal", {"trades": {}, "filled": False})


def _football(row):
    title = str(row.get("title") or "")
    return title.startswith("Will ") and " win on " in title and str(row.get("outcome") or "").lower() == "yes"

# ─── READING ─────────────────────────────────────────────────────────────────

def fetch_activity(wallet, since=SINCE, page=500, max_pages=20):
    rows = []
    for i in range(max_pages):
        r = requests.get(f"{DATA_API}/activity", params={"user": wallet, "limit": page, "offset": i * page},
                         timeout=20)
        r.raise_for_status()
        batch = r.json()
        rows += [x for x in batch if int(x.get("timestamp") or 0) >= since]
        if len(batch) < page or int(batch[-1].get("timestamp") or 0) < since:
            break
    return rows


def positions_from(rows, wallet):
    """Football Yes positions of one wallet, built from its activity."""
    out = {}
    for x in sorted(rows, key=lambda x: int(x.get("timestamp") or 0)):
        if x.get("type") not in ("TRADE", "REDEEM") or not _football(x) or not x.get("asset"):
            continue
        key = f"{wallet}:{x['asset']}"
        p = out.setdefault(key, {"wallet": wallet, "asset": str(x["asset"]), "title": x["title"],
                                 "event": x.get("eventSlug") or "", "bought": 0.0, "cost": 0.0,
                                 "sold": 0.0, "proceeds": 0.0, "redeemed": 0.0, "redeem_usd": 0.0,
                                 "first": int(x["timestamp"]), "last": 0})
        size, usd = float(x.get("size") or 0), float(x.get("usdcSize") or 0)
        if x["type"] == "TRADE" and x.get("side") == "BUY":
            p["bought"] += size
            p["cost"] += usd
        elif x["type"] == "TRADE" and x.get("side") == "SELL":
            p["sold"] += size
            p["proceeds"] += usd
        elif x["type"] == "REDEEM":
            p["redeemed"] += size
            p["redeem_usd"] += usd
        p["last"] = max(p["last"], int(x["timestamp"]))
    return {k: p for k, p in out.items() if p["bought"] > 0 and p["first"] >= SINCE}


def closed(p):
    return p["sold"] + p["redeemed"] >= p["bought"] * 0.98


def fetch_payout(asset):
    """What one share paid at resolution (1, 0, 0.5), or None while unsettled."""
    r = requests.get(f"{GAMMA}/markets", params={"clob_token_ids": asset, "closed": "true"}, timeout=15)
    r.raise_for_status()
    markets = r.json()
    if not markets:
        return None
    m = markets[0]
    try:
        tokens = [str(t) for t in json.loads(m["clobTokenIds"])]
        prices = [float(v) for v in json.loads(m["outcomePrices"])]
    except (KeyError, ValueError, TypeError):
        return None
    if not all(v in (0, 0.5, 1) for v in prices):
        return None
    return prices[tokens.index(str(asset))]


def due(now):
    return enabled() and now - _last_check >= CHECK_EVERY


def fetch(ledger_view, now):
    """Network reads, outside the ledger lock. `ledger_view` is the journal
    section as it was read under the lock. Returns {"positions", "payouts", "error"}."""
    global _last_check
    _last_check = now
    out = {"positions": {}, "payouts": {}, "error": None}
    try:
        for wallet in positions_module.watched_wallets():
            out["positions"].update(positions_from(fetch_activity(wallet), wallet))
        known = ledger_view.get("trades", {})
        for key, p in out["positions"].items():
            rec = known.get(key)
            if not closed(p) or (rec and rec.get("payout") is not None):
                continue
            if p["redeemed"] > 0 and p["sold"] == 0:
                out["payouts"][key] = 1.0 if p["redeem_usd"] > 0 else 0.0  # held to the end: the redeem says it
                continue
            if now - _outcome_checked.get(key, 0) < OUTCOME_EVERY:
                continue
            _outcome_checked[key] = now
            payout = fetch_payout(p["asset"])
            if payout is not None:
                out["payouts"][key] = payout
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"[:300]
        logger.warning(f"[JOURNAL] {out['error']}")
    STATE.update(last_check_at=datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds"),
                 error=out["error"])
    return out

# ─── LEARNING ────────────────────────────────────────────────────────────────

def record(p, payout):
    """A closed position as a journal entry."""
    import strict_strategy
    team = p["title"][len("Will "):p["title"].index(" win on ")]
    back = p["proceeds"] + p["redeem_usd"]
    pnl = back - p["cost"]
    ret = pnl / p["cost"] if p["cost"] else 0.0
    if p["sold"] < p["bought"] * 0.5:
        ending = "held"
    elif ret > 0:
        ending = "profit"
    elif ret > -0.30:
        ending = "loss"
    else:
        ending = "deep"
    rec = {"wallet": p["wallet"], "team": team, "title": p["title"], "league": p["event"].split("-")[0],
           "elite": strict_strategy.is_elite(team), "entry": round(p["cost"] / p["bought"], 4),
           "cost": round(p["cost"], 4), "back": round(back, 4), "pnl": round(pnl, 4), "ret": round(ret, 4),
           "ending": ending, "shares": round(p["bought"], 4),
           "closed_at": datetime.fromtimestamp(p["last"], timezone.utc).isoformat(timespec="seconds"),
           "payout": payout}
    if payout is not None:
        rec["hold_pnl"] = round(p["bought"] * payout - p["cost"], 4)
    return rec


def wilson(wins, n, z=1.96):
    """95% range of a win rate from n trades, as (low, high)."""
    if n == 0:
        return (0.0, 1.0)
    p = wins / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def band(entry):
    for low, high, name in PRICE_BANDS:
        if low <= entry < high:
            return name
    return PRICE_BANDS[-1][2]


def groups(rec):
    """The groups a trade is counted in: (dimension, name)."""
    return [("السعر", band(rec["entry"])), ("الفريق", "من قائمة النخبة" if rec["elite"] else "خارج القائمة"),
            ("الدوري", rec["league"]), ("النهاية", ENDINGS[rec["ending"]])]


def stats(trades):
    """Per group: n, wins, win rate range, net, and holding instead."""
    table = {}
    for rec in trades:
        for dim, name in groups(rec):
            g = table.setdefault((dim, name), {"dim": dim, "name": name, "n": 0, "wins": 0, "pnl": 0.0,
                                               "hold": 0.0, "hold_n": 0, "cost": 0.0})
            g["n"] += 1
            g["wins"] += rec["pnl"] > 0
            g["pnl"] += rec["pnl"]
            g["cost"] += rec["cost"]
            if rec.get("hold_pnl") is not None:
                g["hold"] += rec["hold_pnl"]
                g["hold_n"] += 1
    for g in table.values():
        low, high = wilson(g["wins"], g["n"])
        g.update(rate=g["wins"] / g["n"], low=low, high=high, ret=g["pnl"] / g["cost"] if g["cost"] else 0.0)
        g["verdict"] = verdict(g)
    order = {"السعر": 0, "الفريق": 1, "النهاية": 2, "الدوري": 3}
    return sorted(table.values(), key=lambda g: (order[g["dim"]], -g["n"]))


def verdict(g):
    if g["dim"] == "النهاية":
        return "—"  # the ending decides the win: compare it with holding instead
    if g["n"] < MIN_SAMPLE:
        return "فرضية"
    if g["low"] > BREAK_EVEN:
        return "يربح"
    if g["high"] < BREAK_EVEN:
        return "يخسر"
    return "غير محسوم"


def _usd(v):
    return f"‎{'-' if v < -0.004 else '+'}${abs(v):.2f}"


def message(rec, table):
    """What one closed trade adds to what we know."""
    lines = [f"📘 صفقة أُغلقت: {rec['team']} ({rec['league']})",
             f"دخلت بـ {rec['entry'] * 100:.0f}¢، والنتيجة {_usd(rec['pnl'])} (‎{rec['ret'] * 100:+.0f}%)، "
             f"{ENDINGS[rec['ending']]}."]
    if rec.get("hold_pnl") is not None and rec["ending"] != "held":
        diff = rec["pnl"] - rec["hold_pnl"]
        lines.append(f"لو احتفظت حتى النهاية: {_usd(rec['hold_pnl'])} → "
                     + ("البيع كان أفضل" if diff > 0.004 else "الاحتفاظ كان أفضل" if diff < -0.004 else "لا فرق")
                     + (f" بـ ${abs(diff):.2f}" if abs(diff) > 0.004 else ""))
    lines.append("ما تعلمناه حتى الآن في مجموعات هذه الصفقة:")
    mine = set(groups(rec))
    for g in table:
        if (g["dim"], g["name"]) in mine:
            lines.append(f"• {g['dim']} {g['name']}: {g['n']} صفقة، ربح {g['rate'] * 100:.0f}% "
                         f"(المدى {g['low'] * 100:.0f}–{g['high'] * 100:.0f}%)، الصافي {_usd(g['pnl'])} — {g['verdict']}")
    lines.append(f"المجموعة تصبح نتيجة من {MIN_SAMPLE} صفقة؛ التعادل حوالي {BREAK_EVEN * 100:.0f}% ربح.")
    return "\n".join(lines)


def apply(ledger, fetched, now):
    """Records newly closed trades (under the ledger lock). Returns messages;
    the first fill of the journal is silent."""
    if fetched is None:
        return []
    sec = section(ledger)
    trades = sec["trades"]
    new = []
    for key, p in fetched["positions"].items():
        payout = fetched["payouts"].get(key)
        rec_old = trades.get(key)
        if not closed(p):
            continue
        if rec_old is None:
            trades[key] = record(p, payout)
            new.append(key)
        elif rec_old.get("payout") is None and payout is not None:
            trades[key] = record(p, payout)
    STATE["trades"] = len(trades)
    if not sec["filled"]:
        sec["filled"] = True  # the first run: the history, not news
        return []
    table = stats(list(trades.values()))
    return [message(trades[k], table) for k in sorted(new, key=lambda k: trades[k]["closed_at"])]


def dashboard(ledger):
    """Groups and totals for the private part of the dashboard."""
    trades = list(section(ledger)["trades"].values())
    held = [t for t in trades if t.get("hold_pnl") is not None]
    return {"n": len(trades), "wins": sum(t["pnl"] > 0 for t in trades), "pnl": sum(t["pnl"] for t in trades),
            "cost": sum(t["cost"] for t in trades), "hold": sum(t["hold_pnl"] for t in held),
            "hold_pnl_same": sum(t["pnl"] for t in held), "hold_n": len(held), "groups": stats(trades)}
