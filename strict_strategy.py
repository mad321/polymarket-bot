"""
"Strict balance" 3.0 (الميزان الصارم): paper test
==================================================
The owner's strategy of 2026-10-18, tested without money on the games the
football test already watches (match_strategy.py reads them):

  Entry, in the 15 minutes before kickoff, at the real asks:
    - the team is on the elite attacking list (ELITE, or STRICT_TEAMS)
    - the match volume is at least $15,000
    - "Will <team> win?" Yes costs 55–72¢
    - a fixed $25 (STRICT_STAKE)
  Exit at the first of:
    - take-profit: a resting limit sell at entry +20%. It fills, without a
      fee (maker), once a buyer bids that much.
      Polymarket clears the books at kickoff, so a real order placed before
      the match is cancelled then and has to be placed again; the paper test
      assumes it is.
    - stop-loss: the price Polymarket shows is 20% or more below the entry.
      Sold down the real bids, minus the taker fee; with nobody buying it
      keeps trying every minute.
  No time stop. Otherwise the trade is held to the end.

Each trade is also compared with holding it to the end. A win is a trade
that made money; the strategy needs 66% wins to reach its goal.

Nothing here places orders.

Buy signals (asked by the owner on 2026-10-23): each paper entry is also
sent to Telegram as a suggestion to buy for real, with the market link, so
the owner can buy by hand. The bot itself never buys (its server cannot, and
no strategy is proven yet); after the purchase, auto_stop.py sells at −20%.

Settings:
  STRICT_TEST=0   turn the test off (and the buy signals with it)
  BUY_SIGNALS=0   keep the test but send no buy signals
  SIGNAL_PCT      size of a suggested buy, in percent of the watched wallets'
                  value (cash + open positions) at the time (default 2). The
                  paper test keeps its fixed $25.

Each morning (9:00, ALERT_TZ) a heads-up lists the day's candidate games:
an elite team priced near the range (NEAR_RANGE) in the next 24 hours, with
kickoff time. It is not a signal to buy: prices move, and the lineups come
out about an hour before kickoff. The buy signal still comes 15 minutes
before kickoff, at the real price.
  STRICT_STAKE    virtual dollars per trade (default 25)
  STRICT_TEAMS    comma-separated team names replacing the elite list
"""

import os
import re
import unicodedata
from datetime import timedelta

import match_strategy as ms
import trade_journal
import stop_review

ENTRY_RANGE = (0.55, 0.72)
MIN_VOLUME = 15_000
TARGET = 0.20       # take-profit: entry × 1.2
STOP = 0.20         # stop-loss: entry × 0.8
WIN_RATE_GOAL = 0.66

# "Elite attacking teams": the owner named none, so this list is a first
# choice (the clubs that score most in each league, and the strongest
# national teams). Names are matched as whole words, accents ignored.
ELITE = [
    # England
    "Manchester City", "Arsenal", "Liverpool", "Chelsea",
    # Spain
    "Real Madrid", "Barcelona", "Atletico Madrid", "Atletico de Madrid",
    # Germany
    "Bayern", "Dortmund", "Leverkusen",
    # Italy
    "Inter", "Internazionale", "Napoli", "Atalanta",
    # France (Champions League)
    "Paris Saint-Germain", "PSG",
    # Saudi Arabia
    "Al Hilal", "Al Nassr", "Al Ittihad", "Al Ahli",
    # National teams (Nations League)
    "Spain", "France", "England", "Germany", "Portugal",
]

RESULTS = {"target": "الهدف +20%", "stop": "الوقف −20%"}

STATE = {"open": 0, "closed": 0}


def enabled():
    return (os.environ.get("STRICT_TEST") or "").strip() != "0"


def stake():
    try:
        return float(os.environ.get("STRICT_STAKE") or 25)
    except ValueError:
        return 25.0


def _normalize(name):
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    return " " + re.sub(r"[^a-z0-9]+", " ", text).strip() + " "


def elite_teams():
    custom = (os.environ.get("STRICT_TEAMS") or "").strip()
    return [t.strip() for t in custom.split(",") if t.strip()] if custom else ELITE


def is_elite(team):
    name = _normalize(team)
    return any(_normalize(t) in name for t in elite_teams())


def section(ledger):
    return ledger.setdefault("strict_test", {"open": [], "closed": [], "skipped": {},
                                             "digest_day": None, "last_digest_at": None})


def plan(ledger, now):
    """Live slugs, trades to settle and slugs already looked at."""
    sec = section(ledger)
    live = {t["slug"]: t["league"] for t in sec["open"] if not t.get("ended")}
    settle = []
    for t in sec["open"]:
        last = ms._settle_checked.get(t["id"])
        if t.get("ended") and (last is None or now - last >= ms.SETTLE_EVERY):
            settle.append((t["id"], t["market_id"], t["token_id"]))
    return {"live": live, "settle": settle, "entered": set(sec.get("seen", []))}


def _skip(sec, reason):
    sec["skipped"][reason] = sec["skipped"].get(reason, 0) + 1


def enter(sec, game, books, now):
    """Looks at a game once, in its entry window. Returns True if it bought."""
    from paper_trading import simulate_buy  # imported here: paper_trading imports this module
    seen = sec.setdefault("seen", [])
    if game["slug"] in seen:
        return False
    sides = [(side, s) for side, s in game["sides"].items() if is_elite(s["team"])]
    if not sides:
        return False  # not decided yet: a book may still fill in, but no elite team never changes
    if game.get("volume", 0) < MIN_VOLUME:
        seen.append(game["slug"])
        _skip(sec, "volume")
        return False
    for side, s in sides:
        book = books.get(s["token_id"])
        if not book:
            continue
        fill = simulate_buy(book.get("asks") or [], stake(), s["fee_rate"], s["min_size"])
        if not fill:
            continue
        price = fill["cost"] / fill["shares"]
        if ENTRY_RANGE[0] <= price <= ENTRY_RANGE[1]:
            seen.append(game["slug"])
            sec["open"].append({
                "id": f"strict:{game['slug']}:{side}", "slug": game["slug"], "league": game["league"],
                "title": game["title"], "team": s["team"], "side": side, "market_id": s["market_id"],
                "token_id": s["token_id"], "fee_rate": s["fee_rate"], "start": ms._iso(game["start"]),
                "entry_at": ms._iso(now), "entry_price": round(price, 4), "volume": game.get("volume", 0),
                "target": round(min(price * (1 + TARGET), 0.99), 4), "stop": round(price * (1 - STOP), 4),
                **fill,
            })
            return True
    return False


def missed(sec, game):
    """Kickoff came with an elite team never priced 55–72¢ (or a thin book)."""
    seen = sec.setdefault("seen", [])
    if game["slug"] in seen or not any(is_elite(s["team"]) for s in game["sides"].values()):
        return
    seen.append(game["slug"])
    _skip(sec, "price")


def step(trade, game, book, now):
    """Take-profit, then stop-loss. Records trade["exit"] once."""
    if "exit" in trade:
        return
    bids = book.get("bids") or []
    best = max((float(b["price"]) for b in bids), default=None)
    if best is not None and best >= trade["target"] - 1e-9:
        trade["exit"] = {"rule": "target", "at": ms._iso(now), "minute": ms.minute(game),
                         "score": game["score"], "price": trade["target"], "sold_shares": trade["shares"],
                         "proceeds": round(trade["shares"] * trade["target"], 4)}
        return
    mid = ms.mid_price(book)
    if not trade.get("stop_pending") and (mid is None or mid > trade["stop"] + 1e-9):
        return
    sold, proceeds = stop_review.simulate_sell(bids, trade["shares"], trade["fee_rate"])
    if sold <= 0:
        trade["stop_pending"] = True  # nobody buying right now: try again next minute
        return
    trade.pop("stop_pending", None)
    trade["exit"] = {"rule": "stop", "at": ms._iso(now), "minute": ms.minute(game), "score": game["score"],
                     "mid": mid, "sold_shares": sold, "proceeds": proceeds}


def settle(sec, trade, payout, now):
    shares, paid = trade["shares"], trade["cost"] + trade["fee"]
    ex = trade.get("exit")
    value = ex["proceeds"] + (shares - ex["sold_shares"]) * payout if ex else shares * payout
    trade.update(payout=payout, pnl=round(value - paid, 4), hold_pnl=round(shares * payout - paid, 4),
                 closed_at=ms._iso(now))
    sec["open"].remove(trade)
    sec["closed"].append(trade)


def signals_enabled():
    return (os.environ.get("BUY_SIGNALS") or "").strip() != "0"


def signal_pct():
    try:
        return float(os.environ.get("SIGNAL_PCT") or 2)
    except ValueError:
        return 2.0


def signal(trade, game, settled, now, capital=None):
    """The Telegram suggestion to buy what the paper test just bought, sized
    at signal_pct() of the wallets' value (the paper stake when unknown)."""
    minutes = max(0, round((game["start"] - now).total_seconds() / 60))
    if capital:
        amount = round(capital * signal_pct() / 100, 2)
        size = f"${amount:.2f} ({signal_pct():g}% من قيمة محفظتك ${capital:,.2f})"
    else:
        amount = stake()
        size = f"${amount:g} (تعذّرت قراءة قيمة محفظتك الآن)"
    shares = amount / trade["entry_price"]
    return "\n".join([
        "🟢 فرصة شراء: الميزان الصارم 3.0",
        f"{trade['title']}: تبدأ بعد {minutes} دقيقة",
        f"الفريق: {trade['team']}، السعر الآن حوالي {trade['entry_price'] * 100:.1f}¢ "
        f"(حجم تداول المباراة ${trade['volume']:,.0f})",
        f"اشترِ \"نعم\" بـ {size}، أي حوالي {shares:.0f} سهم.",
        f"بعد الشراء: البوت يبيع تلقائياً إن نزل السعر إلى {trade['stop'] * 100:.1f}¢ (−20%)، "
        f"ويرسل لك زر البيع عند {trade['target'] * 100:.1f}¢ (+20%).",
        f"⚠️ الاستراتيجية ما زالت تحت الاختبار: {settled} صفقة محسومة، والحكم بعد 30. القرار لك.",
        f"https://polymarket.com/event/{trade['slug']}",
    ])


def apply(sec, data, now):
    """Entries, exits and settlements for one round (under the ledger lock).
    Returns the buy signals for the entries of this round."""
    games, books = data["games"], data["books"]
    messages = []
    for slug in data.get("candidates", []):
        if slug in games and enter(sec, games[slug], books, now) and signals_enabled():
            messages.append(signal(sec["open"][-1], games[slug], len(sec["closed"]), now, data.get("capital")))
    for slug in data.get("started", []):
        game = ms._schedule.get(slug)
        if game:
            missed(sec, game)
    for trade in list(sec["open"]):
        if trade["id"] in data["payouts"]:
            settle(sec, trade, data["payouts"][trade["id"]], now)
            continue
        if trade.get("ended"):
            continue
        if now - ms._parse_time(trade["start"]) > timedelta(hours=4):
            trade["ended"] = True  # no final whistle seen (data gap): wait for the resolution
            continue
        game = games.get(trade["slug"])
        if game is None:
            continue
        if ms.finished(game):
            trade["ended"] = True
            continue
        step(trade, game, books.get(trade["token_id"]) or {}, now)
    STATE.update(open=len(sec["open"]), closed=len(sec["closed"]))
    return messages

# ─── REPORTS ─────────────────────────────────────────────────────────────────

def results_lines(trades):
    if not trades:
        return []
    paid = sum(t["cost"] + t["fee"] for t in trades)
    pnl = sum(t["pnl"] for t in trades)
    hold = sum(t["hold_pnl"] for t in trades)
    wins = sum(t["pnl"] > 0 for t in trades)
    rules = {r: sum((t.get("exit") or {}).get("rule") == r for t in trades) for r in RESULTS}
    held = sum("exit" not in t for t in trades)
    return [
        f"الربح {wins} من {len(trades)} (‎{wins / len(trades) * 100:.0f}%، والمطلوب {WIN_RATE_GOAL * 100:.0f}%)",
        f"الصافي {ms._usd(pnl)} من ${paid:.2f} (‎{pnl / paid * 100:+.1f}%)، "
        f"ولو احتفظت حتى النهاية {ms._usd(hold)} (‎{hold / paid * 100:+.1f}%)",
        f"الخروج: {RESULTS['target']} {rules['target']}، {RESULTS['stop']} {rules['stop']}، حتى النهاية {held}",
    ]


NEAR_RANGE = (0.50, 0.77)  # the morning list: the entry range ±5¢


def morning(sec, games, now, tz):
    """Once a day from DIGEST_HOUR: today's candidate games, or nothing."""
    if not signals_enabled():
        return []
    local = now.astimezone(tz)
    today = local.strftime("%Y-%m-%d")
    if local.hour < ms.DIGEST_HOUR or sec.get("morning_day") == today:
        return []
    sec["morning_day"] = today
    rows = []
    for game in sorted(games, key=lambda g: g["start"]):
        if not now < game["start"] <= now + timedelta(hours=24):
            continue
        for s in game["sides"].values():
            ask = s.get("ask")
            if not is_elite(s["team"]) or ask is None or not NEAR_RANGE[0] <= ask <= NEAR_RANGE[1]:
                continue
            fits = ENTRY_RANGE[0] <= ask <= ENTRY_RANGE[1]
            volume = game.get("volume", 0)
            rows.append(f"• {game['start'].astimezone(tz):%H:%M} {s['team']} ({game['title']}): "
                        f"{ask * 100:.0f}¢ {'✅ داخل النطاق' if fits else '〰️ قريب من النطاق'}، "
                        f"حجم ${volume:,.0f}{'' if volume >= MIN_VOLUME else ' ⚠️ أقل من $15,000 حتى الآن'}")
    if not rows:
        return []
    return ["\n".join([f"🗓️ مباريات مرشحة للميزان الصارم خلال 24 ساعة ({len(rows)}):"] + rows + [
        "هذه قائمة للتخطيط، لا للشراء. الأسعار تتغير والتشكيلة تُعلن قبل المباراة بساعة تقريباً. "
        "رسالة الشراء تصلك قبل البداية بربع ساعة إذا بقي السعر بين 55¢ و72¢."])]


def digest(sec, now, tz):
    """Morning message on the trades settled since the last one."""
    local = now.astimezone(tz)
    today = local.strftime("%Y-%m-%d")
    if local.hour < ms.DIGEST_HOUR or sec.get("digest_day") == today:
        return []
    since = sec.get("last_digest_at")
    new = [t for t in sec["closed"] if since is None or t["closed_at"] > since]
    sec.update(digest_day=today, last_digest_at=ms._iso(now))
    if not new:
        return []
    return ["\n".join([f"🛡️ الميزان الصارم 3.0 (بدون مال حقيقي): {len(new)} صفقة حُسمت منذ آخر تقرير"]
                      + results_lines(new))]


def dashboard(sec):
    """The figures of the bot's own dashboard page (no wallet data)."""
    closed = sec.get("closed", [])
    paid = sum(t["cost"] + t["fee"] for t in closed)
    pnl = sum(t.get("pnl", 0) for t in closed)
    hold = sum(t.get("hold_pnl", 0) for t in closed)
    wins = sum(t.get("pnl", 0) > 0 for t in closed)
    rows = []
    for t, is_open in ([(t, True) for t in sorted(sec.get("open", []), key=lambda t: t["start"], reverse=True)]
                       + [(t, False) for t in sorted(closed, key=lambda t: t.get("closed_at", ""), reverse=True)]):
        ex = t.get("exit") or {}
        exit_text = ("🎯 هدف" if ex.get("rule") == "target" else
                     f"🛑 وقف · د{ex.get('minute')} · {str(ex.get('score') or '').split('|')[0]}" if ex.get("rule") == "stop"
                     else "—" if is_open else "حتى النهاية")
        payout = t.get("payout")
        rows.append({"title": t["title"], "team": t["team"], "entry": t["entry_price"] * 100, "exit": exit_text,
                     "won": None if payout is None else payout >= 1, "pnl": t.get("pnl"),
                     "hold": t.get("hold_pnl"), "open": is_open})
    skipped = sec.get("skipped") or {}
    return {"settled": len(closed), "open": len(sec.get("open", [])), "wins": wins,
            "win_rate": wins / len(closed) * 100 if closed else None,
            "pnl": pnl, "pnl_pct": pnl / paid * 100 if paid else None,
            "hold": hold, "hold_pct": hold / paid * 100 if paid else None,
            "targets": sum((t.get("exit") or {}).get("rule") == "target" for t in closed),
            "stops": sum((t.get("exit") or {}).get("rule") == "stop" for t in closed),
            "held": sum("exit" not in t for t in closed),
            "skipped_volume": skipped.get("volume", 0), "skipped_price": skipped.get("price", 0),
            "goal": WIN_RATE_GOAL * 100, "break_even": 57, "rows": rows,
            "indicators": {
                "strategy": trade_journal.indicator(len(closed), wins, pnl, paid),
                "hold": trade_journal.indicator(len(closed), sum(t.get("hold_pnl", 0) > 0 for t in closed), hold, paid),
            }}


def summary_lines(ledger):
    sec = section(ledger)
    skipped = sec["skipped"]
    lines = [f"🛡️ الميزان الصارم 3.0: {len(sec['closed'])} صفقة حُسمت، {len(sec['open'])} جارية؛ "
             f"تُركت {skipped.get('volume', 0)} مباراة لحجم أقل من ${MIN_VOLUME:,}، "
             f"و{skipped.get('price', 0)} لسعر خارج 55–72¢"]
    lines += results_lines(sec["closed"])
    if 0 < len(sec["closed"]) < 30:
        lines.append(f"⚠️ {len(sec['closed'])} صفقة فقط: الحكم يحتاج 30 على الأقل.")
    return lines


INTRO = (
    "🛡️ بدأ اختبار \"الميزان الصارم 3.0\" على الورق (بدون مال حقيقي).\n"
    "قبل كل مباراة بربع ساعة يشتري البوت شراءً وهمياً بـ ${stake:g} لفريق من قائمة الفرق الهجومية "
    "إذا كان سعر فوزه بين 55¢ و72¢ وحجم تداول المباراة ${volume:,} على الأقل.\n"
    "يبيع عند +20% من سعر الدخول (أمر بيع محدد، بلا رسوم)، أو عند −20% (بأسعار المشترين وبعد الرسوم). "
    "لا وقف بالوقت.\n"
    "الفرق: {teams}.\n"
    "يصلك تقرير كل صباح فيه الصفقات المحسومة، والمجموع في /paper وملخص الجمعة."
)


def intro():
    return INTRO.format(stake=stake(), volume=MIN_VOLUME, teams="، ".join(elite_teams()))
