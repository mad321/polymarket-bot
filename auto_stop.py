"""
Automatic stop-loss sale
========================
The owner decided on 2026-10-23 that the bot sells by itself at the stop-loss,
without waiting for "تأكيد البيع". Only this: no automatic buying, and no
automatic sale at the take-profit.

What it sells: a football "Will <team> win?" Yes position covered by the
strategy 3.0 alerts (match_strategy.covers), in a wallet the bot can sell
from (trading.can_sell), once the shown price is 20% or more below your
average buy price while the game is under way.

How: every share, as a Fill-and-Kill order at the price the order book pays
now (trading.quote / trading.sell, the same path as the sell button). When
that price is far below the shown price (fewer than MIN_BOOK_RATIO of it,
a thin book), it does not sell and tries again the next minute. After
MAX_TRIES attempts without a sale it stops and tells you to sell by hand.
Each attempt and its result go to Telegram.

Settings (Render → Environment):
  AUTO_STOP=1     turn it on (default off); needs TRADING_ENABLED=1, and
                  TRADING_DRY_RUN=0 for real orders (otherwise it simulates)
"""

import os
import time
import queue
import logging
import threading
from decimal import Decimal

logger = logging.getLogger(__name__)

MIN_BOOK_RATIO = Decimal("0.8")  # sell only if the book pays at least 80% of the shown price
MAX_TRIES = 10
RETRY_AFTER = 55  # seconds; the ledger loop runs every minute

STATE = {"enabled": False, "attempts": 0, "sold": 0, "last": None}

_queue = queue.Queue()
_worker = None
_lock = threading.Lock()
_tries = {}      # position key -> attempts so far
_last_try = {}   # position key -> time of the last attempt
_busy = set()    # position keys queued or being sold
_done = set()    # position keys sold, or given up on


def enabled():
    import trading
    return (os.environ.get("AUTO_STOP") or "").strip() == "1" and trading.enabled()


def applies(pos):
    """True when the stop-loss on this position is sold automatically."""
    import trading
    return enabled() and trading.can_sell(pos.get("wallet"))


def request(pos, mid, now=None):
    """Asks for the sale of a covered position at its stop. Never blocks: the
    sale runs on its own thread, outside the ledger lock."""
    import trading
    now = now or time.time()
    key = trading.position_key(pos["id"], pos.get("wallet"))
    with _lock:
        if key in _done or key in _busy or now - _last_try.get(key, 0) < RETRY_AFTER:
            return False
        _busy.add(key)
        _last_try[key] = now
    _queue.put((key, pos.get("name") or pos.get("title") or "", mid))
    _start()
    return True


def _start():
    global _worker
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, daemon=True, name="auto-stop")
            _worker.start()


def _run():
    import alerts
    while True:
        key, name, mid = _queue.get()
        try:
            message = attempt(key, name, mid)
        except Exception:
            logger.exception("[AUTO-STOP] sale failed unexpectedly")
            message = (f"⚠️ خطأ غير متوقع أثناء البيع التلقائي لـ {name}. "
                       "افتح /positions أو بوليماركت وتحقق من الصفقة.")
        finally:
            with _lock:
                _busy.discard(key)
        if message:
            alerts.send_alert(message)


def attempt(key, name, mid):
    """One try at selling every share. Returns the Telegram text, or None."""
    import trading
    import telegram_actions

    with _lock:
        _tries[key] = tries = _tries.get(key, 0) + 1
    STATE["attempts"] += 1
    give_up = tries >= MAX_TRIES
    try:
        q = trading.quote(key)
    except trading.TradingError as e:
        if "لم أجد هذه الصفقة" in str(e):
            _finish(key)  # sold by hand or resolved meanwhile
            return None
        return _failed(key, name, str(e), give_up)
    shown = Decimal(str(mid)) if mid is not None else q["current_price"]
    if shown and q["price"] < shown * MIN_BOOK_RATIO:
        return _failed(key, q["name"], f"المشترون قليلون: أفضل سعر لكل الأسهم {q['price'] * 100:.0f}¢ "
                                       f"والسعر المعروض {shown * 100:.0f}¢", give_up)
    placed_at = time.time()
    result = trading.sell(key, q["shares"], q["price"])
    STATE["last"] = {k: result.get(k) for k in ("at", "status", "ok", "dry_run")}
    if result.get("status") == "delayed" and result.get("order_id"):
        outcome = trading.await_delayed_fill(result["order_id"], result["asset_id"], placed_at,
                                             second=result.get("second", False))
        if outcome and outcome["status"] == "matched":
            _finish(key, sold=True)
        elif outcome and outcome["status"] == "unfilled":
            return _failed(key, q["name"], "السعر نزل أثناء التنفيذ ولم يُبع شيء", give_up)
        return "🤖 بيع تلقائي عند وقف الخسارة\n" + telegram_actions.delayed_outcome_text(result, outcome)
    if result.get("ok"):
        _finish(key, sold=True)
        return "🤖 بيع تلقائي عند وقف الخسارة\n" + telegram_actions.result_text(result)
    return _failed(key, q["name"], result.get("message") or result.get("status"), give_up)


def _finish(key, sold=False):
    with _lock:
        _done.add(key)
    if sold:
        STATE["sold"] += 1


def _failed(key, name, why, give_up):
    if give_up:
        _finish(key)
        return (f"❌ توقف البيع التلقائي لـ {name} بعد {MAX_TRIES} محاولات: {why}.\n"
                "بِع يدوياً من /positions أو بوليماركت إن أردت.")
    if _tries.get(key) == 1:  # say it once, then retry quietly every minute
        return f"⏳ البيع التلقائي لـ {name} لم يتم: {why}. سأحاول كل دقيقة."
    return None


def status():
    return {**STATE, "enabled": enabled()}
