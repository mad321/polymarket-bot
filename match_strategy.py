"""
Football hybrid stop-loss: shadow test
======================================
Tests a match strategy on every game of the chosen leagues, without money:

  Entry (an assumption: the rules say how to exit, not what to buy): in the
  15 minutes before kickoff, buy PAPER-$10 of "Will <team> win?" Yes for the
  team priced 55–75¢ (the range of the examples, 57–72¢), at the real asks.
  Polymarket clears the order books at kickoff, so entry is pre-match only.

  Exit at the first rule that holds, checked every minute from kickoff:
    A  price stop: the price is 15¢ or more below the entry price
    B  time stop:  minute 65 or later and the team has not scored
    C  goal:       the team scored (take the profit)
  Sales are priced down the real bids, minus the taker fee. A rule that
  triggers when nobody is buying keeps trying every minute, as a bot would.

  After Polymarket resolves the market, each trade is compared with holding
  to the end. The question: does the strategy beat holding, after costs?

Live score, minute and period come from Polymarket's own event data. Nothing
here places orders; results go to Telegram (a morning digest, /paper and the
Friday summary) and live in the pinned ledger, like paper_trading.py.

Settings:
  MATCH_TEST=0    turn the test off
  MATCH_LEAGUES   Polymarket league codes (default: unl,spl,ucl,epl,lal,bun,sea)
  MATCH_STAKE     virtual dollars per match (default 10)
"""

import os
import json
import logging
from datetime import datetime, timedelta, timezone

import requests

import stop_review

logger = logging.getLogger(__name__)

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"

LEAGUES = {  # Polymarket league code -> (series id, name)
    "unl": (11446, "دوري الأمم الأوروبية"),
    "spl": (10361, "الدوري السعودي"),
    "ucl": (10204, "دوري أبطال أوروبا"),
    "epl": (10188, "الدوري الإنجليزي"),
    "lal": (10193, "الدوري الإسباني"),
    "bun": (10194, "الدوري الألماني"),
    "sea": (10203, "الدوري الإيطالي"),
}
ENTRY_RANGE = (0.55, 0.75)
ENTRY_WINDOW = timedelta(minutes=15)
STOP_DROP = 0.15
TIME_STOP_MINUTE = 65
SCHEDULE_EVERY = timedelta(minutes=10)
SETTLE_EVERY = timedelta(minutes=10)
DIGEST_HOUR = 9  # morning digest, ALERT_TZ
RULES = {"price": "السعر نزل 15¢", "time": "الدقيقة 65 بلا هدف", "goal": "هدف للفريق"}
FINISHED = ("FT", "VFT", "AET", "PEN", "FINISHED", "ENDED")

STATE = {"leagues": None, "games_scheduled": 0, "open": 0, "last_scan_at": None, "error": None}

_schedule = {}            # slug -> game, refreshed every SCHEDULE_EVERY
_schedule_at = None
_settle_checked = {}      # trade id -> last resolution check
_counted_skips = set()    # games that started without a team in the entry range


def enabled():
    return (os.environ.get("MATCH_TEST") or "").strip() != "0"


def stake():
    try:
        return float(os.environ.get("MATCH_STAKE") or 10)
    except ValueError:
        return 10.0


def leagues():
    codes = [c.strip().lower() for c in (os.environ.get("MATCH_LEAGUES") or ",".join(LEAGUES)).split(",")]
    return [c for c in codes if c in LEAGUES]


def _parse_time(text):
    return datetime.fromisoformat(str(text).replace("Z", "+00:00"))


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")

# ─── GAME DATA ───────────────────────────────────────────────────────────────

def parse_game(event, league=None):
    """A match event with its two "Will <team> win?" markets, or None."""
    if not event.get("gameId"):
        return None
    moneyline = [m for m in event.get("markets") or [] if m.get("sportsMarketType") == "moneyline"]
    teams = [m for m in moneyline if not str(m.get("groupItemTitle", "")).startswith("Draw")]
    if len(moneyline) != 3 or len(teams) != 2:
        return None
    title = event.get("title") or ""
    home_name = title.split(" vs. ")[0].strip()
    sides = {}
    for m in teams:
        try:
            outcomes = [o.lower() for o in json.loads(m["outcomes"])]
            tokens = json.loads(m["clobTokenIds"])
            yes = tokens[outcomes.index("yes")]
        except (KeyError, ValueError, TypeError):
            return None
        side = "home" if m.get("groupItemTitle") == home_name else "away"
        rate = (m.get("feeSchedule") or {}).get("rate", 0) if m.get("feesEnabled") else 0
        sides[side] = {"team": m.get("groupItemTitle"), "market_id": str(m["id"]), "token_id": str(yes),
                       "fee_rate": float(rate), "min_size": float(m.get("orderMinSize") or 0)}
    if set(sides) != {"home", "away"}:
        return None
    try:
        start = _parse_time(event.get("startTime") or event["endDate"])
    except (KeyError, ValueError):
        return None
    return {"slug": event["slug"], "league": league, "title": title, "start": start, "sides": sides,
            "live": bool(event.get("live")), "ended": bool(event.get("ended")),
            "period": str(event.get("period") or "").upper(), "elapsed": str(event.get("elapsed") or ""),
            "score": str(event.get("score") or "")}


def minute(game):
    """Match minute as a number (45 at half time), or None before kickoff."""
    if game["period"] == "HT":
        return 45
    digits = ""
    for ch in game["elapsed"]:
        if not ch.isdigit():
            break
        digits += ch
    return int(digits) if digits else None


def goals(game):
    """(home, away) goals, or None when there is no score yet."""
    try:
        home, away = game["score"].split("|")[0].split("-")
        return int(home), int(away)
    except (ValueError, AttributeError):
        return None


def finished(game):
    return game["ended"] or game["period"] in FINISHED


def in_play(game):
    return game["live"] and not finished(game)


def _get(url, **params):
    r = requests.get(url, params=params or None, timeout=20)
    r.raise_for_status()
    return r.json()


def fetch_schedule(now):
    """Games starting from 4 hours ago to 1 day ahead in the chosen leagues."""
    games = {}
    for code in leagues():
        series_id = LEAGUES[code][0]
        for offset in range(0, 500, 100):
            events = _get(f"{GAMMA}/events", series_id=series_id, closed="false", limit=100, offset=offset,
                          end_date_min=(now - timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                          end_date_max=(now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))
            for e in events:
                game = parse_game(e, code)
                if game:
                    games[game["slug"]] = game
            if len(events) < 100:
                break
    return games


def fetch_game(slug, league):
    events = _get(f"{GAMMA}/events", slug=slug)
    return parse_game(events[0], league) if events else None


def fetch_books(token_ids):
    ids, books = list(token_ids), {}
    for i in range(0, len(ids), 100):
        r = requests.post(f"{CLOB}/books", json=[{"token_id": t} for t in ids[i:i + 100]], timeout=20)
        r.raise_for_status()
        books.update({b["asset_id"]: b for b in r.json()})
    return books


def mid_price(book):
    """The price Polymarket shows: the bid/ask midpoint, or the last trade when
    the spread is wider than 10¢ (just after kickoff the books are thin, and a
    wide midpoint would trip the price stop by itself)."""
    bids = [float(b["price"]) for b in book.get("bids") or []]
    asks = [float(a["price"]) for a in book.get("asks") or []]
    if bids and asks and min(asks) - max(bids) <= 0.10 + 1e-9:
        return (max(bids) + min(asks)) / 2
    last = book.get("last_trade_price")
    return float(last) if last not in (None, "") else None

# ─── LEDGER ──────────────────────────────────────────────────────────────────

def section(ledger):
    return ledger.setdefault("match_test", {"open": [], "closed": [], "skipped": 0,
                                            "digest_day": None, "last_digest_at": None})


def plan(ledger, now):
    """What the next fetch needs (read under the ledger lock)."""
    sec = section(ledger)
    live = {t["slug"]: t["league"] for t in sec["open"] if not t.get("ended")}
    settle = []
    for t in sec["open"]:
        if t.get("ended") and now - _settle_checked.get(t["id"], datetime.min.replace(tzinfo=timezone.utc)) >= SETTLE_EVERY:
            settle.append((t["id"], t["market_id"], t["token_id"]))
    entered = {t["slug"] for t in sec["open"] + sec["closed"]}
    return {"live": live, "settle": settle, "entered": entered}


def fetch(plan_, now):
    """Network reads for one round, outside the ledger lock."""
    global _schedule, _schedule_at
    data = {"games": {}, "books": {}, "payouts": {}, "candidates": [], "error": None}
    try:
        if _schedule_at is None or now - _schedule_at >= SCHEDULE_EVERY:
            _schedule, _schedule_at = fetch_schedule(now), now
        candidates = [g for g in _schedule.values()
                      if g["slug"] not in plan_["entered"] and g["start"] - ENTRY_WINDOW <= now < g["start"]]
        data["candidates"] = [g["slug"] for g in candidates]
        data["started"] = [g["slug"] for g in _schedule.values()
                           if g["slug"] not in plan_["entered"] and now - ENTRY_WINDOW <= g["start"] <= now]
        for g in candidates:
            data["games"][g["slug"]] = g
        for slug, league in plan_["live"].items():
            game = fetch_game(slug, league)
            if game:
                data["games"][slug] = game
        tokens = {s["token_id"] for slug in data["candidates"] for s in data["games"][slug]["sides"].values()}
        tokens |= {s["token_id"] for slug in plan_["live"] if slug in data["games"]
                   for s in data["games"][slug]["sides"].values()}
        data["books"] = fetch_books(tokens) if tokens else {}
    except Exception as e:
        data["error"] = f"{type(e).__name__}: {e}"[:300]
    for trade_id, market_id, token_id in plan_["settle"]:
        _settle_checked[trade_id] = now
        try:
            payout = stop_review.fetch_payout(market_id, token_id)
        except Exception as e:
            logger.warning(f"[MATCH] resolution of {market_id}: {e}")
            continue
        if payout is not None:
            data["payouts"][trade_id] = payout
    STATE.update(leagues=leagues(), games_scheduled=len(_schedule), error=data["error"])
    return data


def _enter(sec, game, books, now):
    from paper_trading import simulate_buy  # imported here: paper_trading imports this module
    for side, s in game["sides"].items():
        book = books.get(s["token_id"])
        if not book:
            continue
        fill = simulate_buy(book.get("asks") or [], stake(), s["fee_rate"], s["min_size"])
        if not fill:
            continue
        price = fill["cost"] / fill["shares"]
        if ENTRY_RANGE[0] <= price <= ENTRY_RANGE[1]:
            sec["open"].append({
                "id": f"{game['slug']}:{side}", "slug": game["slug"], "league": game["league"],
                "title": game["title"], "team": s["team"], "side": side, "market_id": s["market_id"],
                "token_id": s["token_id"], "fee_rate": s["fee_rate"], "start": _iso(game["start"]),
                "entry_at": _iso(now), "entry_price": round(price, 4), **fill,
            })
            return True
    return False


def exit_rule(trade, game, mid):
    """The first rule that holds now, in the strategy's order, or None."""
    if not in_play(game):
        return None
    score = goals(game)
    team_goals = score[0 if trade["side"] == "home" else 1] if score else 0
    m = minute(game)
    if mid is not None and mid <= trade["entry_price"] - STOP_DROP + 1e-9:
        return "price"
    if m is not None and m >= TIME_STOP_MINUTE and team_goals == 0:
        return "time"
    if team_goals > 0:
        return "goal"
    return None


def _exit(trade, game, book, now):
    rule = trade.get("pending") or exit_rule(trade, game, mid_price(book))
    if rule is None:
        return
    sold, proceeds = stop_review.simulate_sell(book.get("bids") or [], trade["shares"], trade["fee_rate"])
    if sold <= 0:
        trade["pending"] = rule  # nobody buying right now: try again next minute
        return
    trade.pop("pending", None)
    trade["exit"] = {"rule": rule, "at": _iso(now), "minute": minute(game), "score": game["score"],
                     "mid": mid_price(book), "sold_shares": sold, "proceeds": proceeds}


def _settle(sec, trade, payout, now):
    shares = trade["shares"]
    hold = shares * payout
    ex = trade.get("exit")
    strategy = ex["proceeds"] + (shares - ex["sold_shares"]) * payout if ex else hold
    paid = trade["cost"] + trade["fee"]
    trade.update(payout=payout, hold_pnl=round(hold - paid, 4), strategy_pnl=round(strategy - paid, 4),
                 closed_at=_iso(now))
    sec["open"].remove(trade)
    sec["closed"].append(trade)


def apply(ledger, data, now, tz):
    """Entries, exits and settlements for one round (under the ledger lock). Returns messages."""
    sec = section(ledger)
    games, books = data["games"], data["books"]
    for slug in data["candidates"]:
        if slug in games:
            _enter(sec, games[slug], books, now)
    entered = {t["slug"] for t in sec["open"] + sec["closed"]}
    for slug in data.get("started", []):
        if slug not in entered and slug not in _counted_skips:
            _counted_skips.add(slug)
            sec["skipped"] += 1
    for trade in list(sec["open"]):
        if trade["id"] in data["payouts"]:
            _settle(sec, trade, data["payouts"][trade["id"]], now)
            continue
        game = games.get(trade["slug"])
        if trade.get("ended"):
            continue
        if now - _parse_time(trade["start"]) > timedelta(hours=4):
            trade["ended"] = True  # no final whistle seen (data gap): wait for the resolution
            continue
        if game is None:
            continue
        if finished(game):
            trade["ended"] = True
            continue
        if "exit" not in trade:
            _exit(trade, game, books.get(trade["token_id"]) or {}, now)
    STATE.update(open=len(sec["open"]), last_scan_at=_iso(now))
    return digest(sec, now, tz)

# ─── REPORTS ─────────────────────────────────────────────────────────────────

def _usd(value):
    # The left-to-right mark keeps the sign before the number in RTL messages.
    return f"‎{'-' if value < -0.004 else '+'}${abs(value):.2f}"


def results_lines(trades):
    if not trades:
        return []
    paid = sum(t["cost"] + t["fee"] for t in trades)
    strategy = sum(t["strategy_pnl"] for t in trades)
    hold = sum(t["hold_pnl"] for t in trades)
    rules = {r: sum((t.get("exit") or {}).get("rule") == r for t in trades) for r in RULES}
    no_exit = sum("exit" not in t for t in trades)
    diff = strategy - hold
    verdict = ("لا فرق يُذكر" if abs(diff) < 0.01 else
               f"{'الاستراتيجية' if diff > 0 else 'الاحتفاظ'} أفضل بـ ${abs(diff):.2f}")
    return [
        f"لو طبّقت الاستراتيجية: {_usd(strategy)} (‎{strategy / paid * 100:+.1f}%)",
        f"لو احتفظت حتى النهاية: {_usd(hold)} (‎{hold / paid * 100:+.1f}%)",
        f"← {verdict}",
        f"الخروج: بالسعر {rules['price']}، بالوقت {rules['time']}، بالهدف {rules['goal']}، بلا خروج {no_exit}",
    ]


def digest(sec, now, tz):
    """Morning message on the matches settled since the last one."""
    local = now.astimezone(tz)
    today = local.strftime("%Y-%m-%d")
    if local.hour < DIGEST_HOUR or sec.get("digest_day") == today:
        return []
    since = sec.get("last_digest_at")
    new = [t for t in sec["closed"] if since is None or t["closed_at"] > since]
    sec.update(digest_day=today, last_digest_at=_iso(now))
    if not new:
        return []
    return ["\n".join([f"⚽ اختبار الوقف المختلط (بدون مال حقيقي): {len(new)} مباراة حُسمت منذ آخر تقرير"]
                      + results_lines(new))]


def summary_lines(ledger):
    sec = section(ledger)
    closed = sec["closed"]
    lines = [f"⚽ اختبار الوقف المختلط: {len(closed)} مباراة حُسمت، {len(sec['open'])} جارية، "
             f"{sec['skipped']} بلا فريق بين 55¢ و75¢"]
    lines += results_lines(closed)
    return lines


INTRO = (
    "⚽ بدأ اختبار استراتيجية الوقف المختلط على الورق (بدون مال حقيقي).\n"
    "الدوريات: {leagues}.\n"
    "قبل كل مباراة بربع ساعة يشتري البوت شراءً وهمياً بـ ${stake:g} للفريق الذي سعر فوزه بين 55¢ و75¢، "
    "ثم يبيع عند أول شرط: السعر نزل 15¢، أو الدقيقة 65 بلا هدف للفريق، أو سجّل الفريق هدفاً.\n"
    "بعد الحسم يقارن النتيجة بالاحتفاظ حتى النهاية. يصلك تقرير كل صباح فيه المباريات المحسومة، "
    "والمجموع في /paper وملخص الجمعة."
)


def intro():
    return INTRO.format(leagues="، ".join(LEAGUES[c][1] for c in leagues()), stake=stake())
