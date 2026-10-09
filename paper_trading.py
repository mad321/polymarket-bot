"""
Paper trading: Bitcoin "above ___ on <date>" markets
===================================================
Tests a simple model without money. Every few minutes it reads the open
"Bitcoin above ___ on <date>?" markets (Polymarket series "BTC Multi Strikes
Weekly": each resolves Yes when the Binance BTC/USDT 1-minute close at noon ET
is above the strike), and computes a fair probability for each:

    P(Yes) = N(d2),  d2 = (ln(S/K) - σ²T/2) / (σ√T)

S is the BTC/USDT price now, K the strike, T the time left in years, and σ
the annualized volatility of the last 7 days of hourly BTC/USDT closes.

When buying Yes or No at the real order book, fees included, costs at least
PAPER_MIN_EDGE less than the model's probability, it records a virtual buy
(at most one per expiry date), then settles it on Polymarket's own resolution.

It also records, for every market, the model's and the market's probability
24 hours before expiry and compares their accuracy (Brier score) once resolved:
the honest test of whether the model knows anything the market does not.

Nothing here places orders. Results go to Telegram (a message per paper trade
and per settlement, a weekly summary, and /paper on demand). The ledger is
stored as a pinned file in the Telegram chat (paper_store.py).

The same loop and ledger run the stop-loss / take-profit review
(stop_review.py), which keeps working when paper trading is turned off.

Settings (all optional):
  PAPER_TRADING=0       turn paper trading off (default on when Telegram is
                        configured); the stop-alert review keeps running
  PAPER_STAKE           virtual dollars per trade (default 10)
  PAPER_MIN_EDGE        minimum edge after fees, as a probability (default 0.05)
  PAPER_LEDGER_FILE     keep the ledger in this local file instead of Telegram
"""

import os
import json
import math
import time
import logging
import threading
from datetime import datetime, timedelta, timezone
from statistics import NormalDist, stdev

import pytz
import requests

import alert_memory
import alerts
import match_strategy
import paper_store
import stop_review

logger = logging.getLogger(__name__)

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
BINANCE = "https://data-api.binance.vision/api/v3"  # Binance market data, open to US servers
COINBASE = "https://api.exchange.coinbase.com"
SERIES_ID = 45  # "BTC Multi Strikes Weekly"


def _float_env(name, default):
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


STAKE = _float_env("PAPER_STAKE", 10)
MIN_EDGE = _float_env("PAPER_MIN_EDGE", 0.05)
MIN_HOURS = 2           # no new trades in the last hours: quotes move faster than a 5-minute scan
PRICE_RANGE = (0.05, 0.95)
SCAN_INTERVAL = 300     # seconds between Bitcoin scans
LOOP_INTERVAL = 60      # the loop runs every minute for the live football test
SNAPSHOT_HOURS = 24     # model-vs-market snapshot taken this long before expiry
REVIEW_CHECK_EVERY = 3600  # seconds between resolution checks of one alert's market
SUMMARY_WEEKDAY, SUMMARY_HOUR = 4, 18   # weekly summary: Friday 18:00, ALERT_TZ
DEFAULT_FEE_RATE = 0.07  # crypto taker fee: shares × rate × p × (1 − p)

try:
    TZ = pytz.timezone(os.environ.get("ALERT_TZ", "Asia/Riyadh"))
except pytz.UnknownTimeZoneError:
    TZ = pytz.utc

MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
          "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
SIDES = {"YES": "نعم", "NO": "لا"}

# Read by /api/alerts/status.
STATE = {
    "enabled": False,
    "running": False,
    "store": None,
    "loaded": False,
    "last_scan_at": None,
    "last_error": None,
    "markets": 0,
    "spot": None,
    "sigma": None,
    "best_edge_now": None,
    "open_trades": 0,
}

_lock = threading.Lock()
_ledger = None
_review_checked = {}  # market id -> last resolution check (epoch seconds)
_last_bitcoin_scan = None


def ledger_available():
    """Somewhere to keep the ledger: the ledger loop runs only then."""
    has_telegram = all((os.environ.get(k) or "").strip() for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"))
    return has_telegram or bool((os.environ.get("PAPER_LEDGER_FILE") or "").strip())


def enabled():
    """Paper trading on (the stop-alert review only needs ledger_available())."""
    return (os.environ.get("PAPER_TRADING") or "").strip() != "0" and ledger_available()


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))

# ─── MODEL ───────────────────────────────────────────────────────────────────

def fair_probability(spot, strike, sigma, years):
    """Probability that the price ends above the strike, lognormal without drift."""
    if years <= 0 or sigma <= 0:
        return 1.0 if spot > strike else 0.0
    d2 = (math.log(spot / strike) - sigma * sigma * years / 2) / (sigma * math.sqrt(years))
    return NormalDist().cdf(d2)


def realized_vol(closes, periods_per_year=24 * 365):
    returns = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
    if len(returns) < 24:
        raise ValueError("not enough price history")
    return stdev(returns) * math.sqrt(periods_per_year)


def simulate_buy(asks, stake, fee_rate, min_size=0):
    """Buys `stake` dollars of shares through the asks, cheapest first.
    Returns shares, cost and taker fee, or None if the book is too thin."""
    shares = cost = fee = 0.0
    for price, size in sorted((float(a["price"]), float(a["size"])) for a in asks):
        if not 0 < price < 1:
            continue
        take = math.floor(min(size, (stake - cost) / price) * 100) / 100
        if take <= 0:
            break
        shares += take
        cost += take * price
        fee += take * fee_rate * price * (1 - price)
    if shares <= 0 or shares < min_size or cost < stake * 0.98:
        return None
    return {"shares": round(shares, 2), "cost": round(cost, 4), "fee": round(fee, 5)}


def best_prices(book):
    bids = [float(b["price"]) for b in book.get("bids") or []]
    asks = [float(a["price"]) for a in book.get("asks") or []]
    return (max(bids) if bids else None), (min(asks) if asks else None)

# ─── DATA ────────────────────────────────────────────────────────────────────

def _get(url, **params):
    r = requests.get(url, params=params or None, timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_spot_and_vol():
    """BTC/USDT price and 7-day hourly volatility. Binance is the resolution
    source; Coinbase BTC/USD is the fallback (within a few dollars of it)."""
    try:
        spot = float(_get(f"{BINANCE}/ticker/price", symbol="BTCUSDT")["price"])
        klines = _get(f"{BINANCE}/klines", symbol="BTCUSDT", interval="1h", limit=169)
        return spot, realized_vol([float(k[4]) for k in klines]), "binance"
    except Exception as e:
        logger.warning(f"[PAPER] Binance price failed, using Coinbase: {e}")
    candles = _get(f"{COINBASE}/products/BTC-USD/candles", granularity=3600)[:169]
    spot = float(_get("https://api.coinbase.com/v2/prices/BTC-USD/spot")["data"]["amount"])
    return spot, realized_vol([float(c[4]) for c in reversed(candles)]), "coinbase"


def parse_markets(events):
    """Open markets of the series, with what the model and the ledger need."""
    out = []
    for event in events:
        for m in event.get("markets") or []:
            if m.get("closed") or not m.get("acceptingOrders") or not m.get("enableOrderBook", True):
                continue
            try:
                outcomes = [o.lower() for o in json.loads(m["outcomes"])]
                tokens = json.loads(m["clobTokenIds"])
                strike = float("".join(c for c in m["groupItemTitle"] if c.isdigit() or c == "."))
                end = _parse_time(m.get("endDate") or event["endDate"])
            except (KeyError, ValueError, TypeError):
                continue
            if sorted(outcomes) != ["no", "yes"] or strike <= 0:
                continue
            rate = (m.get("feeSchedule") or {}).get("rate", DEFAULT_FEE_RATE) if m.get("feesEnabled") else 0
            out.append({
                "market_id": str(m["id"]),
                "event": event.get("slug"),
                "strike": strike,
                "end": end,
                "tokens": {"YES": tokens[outcomes.index("yes")], "NO": tokens[outcomes.index("no")]},
                "fee_rate": float(rate),
                "min_size": float(m.get("orderMinSize") or 0),
            })
    return out


def fetch_markets():
    events = _get(f"{GAMMA}/events", series_id=SERIES_ID, closed="false", limit=50)
    return parse_markets(events)


def fetch_books(token_ids):
    books = {}
    ids = list(token_ids)
    for i in range(0, len(ids), 100):
        r = requests.post(f"{CLOB}/books", json=[{"token_id": t} for t in ids[i:i + 100]], timeout=15)
        r.raise_for_status()
        books.update({b["asset_id"]: b for b in r.json()})
    return books


def fetch_winner(market_id):
    """'YES' or 'NO' once Polymarket has resolved the market, else None."""
    m = _get(f"{GAMMA}/markets/{market_id}")
    if not m.get("closed"):
        return None
    try:
        outcomes = [o.upper() for o in json.loads(m["outcomes"])]
        prices = [float(p) for p in json.loads(m["outcomePrices"])]
    except (KeyError, ValueError, TypeError):
        return None
    winners = [o for o, p in zip(outcomes, prices) if p == 1]
    return winners[0] if len(winners) == 1 and sorted(p for p in prices) == [0, 1] else None

# ─── LEDGER ──────────────────────────────────────────────────────────────────

def new_ledger(now):
    ledger = {
        "version": 1,
        "started_at": _iso(now),
        "open": [],
        "closed": [],
        "snapshots": {},
        "calibration": {"n": 0, "model": 0.0, "market": 0.0},
        "level_alerts": {"open": [], "closed": []},  # stop_review.py
        "alert_memory": {"next_alert_at": {}, "exposure_sent": {}},  # alert_memory.py
        "best_edge": None,
        "last_summary_at": _iso(now),
        "summary_week": None,
    }
    if summary_due(ledger, now):  # started after this week's summary time
        ledger["summary_week"] = _week(now)
    return ledger


def _week(now):
    return now.astimezone(TZ).strftime("%G-W%V")


def summary_due(ledger, now):
    local = now.astimezone(TZ)
    past = (local.weekday(), local.hour) >= (SUMMARY_WEEKDAY, SUMMARY_HOUR)
    return past and ledger.get("summary_week") != _week(now)


def market_name(strike, end):
    local_date = end.astimezone(pytz.timezone("America/New_York"))
    return f"هل البيتكوين فوق ${strike:,.0f} يوم {local_date.day} {MONTHS[local_date.month - 1]}؟"


def _pct(p):
    return f"{p * 100:.1f}%"


def _cents(p):
    return f"{p * 100:.1f}¢"


def _signed(value):
    # The left-to-right mark keeps the sign before the number in RTL messages.
    return f"‎{'-' if value < -0.004 else '+'}${abs(value):.2f}"


def evaluate(market, books, spot, sigma, now):
    """The model's probability and a candidate trade per side."""
    years = (market["end"] - now).total_seconds() / (365 * 24 * 3600)
    fair_yes = fair_probability(spot, market["strike"], sigma, years)
    candidates = []
    for side, fair in (("YES", fair_yes), ("NO", 1 - fair_yes)):
        book = books.get(market["tokens"][side])
        if not book:
            continue
        fill = simulate_buy(book.get("asks") or [], STAKE, market["fee_rate"], market["min_size"])
        if not fill:
            continue
        price = fill["cost"] / fill["shares"]
        all_in = (fill["cost"] + fill["fee"]) / fill["shares"]
        if not PRICE_RANGE[0] <= price <= PRICE_RANGE[1]:
            continue
        candidates.append({**fill, "side": side, "fair": fair, "price": price, "edge": fair - all_in})
    return fair_yes, candidates


def open_trades(ledger, markets, books, spot, sigma, now):
    """Records new paper trades and model-vs-market snapshots. Returns messages."""
    messages, best_now = [], None
    traded = {t["event"] for t in ledger["open"] + ledger["closed"]}
    picks = {}
    for m in markets:
        hours = (m["end"] - now).total_seconds() / 3600
        if hours <= 0:
            continue
        fair_yes, candidates = evaluate(m, books, spot, sigma, now)

        # Only inside the window: after downtime, a snapshot close to expiry
        # would flatter both sides and skew the comparison.
        if SNAPSHOT_HOURS - 4 < hours <= SNAPSHOT_HOURS and m["market_id"] not in ledger["snapshots"]:
            bid, ask = best_prices(books.get(m["tokens"]["YES"]) or {})
            if bid is not None and ask is not None and ask - bid <= 0.1:
                ledger["snapshots"][m["market_id"]] = {
                    "end": _iso(m["end"]), "model": round(fair_yes, 4), "market": round((bid + ask) / 2, 4)}

        if hours < MIN_HOURS:
            continue
        for c in candidates:
            if best_now is None or c["edge"] > best_now["edge"]:
                best_now = {**c, "name": market_name(m["strike"], m["end"])}
            if m["event"] in traded or c["edge"] < MIN_EDGE:
                continue
            if m["event"] not in picks or c["edge"] > picks[m["event"]][1]["edge"]:
                picks[m["event"]] = (m, c)

    STATE["best_edge_now"] = round(best_now["edge"], 4) if best_now else None
    best = ledger.get("best_edge")
    if best_now and (best is None or best_now["edge"] > best["edge"]):
        ledger["best_edge"] = {"edge": round(best_now["edge"], 4), "at": _iso(now), "name": best_now["name"],
                               "side": best_now["side"], "price": round(best_now["price"], 4),
                               "fair": round(best_now["fair"], 4)}

    for m, c in picks.values():
        trade = {
            "id": f"{m['market_id']}-{c['side']}",
            "market_id": m["market_id"], "event": m["event"], "token_id": m["tokens"][c["side"]],
            "name": market_name(m["strike"], m["end"]), "strike": m["strike"], "end": _iso(m["end"]),
            "side": c["side"], "opened_at": _iso(now), "spot": round(spot, 2), "sigma": round(sigma, 4),
            "fair": round(c["fair"], 4), "price": round(c["price"], 4), "shares": c["shares"],
            "cost": c["cost"], "fee": c["fee"], "edge": round(c["edge"], 4),
        }
        ledger["open"].append(trade)
        end_local = m["end"].astimezone(TZ)
        messages.append(
            "🧪 صفقة ورقية جديدة (بدون مال حقيقي)\n"
            f"{trade['name']}\n"
            f"الشراء: {SIDES[c['side']]} بسعر {_cents(c['price'])}، {c['shares']:g} سهم بـ ${c['cost']:.2f} "
            f"+ رسوم ${c['fee']:.2f}\n"
            f"تقدير النموذج: {_pct(c['fair'])}، والتكلفة مع الرسوم {_pct(c['price'] + c['fee'] / c['shares'])} "
            f"(فارق {c['edge'] * 100:.1f} نقطة)\n"
            f"البيتكوين الآن: ${spot:,.0f}، التذبذب السنوي: {sigma * 100:.0f}%\n"
            f"يُحسم: {end_local:%d/%m} الساعة {end_local:%H:%M}"
        )
    STATE["open_trades"] = len(ledger["open"])
    return messages


def settle(ledger, winners, now):
    """Closes paper trades and snapshots whose market resolved. Returns messages."""
    messages = []
    for trade in list(ledger["open"]):
        winner = winners.get(trade["market_id"])
        if winner is None:
            continue
        won = winner == trade["side"]
        payout = trade["shares"] if won else 0.0
        pnl = payout - trade["cost"] - trade["fee"]
        trade.update(result="won" if won else "lost", payout=round(payout, 4),
                     pnl=round(pnl, 4), closed_at=_iso(now))
        ledger["open"].remove(trade)
        ledger["closed"].append(trade)
        messages.append(
            f"{'✅ ربحت' if won else '❌ خسرت'} الصفقة الورقية (بدون مال حقيقي)\n"
            f"{trade['name']} — {SIDES[trade['side']]}\n"
            f"النتيجة: {_signed(pnl)} (التكلفة ${trade['cost'] + trade['fee']:.2f}، المستلم ${payout:.2f})"
        )
    cal = ledger["calibration"]
    for market_id, snap in list(ledger["snapshots"].items()):
        winner = winners.get(market_id)
        if winner is None:
            if now - _parse_time(snap["end"]) > timedelta(days=7):
                del ledger["snapshots"][market_id]  # never resolved: drop it
            continue
        outcome = 1.0 if winner == "YES" else 0.0
        cal["n"] += 1
        cal["model"] += (snap["model"] - outcome) ** 2
        cal["market"] += (snap["market"] - outcome) ** 2
        del ledger["snapshots"][market_id]
    STATE["open_trades"] = len(ledger["open"])
    return messages


def due_market_ids(ledger, now):
    ids = {t["market_id"] for t in ledger["open"] if _parse_time(t["end"]) <= now}
    ids |= {mid for mid, s in ledger["snapshots"].items() if _parse_time(s["end"]) <= now}
    return ids

# ─── REPORTS ─────────────────────────────────────────────────────────────────

def _results(trades):
    paid = sum(t["cost"] + t["fee"] for t in trades)
    pnl = sum(t["pnl"] for t in trades)
    wins = sum(t["result"] == "won" for t in trades)
    line = f"{len(trades)} (ربح {wins}، خسارة {len(trades) - wins})"
    if trades:
        line += f"، الصافي {_signed(pnl)} من ${paid:.2f} (‎{pnl / paid * 100:+.1f}%)"
    return line


def summary_text(ledger, now, title):
    if not enabled():
        lines = [f"📒 {title}", "التداول على الورق متوقف (PAPER_TRADING=0)."]
        lines += stop_review.summary_lines(ledger) or ["لا توجد تنبيهات مسجلة للمراجعة بعد."]
        if "match_test" in ledger:
            lines += match_strategy.summary_lines(ledger)
        return "\n".join(lines)
    since = _parse_time(ledger["last_summary_at"])
    recent = [t for t in ledger["closed"] if _parse_time(t["closed_at"]) > since]
    lines = [
        f"📒 {title} (بدون مال حقيقي)",
        f"منذ {since.astimezone(TZ):%d/%m}: صفقات حُسمت {_results(recent)}",
        f"منذ البداية ({_parse_time(ledger['started_at']).astimezone(TZ):%d/%m}): {_results(ledger['closed'])}",
        f"صفقات مفتوحة: {len(ledger['open'])}"
        + (f" (${sum(t['cost'] + t['fee'] for t in ledger['open']):.2f})" if ledger["open"] else ""),
    ]
    cal = ledger["calibration"]
    if cal["n"]:
        model, market = cal["model"] / cal["n"], cal["market"] / cal["n"]
        verdict = "النموذج أدق من السوق" if model < market else "السوق أدق من النموذج"
        lines.append(f"دقة التقدير قبل الحسم بيوم ({cal['n']} سوق، الأقل أفضل): "
                     f"النموذج {model:.4f}، السوق {market:.4f} ← {verdict}")
    best = ledger.get("best_edge")
    if best:
        lines.append(f"أكبر فارق رآه النموذج: {best['edge'] * 100:.1f} نقطة "
                     f"({SIDES[best['side']]} في {best['name']})، والحد المطلوب للشراء {MIN_EDGE * 100:.0f} نقاط")
    lines += stop_review.summary_lines(ledger)
    if "match_test" in ledger:
        lines += match_strategy.summary_lines(ledger)
    lines.append("⚠️ الحكم يحتاج 4 أسابيع و30 صفقة محسومة على الأقل: نتيجة أسبوع واحد قد تكون حظاً.")
    return "\n".join(lines)


def status_text():
    """Reply to /paper."""
    if not ledger_available():
        return "التداول على الورق ومراجعة التنبيهات يحتاجان إعدادات تيليجرام في Render."
    with _lock:
        if _ledger is None:
            return ("سجل التداول على الورق لم يُحمّل بعد. انتظر دقائق ثم أرسل /paper مرة أخرى."
                    + (f"\nآخر خطأ: {STATE['last_error']}" if STATE["last_error"] else ""))
        return summary_text(_ledger, datetime.now(timezone.utc), "التداول على الورق حتى الآن")

# ─── LOOP ────────────────────────────────────────────────────────────────────

def _review_payouts(entries, now):
    """Resolution of the reviewed alerts' markets, each checked at most hourly."""
    payouts = {}
    for market_id, token_id in set(entries):
        if now.timestamp() - _review_checked.get(market_id, 0) < REVIEW_CHECK_EVERY:
            continue
        _review_checked[market_id] = now.timestamp()
        try:
            payout = stop_review.fetch_payout(market_id, token_id)
        except Exception as e:
            logger.warning(f"[REVIEW] resolution of {market_id}: {e}")
            continue
        if payout is not None:
            payouts[(market_id, token_id)] = payout
    return payouts


def scan_once(ledger, now=None):
    """One round: settle what resolved, look for new paper trades, review the
    stop-loss / take-profit alerts. Returns (messages, changed, error).
    Network reads happen before the ledger lock; when the market data for
    paper trading cannot be read, the rest of the round still runs."""
    global _last_bitcoin_scan
    now = now or datetime.now(timezone.utc)
    paper = enabled() and (_last_bitcoin_scan is None or not 0 <= (now - _last_bitcoin_scan).total_seconds() < SCAN_INTERVAL)
    if paper:
        _last_bitcoin_scan = now
    matches = match_strategy.active()
    with _lock:
        before = json.dumps(ledger, sort_keys=True)
        new_review = "level_alerts" not in ledger  # a ledger from before the review existed
        new_matches = match_strategy.enabled() and "match_test" not in ledger
        stop_review.merge(ledger)
        due = due_market_ids(ledger, now) if paper else set()
        review = stop_review.open_entries(ledger)
        match_plan = match_strategy.plan(ledger, now) if matches else None
    winners = {}
    for market_id in due:
        try:
            winner = fetch_winner(market_id)
        except Exception as e:
            logger.warning(f"[PAPER] resolution of {market_id}: {e}")
            continue
        if winner:
            winners[market_id] = winner
    payouts = _review_payouts(review, now)
    match_data = match_strategy.fetch(match_plan, now) if matches else None

    data, error = None, None
    if paper:
        try:
            spot, sigma, source = fetch_spot_and_vol()
            sigma = max(sigma, 0.1)
            markets = [m for m in fetch_markets() if m["end"] > now]
            books = fetch_books(t for m in markets for t in m["tokens"].values())
            STATE.update(markets=len(markets), spot=round(spot, 2), sigma=round(sigma, 4), price_source=source)
            data = (markets, books, spot, sigma)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"[:300]

    with _lock:
        messages = [REVIEW_INTRO] if new_review else []
        if new_matches:
            messages.append(match_strategy.intro())
        messages += stop_review.settle(ledger, payouts, _iso(now))
        if match_data:
            messages += match_strategy.apply(ledger, match_data, now, TZ)
        if paper:
            messages += settle(ledger, winners, now)
            if data:
                messages += open_trades(ledger, *data, now)
        if alert_memory.ready():  # never overwrite saved times before they were restored
            ledger["alert_memory"] = alert_memory.snapshot(now.timestamp())
        if summary_due(ledger, now):
            messages.append(summary_text(ledger, now, "ملخص الأسبوع للتداول على الورق"))
            ledger.update(summary_week=_week(now), last_summary_at=_iso(now), best_edge=None)
        changed = json.dumps(ledger, sort_keys=True) != before
    if match_data and match_data["error"]:
        error = "; ".join(filter(None, [error, f"football: {match_data['error']}"]))
    return messages, changed, error


REVIEW_INTRO = (
    "📊 جديد: مراجعة تنبيهات وقف الخسارة والهدف.\n"
    "عند أول تنبيه لكل صفقة يسجّل البوت كم كنت ستستلم لو بعت كل الأسهم وقتها (بأسعار المشترين الفعلية وبعد الرسوم). "
    "وبعد حسم السوق يرسل لك هل كان البيع عند التنبيه أفضل أم الانتظار، وبكم.\n"
    "البوت لا يبيع شيئاً بنفسه، والتنبيهات لا تتغير. المجموع يظهر في /paper وفي ملخص الجمعة."
)


INTRO = (
    "📒 بدأ التداول على الورق لأسواق البيتكوين (بدون مال حقيقي).\n"
    "البوت يقارن تقدير نموذج حسابي بأسعار أسواق \"هل البيتكوين فوق سعر معيّن يوم كذا\"، "
    "ويسجّل صفقة وهمية بـ ${stake:g} حين يكون السعر أرخص من تقديره بـ {edge:g} نقاط على الأقل بعد الرسوم.\n"
    "تصلك رسالة عند كل صفقة ورقية وعند حسمها، وملخص كل جمعة. أرسل /paper لرؤية النتائج في أي وقت.\n"
    "ويسجّل أيضاً كل تنبيه وقف خسارة أو هدف، ويخبرك بعد حسم السوق هل كان البيع عند التنبيه أفضل أم الانتظار.\n"
    "السجل محفوظ في ملف مثبّت في هذه المحادثة: لا تحذفه."
)


def run_forever():
    global _ledger
    STATE.update(running=True, enabled=enabled())
    stop_review.ACTIVE = True
    store = paper_store.default_store()
    STATE["store"] = store.describe()
    dirty = False
    while True:
        try:
            if _ledger is None:
                ledger = store.load()  # raises if unreadable: never overwrite a ledger we could not read
                if ledger is None:
                    ledger, dirty = new_ledger(datetime.now(timezone.utc)), True
                    alerts.send_alert(INTRO.format(stake=STAKE, edge=MIN_EDGE * 100))
                alert_memory.restore(ledger.get("alert_memory"))
                with _lock:
                    _ledger = ledger
                STATE.update(loaded=True, open_trades=len(ledger["open"]))
            messages, changed, error = scan_once(_ledger)
            dirty = dirty or changed
            for message in messages:  # text, or (text, buttons)
                alerts.send_alert(*message) if isinstance(message, tuple) else alerts.send_alert(message)
            if dirty:
                with _lock:
                    snapshot = json.loads(json.dumps(_ledger))
                store.save(snapshot)  # on failure dirty stays set, so the next round retries
                dirty = False
            STATE.update(last_scan_at=_iso(datetime.now(timezone.utc)), last_error=error)
        except Exception as e:
            STATE["last_error"] = f"{type(e).__name__}: {e}"[:300]
            logger.error(f"[PAPER] {STATE['last_error']}")
        time.sleep(LOOP_INTERVAL)
