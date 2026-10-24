"""
The 70-match trial (owner, 2026-10-24)
=====================================
No real buying or selling until a strategy is chosen: the next TARGET
matches of the watched leagues with a team priced 55–72¢ (volume ≥ $15,000)
15 minutes before kickoff are traded on paper, $25 each, and every candidate
way of trading is scored on the same matches:

  hold        buy at the asks (taker fee), hold to the end        (strategy 3.1)
  maker       buy at the best bid with a limit order, no fee, hold
              (optimistic: assumes the order fills)
  pm20        buy at the asks, sell at +20% (limit) or -20% (bids) (strategy 3.0)
  edge        "hold", only where the bookmakers' chance beats the
              Polymarket cost by EDGE_MIN (needs ODDS_API_KEY)
  no_edge     "hold" on the rest, for comparison with "edge"

Since the pre-match model found no edge in the price alone
(research/pre_match_model), the open questions are the exits, the fees, and
whether the bookmakers know more than Polymarket.

While the trial runs, the buy signals and the morning list stay off (the
owner buys nothing). A short progress line comes each morning; the
comparison when the TARGET matches are settled.

Settings:
  TRIAL=0   turn it off
"""

import os
import math
from datetime import timedelta

import match_strategy as ms
import odds
import stop_review

TARGET = 70
STAKE = 25.0
ENTRY_RANGE = (0.55, 0.72)
MIN_VOLUME = 15_000
EDGE_MIN = 0.02
VARIANTS = {"hold": "الاحتفاظ حتى النهاية (3.1)", "maker": "أمر محدد بلا رسوم + احتفاظ",
            "pm20": "بيع عند +20% أو −20% (3.0)", "edge": "فقط حيث مكاتب المراهنات تعطي أفضلية",
            "no_edge": "حيث لا أفضلية"}

STATE = {"entered": 0, "settled": 0, "done": False}


def enabled():
    return (os.environ.get("TRIAL") or "").strip() != "0"


def section(ledger):
    return ledger.setdefault("trial", {"open": [], "closed": [], "seen": [], "digest_day": None,
                                       "final_sent": False})


def running(ledger):
    """True until the comparison of the TARGET matches has been sent."""
    return enabled() and not section(ledger).get("final_sent")


def full(sec):
    return len(sec["open"]) + len(sec["closed"]) >= TARGET


def plan(ledger, now):
    sec = section(ledger)
    live = {t["slug"]: t["league"] for t in sec["open"] if not t.get("ended")}
    settle = []
    for t in sec["open"]:
        last = ms._settle_checked.get(t["id"])
        if t.get("ended") and (last is None or now - last >= ms.SETTLE_EVERY):
            settle.append((t["id"], t["market_id"], t["token_id"]))
    entered = set(sec["seen"]) if not full(sec) else {g for g in ms._schedule}
    return {"live": live, "settle": settle, "entered": entered}


def enter(sec, game, books, odds_by_slug, now):
    from paper_trading import simulate_buy  # imported here: paper_trading imports this module
    if full(sec) or game["slug"] in sec["seen"]:
        return None
    if game.get("volume", 0) < MIN_VOLUME:
        return None  # may still grow before kickoff
    for side, s in game["sides"].items():
        book = books.get(s["token_id"])
        if not book:
            continue
        fill = simulate_buy(book.get("asks") or [], STAKE, s["fee_rate"], s["min_size"])
        if not fill:
            continue
        price = fill["cost"] / fill["shares"]
        if not ENTRY_RANGE[0] <= price <= ENTRY_RANGE[1]:
            continue
        bids = [float(b["price"]) for b in book.get("bids") or []]
        chances, source = odds_by_slug.get(game["slug"], (None, None))
        chance = (chances or {}).get(side)
        cost_per_share = (fill["cost"] + fill["fee"]) / fill["shares"]
        trade = {"id": f"trial:{game['slug']}:{side}", "slug": game["slug"], "league": game["league"],
                 "title": game["title"], "team": s["team"], "side": side, "market_id": s["market_id"],
                 "token_id": s["token_id"], "fee_rate": s["fee_rate"], "start": ms._iso(game["start"]),
                 "entry_at": ms._iso(now), "entry_price": round(price, 4), "bid": max(bids) if bids else None,
                 "volume": game.get("volume", 0), "chance": chance, "odds_source": source,
                 "edge": None if chance is None else round(chance - cost_per_share, 4),
                 "target": round(min(price * 1.2, 0.99), 4), "stop": round(price * 0.8, 4), **fill}
        sec["seen"].append(game["slug"])
        sec["open"].append(trade)
        return trade
    return None


def missed(sec, slug):
    if slug not in sec["seen"]:
        sec["seen"].append(slug)


def step(trade, game, book, now):
    """The +20% / -20% exits of the pm20 variant (as in strict_strategy.step)."""
    if "exit" in trade:
        return
    bids = book.get("bids") or []
    best = max((float(b["price"]) for b in bids), default=None)
    if best is not None and best >= trade["target"] - 1e-9:
        trade["exit"] = {"rule": "target", "at": ms._iso(now), "sold_shares": trade["shares"],
                         "proceeds": round(trade["shares"] * trade["target"], 4)}
        return
    mid = ms.mid_price(book)
    if not trade.get("stop_pending") and (mid is None or mid > trade["stop"] + 1e-9):
        return
    sold, proceeds = stop_review.simulate_sell(bids, trade["shares"], trade["fee_rate"])
    if sold <= 0:
        trade["stop_pending"] = True
        return
    trade.pop("stop_pending", None)
    trade["exit"] = {"rule": "stop", "at": ms._iso(now), "minute": ms.minute(game), "sold_shares": sold,
                     "proceeds": proceeds}


def results(trade, payout):
    """Each variant's P&L on this match (None where the variant did not trade)."""
    paid = trade["cost"] + trade["fee"]
    hold = trade["shares"] * payout - paid
    ex = trade.get("exit")
    pm20 = (ex["proceeds"] + (trade["shares"] - ex["sold_shares"]) * payout - paid) if ex else hold
    maker = STAKE * (payout / trade["bid"] - 1) if trade.get("bid") else None
    edge = trade.get("edge")
    return {"hold": round(hold, 4), "maker": None if maker is None else round(maker, 4), "pm20": round(pm20, 4),
            "edge": round(hold, 4) if edge is not None and edge >= EDGE_MIN else None,
            "no_edge": round(hold, 4) if edge is not None and edge < EDGE_MIN else None}


def settle(sec, trade, payout, now):
    trade.update(payout=payout, results=results(trade, payout), closed_at=ms._iso(now))
    sec["open"].remove(trade)
    sec["closed"].append(trade)


def apply(ledger, data, now, tz):
    """One round (under the ledger lock). Returns messages."""
    sec = section(ledger)
    if sec.get("final_sent"):
        STATE["done"] = True
        return []
    games, books = data["games"], data["books"]
    for slug in data.get("candidates", []):
        if slug in games:
            enter(sec, games[slug], books, data.get("odds") or {}, now)
    for slug in data.get("started", []):
        if not full(sec):
            missed(sec, slug)
    for trade in list(sec["open"]):
        if trade["id"] in data["payouts"]:
            settle(sec, trade, data["payouts"][trade["id"]], now)
            continue
        if trade.get("ended"):
            continue
        if now - ms._parse_time(trade["start"]) > timedelta(hours=4):
            trade["ended"] = True
            continue
        game = games.get(trade["slug"])
        if game is None:
            continue
        if ms.finished(game):
            trade["ended"] = True
            continue
        step(trade, game, books.get(trade["token_id"]) or {}, now)
    STATE.update(entered=len(sec["open"]) + len(sec["closed"]), settled=len(sec["closed"]))
    STATE["done"] = bool(sec.get("final_sent"))
    if len(sec["closed"]) >= TARGET:
        sec["final_sent"] = STATE["done"] = True
        return [final_text(sec)]
    return progress(sec, now, tz)

# ─── REPORTS ─────────────────────────────────────────────────────────────────

def table(sec):
    """Per variant: matches, wins, net, return per trade and its 95% range."""
    out = []
    for name, label in VARIANTS.items():
        pnl = [t["results"][name] for t in sec["closed"] if t["results"].get(name) is not None]
        n = len(pnl)
        mean = sum(pnl) / n if n else 0.0
        sd = math.sqrt(sum((x - mean) ** 2 for x in pnl) / (n - 1)) if n > 1 else 0.0
        out.append({"name": name, "label": label, "n": n, "wins": sum(x > 0 for x in pnl), "net": sum(pnl),
                    "roi": mean / STAKE if n else None, "range": 1.96 * sd / math.sqrt(n) / STAKE if n > 1 else None})
    return out


def _usd(v):
    return f"‎{'-' if v < -0.004 else '+'}${abs(v):.2f}"


def final_text(sec):
    lines = [f"🏁 انتهت تجربة {TARGET} مباراة (على الورق، $25 لكل مباراة). المقارنة على نفس المباريات:"]
    for row in sorted(table(sec), key=lambda r: -(r["roi"] or -9)):
        if row["n"]:
            lines.append(f"• {row['label']}: {row['n']} مباراة، ربح {row['wins']}، الصافي {_usd(row['net'])}، "
                         f"العائد ‎{row['roi'] * 100:+.1f}% للصفقة"
                         + (f" (المدى ±{row['range'] * 100:.1f}%)" if row["range"] is not None else ""))
    lines.append("الاستراتيجية التي يقع مداها كله فوق الصفر فقط هي التي تستحق المال. أرسل \"راجع الاستراتيجية\" لنقرر.")
    return "\n".join(lines)


def progress(sec, now, tz):
    local = now.astimezone(tz)
    today = local.strftime("%Y-%m-%d")
    if local.hour < ms.DIGEST_HOUR or sec.get("digest_day") == today:
        return []
    sec["digest_day"] = today
    entered = len(sec["open"]) + len(sec["closed"])
    if not entered:
        return []
    hold = next(r for r in table(sec) if r["name"] == "hold")
    return [f"🧪 تجربة {TARGET} مباراة: دخلت {entered}، حُسمت {len(sec['closed'])}. "
            f"لا شراء ولا بيع حقيقي حتى نهايتها."
            + (f" الاحتفاظ حتى الآن: {_usd(hold['net'])}." if hold["n"] else "")]


def dashboard(sec):
    return {"target": TARGET, "entered": len(sec.get("open", [])) + len(sec.get("closed", [])),
            "settled": len(sec.get("closed", [])), "rows": table(sec) if sec.get("closed") else [],
            "done": bool(sec.get("final_sent")), "odds": odds.enabled()}
