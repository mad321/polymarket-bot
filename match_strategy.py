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

The same games feed the "strict balance" 3.0 paper test (strict_strategy.py).

Alerts on your own positions follow strategy 3.0 since 2026-10-18 (they
followed the three rules above before): every "Will <team> win?" Yes position
of the watched wallets in these leagues alerts when the price reaches +20% or
falls 20% from your average buy price. Each alerts once per position, with
what selling every share would pay right then; positions of the bot wallet
get the sell button. These positions skip the monitor's generic stop-loss /
take-profit alerts (polymarket_monitor.py), which would contradict them.

Settings:
  MATCH_TEST=0    turn the test off
  MATCH_ALERTS=0  turn the alerts on your positions off
  MATCH_LEAGUES   Polymarket league codes (default: unl,spl,ucl,epl,lal,bun,sea)
  MATCH_STAKE     virtual dollars per match (default 10)
"""

import os
import json
import logging
from datetime import datetime, timedelta, timezone

import requests

import auto_stop
import live_feed
import positions as positions_module
import stop_review
import strict_strategy

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

# ── مستويات السيولة (حجم التداول الكلي للسوق) ──────────────────────────────
# المستوى 1 - حد أدنى مطلق: لا دخول تحته أبداً
LIQUIDITY_MIN = 5_000
# المستوى 2 - المنطقة الذهبية: دخول مريح
LIQUIDITY_GOOD = 8_000
# المستوى 3 - مثالي: أفضل سيولة وأقل انزلاق سعري
LIQUIDITY_IDEAL = 15_000


def liquidity_tier(volume: float) -> str:
    """
    تحديد مستوى السيولة لسوق معين.
    يُستخدم في تقرير الورق وتنبيهات الصفقات.

    المستوى 1 ($5k+):  حد أدنى — دخول مسموح لكن بحذر
    المستوى 2 ($8k+):  منطقة ذهبية — دخول مريح
    المستوى 3 ($15k+): مثالي — أفضل تنفيذ وأقل انزلاق

    أقل من $5k: مرفوض
    """
    if volume >= LIQUIDITY_IDEAL:
        return "مثالي ✅"
    elif volume >= LIQUIDITY_GOOD:
        return "جيد 🟡"
    elif volume >= LIQUIDITY_MIN:
        return "مقبول ⚠️"
    else:
        return "مرفوض 🔴"


def liquidity_ok(volume: float) -> bool:
    """True إذا كانت السيولة كافية للدخول (المستوى 1 فما فوق)."""
    return volume >= LIQUIDITY_MIN
RULES = {"price": "السعر نزل 15¢", "time": "الدقيقة 65 بلا هدف", "goal": "هدف للفريق"}
# Rule sets run side by side on the same paper trades, to tell which rule
# earns and which costs. "full" is the strategy as specified.
VARIANTS = {
    "hold": ((), "الاحتفاظ حتى النهاية"),
    "price": (("price",), "وقف السعر فقط"),
    "price_time": (("price", "time"), "وقف السعر + الوقت"),
    "goal": (("goal",), "البيع عند الهدف فقط"),
    "full": (("price", "time", "goal"), "الاستراتيجية كاملة"),
}
FINISHED = ("FT", "VFT", "AET", "PEN", "FINISHED", "ENDED")

STATE = {"leagues": None, "games_scheduled": 0, "open": 0, "last_scan_at": None, "error": None,
         "positions_in_play": 0, "alerts_sent": 0}

_schedule = {}            # slug -> game, refreshed every SCHEDULE_EVERY
_schedule_at = None
_settle_checked = {}      # trade id -> last resolution check
_counted_skips = set()    # games that started without a team in the entry range


def enabled():
    """The shadow test."""
    return (os.environ.get("MATCH_TEST") or "").strip() != "0"


def alerts_enabled():
    """The alerts on your own positions."""
    return (os.environ.get("MATCH_ALERTS") or "").strip() != "0"


def active():
    return enabled() or alerts_enabled() or strict_strategy.enabled()


def covers(pos):
    """True for the positions the hybrid alerts handle: Yes on "Will <team> win?"
    in one of the chosen leagues (a draw or a No position is not covered)."""
    if not alerts_enabled():
        return False
    league = str(pos.get("event") or "").split("-")[0]
    title = str(pos.get("title") or "")
    return (league in leagues() and str(pos.get("outcome") or "").lower() == "yes"
            and title.startswith("Will ") and " win " in title)


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
    # حجم تداول الحدث = مجموع حجوم جميع الأسواق فيه
    volume = sum(float(m.get("volume") or 0) for m in (event.get("markets") or []))
    return {"slug": event["slug"], "game_id": event.get("gameId"), "league": league, "title": title,
            "start": start, "sides": sides,
            "live": bool(event.get("live")), "ended": bool(event.get("ended")),
            "period": str(event.get("period") or "").upper(), "elapsed": str(event.get("elapsed") or ""),
            "score": str(event.get("score") or ""), "volume": round(volume, 2)}


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
    if not enabled():
        live, settle, entered = {}, [], None
    if strict_strategy.enabled():
        strict = strict_strategy.plan(ledger, now)
        live.update(strict["live"])
        settle += strict["settle"]
        # a game is still a candidate while either test has not decided on it
        entered = strict["entered"] if entered is None else entered & strict["entered"]
    return {"live": live, "settle": settle, "entered": entered or set()}


def fetch(plan_, now):
    """Network reads for one round, outside the ledger lock."""
    global _schedule, _schedule_at
    data = {"games": {}, "books": {}, "payouts": {}, "candidates": [], "positions": [], "error": None}
    try:
        if _schedule_at is None or now - _schedule_at >= SCHEDULE_EVERY:
            _schedule, _schedule_at = fetch_schedule(now), now
        testing = enabled() or strict_strategy.enabled()
        candidates = [g for g in _schedule.values() if testing
                      and g["slug"] not in plan_["entered"] and g["start"] - ENTRY_WINDOW <= now < g["start"]]
        data["candidates"] = [g["slug"] for g in candidates]
        if candidates and strict_strategy.enabled() and strict_strategy.signals_enabled():
            import exposure
            data["capital"] = exposure.capital()  # sizes the buy signals
        data["started"] = [g["slug"] for g in _schedule.values() if testing
                           and g["slug"] not in plan_["entered"] and now - ENTRY_WINDOW <= g["start"] <= now]
        for g in candidates:
            data["games"][g["slug"]] = g
        live = dict(plan_["live"])
        data["positions"] = _positions_in_play(now)
        if live_feed.enabled():  # games under way and your positions, watched second by second
            live_feed.watch([g for g in _schedule.values() if g["start"] <= now <= g["start"] + timedelta(hours=3)],
                            data["positions"])
        for pos in data["positions"]:
            live[pos["_game"]["slug"]] = pos["_game"]["league"]
        for slug, league in live.items():
            game = fetch_game(slug, league)
            if game:
                data["games"][slug] = game
        tokens = {s["token_id"] for slug in data["candidates"] for s in data["games"][slug]["sides"].values()}
        tokens |= {s["token_id"] for slug in live if slug in data["games"]
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
    STATE.update(leagues=leagues(), games_scheduled=len(_schedule), error=data["error"],
                 positions_in_play=len(data["positions"]))
    return data


def _positions_in_play(now):
    """Your covered positions whose game is under way (read only while a
    scheduled game is), each tagged with its game and side."""
    if not alerts_enabled():
        return []
    playing = [g for g in _schedule.values() if g["start"] <= now <= g["start"] + timedelta(hours=3)]
    if not playing:
        return []
    by_token = {s["token_id"]: (g, side) for g in playing for side, s in g["sides"].items()}
    rows, source, _ = positions_module.load_positions()
    if source != "wallet":
        return []
    out = []
    for p in rows:
        hit = by_token.get(str(p.get("id")))
        if hit and covers(p):
            out.append({**p, "_game": hit[0], "_side": hit[1]})
    return out


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
                "entry_at": _iso(now), "entry_price": round(price, 4),
                "volume": game.get("volume", 0),
                "liquidity_tier": liquidity_tier(game.get("volume", 0)),
                **fill,
            })
            return True
    return False


def exit_rule(trade, game, mid, rules=("price", "time", "goal")):
    """The first of `rules` that holds now, in the strategy's order, or None."""
    if not in_play(game):
        return None
    score = goals(game)
    team_goals = score[0 if trade["side"] == "home" else 1] if score else 0
    m = minute(game)
    if "price" in rules and mid is not None and mid <= trade["entry_price"] - STOP_DROP + 1e-9:
        return "price"
    if "time" in rules and m is not None and m >= TIME_STOP_MINUTE and team_goals == 0:
        return "time"
    if "goal" in rules and team_goals > 0:
        return "goal"
    return None


def _exit(trade, game, book, now):
    """Applies every variant's rules; "full" is also kept as trade["exit"]."""
    exits = trade.setdefault("exits", {})
    pending = trade.setdefault("pending_by", {})
    if "pending" in trade:  # a trade from before the variants
        pending.setdefault("full", trade.pop("pending"))
    mid = mid_price(book)
    for name, (rules, _) in VARIANTS.items():
        if not rules or name in exits:
            continue
        rule = pending.get(name) or exit_rule(trade, game, mid, rules)
        if rule is None:
            continue
        sold, proceeds = stop_review.simulate_sell(book.get("bids") or [], trade["shares"], trade["fee_rate"])
        if sold <= 0:
            pending[name] = rule  # nobody buying right now: try again next minute
            continue
        pending.pop(name, None)
        exits[name] = {"rule": rule, "at": _iso(now), "minute": minute(game), "score": game["score"],
                       "mid": mid, "sold_shares": sold, "proceeds": proceeds}
    if "full" in exits and "exit" not in trade:
        trade["exit"] = exits["full"]


def _settle(sec, trade, payout, now):
    shares = trade["shares"]
    hold = shares * payout
    ex = trade.get("exit")
    strategy = ex["proceeds"] + (shares - ex["sold_shares"]) * payout if ex else hold
    paid = trade["cost"] + trade["fee"]
    trade.update(payout=payout, hold_pnl=round(hold - paid, 4), strategy_pnl=round(strategy - paid, 4),
                 closed_at=_iso(now))
    if "exits" in trade:  # entered with the variants running
        variant_pnl = {}
        for name in VARIANTS:
            v = trade["exits"].get(name)
            value = v["proceeds"] + (shares - v["sold_shares"]) * payout if v else hold
            variant_pnl[name] = round(value - paid, 4)
        trade["variant_pnl"] = variant_pnl
    sec["open"].remove(trade)
    sec["closed"].append(trade)


def apply(ledger, data, now, tz):
    """Entries, exits and settlements for one round (under the ledger lock). Returns messages."""
    sec = section(ledger)
    games, books = data["games"], data["books"]
    messages = position_alerts(ledger, data, now) if alerts_enabled() else []
    if strict_strategy.enabled():
        strict = strict_strategy.section(ledger)
        messages += strict_strategy.apply(strict, data, now)  # buy signals
        messages += strict_strategy.digest(strict, now, tz)
    if not enabled():
        STATE.update(last_scan_at=_iso(now))
        return messages
    already = {t["slug"] for t in sec["open"] + sec["closed"]}
    for slug in data["candidates"]:
        if slug in already:
            continue  # a candidate only for the strict test
        if slug in games:
            game = games[slug]
            vol = game.get("volume", 0)
            if not liquidity_ok(vol):
                # سيولة غير كافية — تسجيل التخطي مع السبب
                if slug not in _counted_skips:
                    _counted_skips.add(slug)
                    sec["skipped"] += 1
                    sec.setdefault("skipped_liquidity", []).append({
                        "slug": slug, "title": game["title"],
                        "volume": vol, "tier": liquidity_tier(vol),
                        "at": _iso(now),
                    })
                logger.info(f"[MATCH] تخطي {game['title']} — سيولة {vol:,.0f}$ ({liquidity_tier(vol)})")
            else:
                _enter(sec, game, books, now)
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
        exits = trade.get("exits")
        if (exits is None and "exit" not in trade) or (exits is not None and len(exits) < len(VARIANTS) - 1):
            _exit(trade, game, books.get(trade["token_id"]) or {}, now)  # until every variant has sold
    STATE.update(open=len(sec["open"]), last_scan_at=_iso(now))
    return messages + digest(sec, now, tz)

# ─── ALERTS ON YOUR POSITIONS ────────────────────────────────────────────────

ALERTS_INTRO = (
    "🛡️ تنبيهات صفقاتك الحقيقية تتبع الآن الميزان الصارم 3.0.\n"
    "لكل صفقة \"هل سيفوز الفريق؟ نعم\" في الدوريات المختارة، يتابع البوت المباراة كل دقيقة ويرسل تنبيهاً عند: "
    "وصول السعر إلى +20% من سعر شرائك (الهدف)، أو نزوله 20% عنه (الوقف). "
    "لا تنبيه بالدقيقة 65 ولا عند الهدف بعد الآن.\n"
    "كل تنبيه مرة واحدة، ومعه كم ستستلم لو بعت الآن. صفقات محفظة البوت يأتي معها زر البيع. "
    "البوت لا يبيع ولا يضع أوامر بنفسه."
)


def alert_rule(entry, game, mid):
    """Strategy 3.0 on your position: "target" at +20%, "stop" at -20%, or None."""
    if not in_play(game) or mid is None or entry <= 0:
        return None
    if mid >= entry * (1 + strict_strategy.TARGET) - 1e-9:
        return "target"
    if mid <= entry * (1 - strict_strategy.STOP) + 1e-9:
        return "stop"
    return None


def position_alerts(ledger, data, now):
    """Alerts on your covered positions, each rule once per position."""
    sec = section(ledger)
    messages = []
    if not sec.get("alerts_intro_v3"):
        sec["alerts_intro_v3"] = _iso(now)
        messages.append(ALERTS_INTRO)
    sent = sec.setdefault("alerted", {})
    for key, at in list(sent.items()):
        if now - _parse_time(at) > timedelta(days=3):
            del sent[key]
    for pos in data.get("positions", []):
        game = data["games"].get(pos["_game"]["slug"])
        token = str(pos["id"])
        if game is None:
            continue
        book = data["books"].get(token) or {}
        rule = alert_rule(float(pos.get("buy_price") or 0) / 100, game, mid_price(book))
        if rule is None:
            continue
        if rule == "stop" and auto_stop.applies(pos):
            auto_stop.request(pos, mid_price(book))  # retried every minute until sold
        key = f"{pos.get('wallet', '')}:{token}:{rule}"
        if key in sent:
            continue
        sent[key] = _iso(now)
        STATE["alerts_sent"] += 1
        messages.append(position_alert(pos, game, rule, book))
    return messages


def position_alert(pos, game, rule, book):
    """The alert text, with a sell button for the bot wallet (a (text, markup) pair)."""
    import trading
    import telegram_actions  # imported here: it imports paper_trading, which imports this module

    side = game["sides"][pos["_side"]]
    team, shares, buy = side["team"], float(pos.get("shares") or 0), float(pos.get("buy_price") or 0)
    m, score = minute(game), game["score"] or "0-0"
    mid = mid_price(book)
    headers = {
        "stop": f"🔴 الميزان الصارم: سعر {team} نزل 20% عن سعر شرائك",
        "target": f"🟢 الميزان الصارم: سعر {team} وصل +20% فوق سعر شرائك",
    }
    lines = [headers[rule], f"{game['title']}: {score} (الدقيقة {m})",
             f"سعر شرائك {buy:g}¢" + (f"، والسعر الآن {mid * 100:.1f}¢" if mid is not None else "")]
    sold, proceeds = stop_review.simulate_sell(book.get("bids") or [], shares, side["fee_rate"])
    if sold > 0:
        best = max(float(b["price"]) for b in book.get("bids") or [])
        line = (f"بيع {sold:g} سهم الآن يعطي حوالي ${proceeds:.2f} (أفضل مشترٍ {best * 100:.0f}¢)، "
                f"أي {_usd(proceeds - sold * buy / 100)} مقارنة بسعر شرائك")
        if sold < shares:
            line += f". لا مشترين لباقي الأسهم ({shares - sold:g})"
        lines.append(line)
    else:
        lines.append("لا يوجد مشترون الآن: حاول بعد قليل.")
    in_bot_wallet = bool(trading.trading_wallet()) and (pos.get("wallet") or "").lower() == trading.trading_wallet()
    lines.append(f"المحفظة: {'محفظة البوت' if in_bot_wallet else 'المحفظة الرئيسية'}")
    if rule == "target":
        lines.append("إن كان أمر البيع المحدد عند +20% قائماً فقد يكون نُفّذ: تأكد في بولي ماركت. "
                     "تذكير: بولي ماركت يمسح الأوامر عند بداية المباراة، فالأمر الموضوع قبلها لم يعد قائماً.")
    auto = rule == "stop" and auto_stop.applies(pos)
    if auto:
        lines.append("🤖 البوت يبيع كل الأسهم الآن تلقائياً (AUTO_STOP)، وستصلك النتيجة.")
    else:
        lines.append("القاعدة تقول: بِع. القرار لك، فالاستراتيجية ما زالت قيد الاختبار.")
    if not in_bot_wallet and pos.get("url"):
        lines.append(pos["url"])
    text = "\n".join(lines)
    if trading.can_sell(pos.get("wallet")) and not auto:
        return text, telegram_actions.sell_button(pos["id"], pos.get("wallet"))
    return text

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
                      + results_lines(new) + variant_lines(new))]


def variant_lines(trades):
    """The rule sets side by side, best first, on trades that ran them all."""
    trades = [t for t in trades if t.get("variant_pnl")]
    if not trades:
        return []
    paid = sum(t["cost"] + t["fee"] for t in trades)
    totals = {name: sum(t["variant_pnl"][name] for t in trades) for name in VARIANTS}
    lines = [f"🔬 مقارنة القواعد على نفس {len(trades)} مباراة:"]
    for name, total in sorted(totals.items(), key=lambda kv: -kv[1]):
        lines.append(f"• {VARIANTS[name][1]}: {_usd(total)} (‎{total / paid * 100:+.1f}%)")
    return lines


def summary_lines(ledger):
    sec = section(ledger)
    closed = sec["closed"]
    skipped_liq = sec.get("skipped_liquidity") or []
    lines = [f"⚽ اختبار الوقف المختلط: {len(closed)} مباراة حُسمت، {len(sec['open'])} جارية، "
             f"{sec['skipped']} بلا فريق بين 55¢ و75¢"]
    if skipped_liq:
        lines.append(f"🚫 تخطّى {len(skipped_liq)} مباراة بسبب سيولة منخفضة (أقل من ${LIQUIDITY_MIN:,})")
    # مستويات السيولة للصفقات المغلقة
    if closed:
        tiers = {"مثالي ✅": 0, "جيد 🟡": 0, "مقبول ⚠️": 0}
        for t in closed:
            tier = t.get("liquidity_tier", "")
            if tier in tiers:
                tiers[tier] += 1
        tier_str = " | ".join(f"{k}: {v}" for k, v in tiers.items() if v > 0)
        if tier_str:
            lines.append(f"💧 مستويات السيولة: {tier_str}")
    lines += results_lines(closed)
    lines += variant_lines(closed)
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
