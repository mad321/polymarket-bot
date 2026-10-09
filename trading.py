"""
Selling from the bot's wallets
==============================
Sells a position of a trading wallet when you confirm in Telegram. It only
sells: it never buys, and it only touches the wallets set below.

Settings (Render → Environment):
  TRADING_ENABLED=1     show "sell" buttons in Telegram (default: off)
  TRADING_DRY_RUN=0     place real orders (default: 1, simulate only)
  TRADING_WALLET        the bot account's Polymarket wallet address
                        (polymarket.com profile menu)
  TRADING_PRIVATE_KEY   private key of the MetaMask account that owns it
  TRADING_WALLET_2      optional second wallet to sell from, e.g. your main
  TRADING_PRIVATE_KEY_2 account; its key controls everything in that account

A sale is a Fill-and-Kill market order with a minimum price: it sells what
the order book takes at or above that price right away and cancels the rest,
so it can never fill below the price you confirmed.
"""

import os
import time
import hashlib
import logging
import threading
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN

import requests

logger = logging.getLogger(__name__)

SHARE_STEP = Decimal("0.01")  # order sizes take two decimals on every tick size

# Read by /api/alerts/status. Never holds the key or the wallet address.
STATUS = {
    "connected": False,
    "wallet_type": None,
    "client_error": None,
    "geoblock": None,
    "last_order": None,
    "wallet_2": {"connected": False, "wallet_type": None, "client_error": None},
}

_client = None        # the bot wallet (TRADING_WALLET)
_client_2 = None      # the optional second wallet (TRADING_WALLET_2)
_client_lock = threading.Lock()
_sell_lock = threading.Lock()  # one sale at a time, so a double tap cannot sell twice


class TradingError(Exception):
    """A failure to show the user as is (Arabic)."""


# Spaces, line breaks, quotes and invisible direction marks that copy-paste
# (phones, RTL keyboards) slips into a pasted key or address.
_JUNK = dict.fromkeys(map(ord, " \t\r\n\"'`\u200b\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u202d\u202e"
                              "\u2066\u2067\u2068\u2069\ufeff\u00a0"))


def _env(name):
    value = (os.environ.get(name) or "").strip()
    if name.startswith(("TRADING_PRIVATE_KEY", "TRADING_WALLET")):
        value = value.translate(_JUNK)
    return value


def key_problem(name):
    """Why a private key setting cannot be a key, in Arabic, or None. Never shows the key."""
    key = _env(name).removeprefix("0x").removeprefix("0X")
    if not key:
        return None
    if " " in (os.environ.get(name) or "").strip() and len((os.environ.get(name) or "").split()) >= 12:
        return f"{name} فيه كلمات وليس مفتاحاً: ضع المفتاح السري (64 حرفاً من 0-9 و a-f)، لا الكلمات الـ 12."
    if any(c not in "0123456789abcdefABCDEF" for c in key):
        return f"{name} فيه أحرف لا تكون في المفتاح: المفتاح 64 حرفاً من 0-9 و a-f فقط (قد يبدأ بـ 0x)."
    if len(key) != 64:
        return f"{name} طوله {len(key)} حرفاً، والمفتاح 64 حرفاً (بدون 0x): ربما نُسخ ناقصاً أو زائداً."
    return None


def enabled():
    return _env("TRADING_ENABLED") == "1"


def dry_run():
    return _env("TRADING_DRY_RUN") != "0"


def trading_wallet():
    return _env("TRADING_WALLET").lower()


def second_wallet():
    """TRADING_WALLET_2 when it is set with its key, else ""."""
    wallet = _env("TRADING_WALLET_2").lower()
    return wallet if wallet and _env("TRADING_PRIVATE_KEY_2") and wallet != trading_wallet() else ""


def configured():
    return bool(_env("TRADING_PRIVATE_KEY") and trading_wallet()) or bool(second_wallet())


def can_sell(wallet):
    """True when sell buttons belong on this wallet's positions."""
    wallet = (wallet or "").lower()
    if not enabled() or not wallet:
        return False
    # The bot wallet keeps its button without a key: tapping it explains the
    # missing setting. The second wallet gets buttons only once its key is set.
    return wallet == trading_wallet() or wallet == second_wallet()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _redact(text):
    for name in ("TRADING_PRIVATE_KEY", "TRADING_PRIVATE_KEY_2"):
        key = _env(name)
        for secret in (key, key.removeprefix("0x")):
            if secret:
                text = text.replace(secret, "***")
    return text


def position_key(asset_id, wallet=None):
    """Short stable id for a position, to fit Telegram's 64-byte button data.
    Positions of the second wallet include the wallet, so the same market held
    in both wallets gets two different buttons."""
    wallet = (wallet or "").lower()
    if wallet and wallet == second_wallet():
        return hashlib.sha256(f"{wallet}:{asset_id}".encode()).hexdigest()[:10]
    return hashlib.sha256(str(asset_id).encode()).hexdigest()[:10]


def status():
    return {
        "enabled": enabled(),
        "dry_run": dry_run(),
        "configured": configured(),
        **STATUS,
    }


def check_geoblock():
    """Polymarket's view of this server's location, for the status page only:
    it reports US servers as blocked, yet US is close-only, so sells may pass."""
    try:
        data = requests.get("https://polymarket.com/api/geoblock", timeout=10).json()
        STATUS["geoblock"] = {"blocked": data.get("blocked"), "country": data.get("country")}
    except Exception as e:
        STATUS["geoblock"] = {"error": str(e)}


def _get_client(second=False):
    """The client of the bot wallet, or of the second wallet."""
    global _client, _client_2
    wallet_var, key_var = ("TRADING_WALLET_2", "TRADING_PRIVATE_KEY_2") if second else ("TRADING_WALLET", "TRADING_PRIVATE_KEY")
    status = STATUS["wallet_2"] if second else STATUS
    with _client_lock:
        current = _client_2 if second else _client
        if current is not None:
            return current
        if not (_env(key_var) and _env(wallet_var)):
            raise TradingError(f"إعدادات التداول ناقصة: أضف {wallet_var} و {key_var} في Render.")
        problem = key_problem(key_var)
        if problem:
            status["client_error"] = problem
            raise TradingError(problem)
        # Imported here so the alerts keep working even if this package fails.
        from polymarket import SecureClient
        from polymarket._internal.environment import get_environment_config
        from polymarket._internal.wallet import try_classify_wallet_type
        from polymarket.environments import PRODUCTION
        from eth_account import Account

        key, wallet = _env(key_var), _env(wallet_var)
        try:
            signer = Account.from_key(key).address
            # A wallet the key does not own would silently be treated as a
            # session key; refuse instead, with a message that says why.
            derivation = get_environment_config(PRODUCTION).wallet_derivation
            if try_classify_wallet_type(signer=signer, wallet=wallet, config=derivation) is None:
                raise TradingError(f"المفتاح السري لا يملك هذه المحفظة: تأكد أن {wallet_var} هو عنوان محفظة "
                                   f"بوليماركت لنفس الحساب الذي أخذت منه المفتاح ({key_var}).")
            client = SecureClient.create(private_key=key, wallet=wallet)
        except TradingError as e:
            status["client_error"] = str(e)
            raise
        except Exception as e:
            status["client_error"] = _redact(f"{type(e).__name__}: {e}")
            logger.error(f"[TRADING] client error ({wallet_var}): {status['client_error']}")
            raise TradingError("تعذر الاتصال بحساب التداول في بوليماركت. التفاصيل في صفحة الحالة.") from None
        if second:
            _client_2 = client
        else:
            _client = client
        status.update(connected=True, wallet_type=client.wallet_type, client_error=None)
        return client


def _name(p):
    title = p.title or p.slug or str(p.asset_id)
    return f"{title} — {p.outcome}" if p.outcome else title


def _wallet_clients():
    """[(second, client)] for each wallet the bot can sell from. A wallet whose
    client fails is skipped (its error is on the status page) unless none works."""
    out, error = [], None
    slots = [False] if _client is not None or _env("TRADING_PRIVATE_KEY") or not second_wallet() else []
    if second_wallet():
        slots.append(True)
    for second in slots:
        try:
            out.append((second, _get_client(second)))
        except TradingError as e:
            error = error or e
    if not out:
        raise error or TradingError("إعدادات التداول ناقصة: أضف TRADING_WALLET و TRADING_PRIVATE_KEY في Render.")
    return out


def list_positions():
    """Open positions of the trading wallets that can still be sold."""
    from polymarket import PolymarketError

    out = []
    for second, client in _wallet_clients():
        wallet = second_wallet() if second else trading_wallet()
        try:
            for p in client.list_positions(user=client.wallet, status="OPEN").iter_items():
                shares = p.current_size.quantize(SHARE_STEP, rounding=ROUND_DOWN)
                if p.redeemable or shares <= 0:
                    continue
                out.append({
                    "key": position_key(p.asset_id, wallet if second else None),
                    "asset_id": str(p.asset_id),
                    "name": _name(p),
                    "shares": shares,
                    "current_price": p.current_price,
                    "second": second,
                })
        except PolymarketError as e:
            raise TradingError(_redact(f"تعذر قراءة صفقات {'المحفظة الثانية' if second else 'محفظة البوت'}: {e}")) from None
    return out


def _find(key):
    for p in list_positions():
        if p["key"] == key:
            return p
    raise TradingError("لم أجد هذه الصفقة في المحافظ التي يبيع منها البوت. ربما بِيعت أو حُسم السوق.")


def quote(key):
    """Price the whole position would sell at right now, for the confirmation."""
    from polymarket import InsufficientLiquidityError, PolymarketError

    position = _find(key)
    try:
        client = _get_client(position.get("second", False))
        minimum = client.get_order_book(asset_id=position["asset_id"]).min_order_size
        if position["shares"] < minimum:
            raise TradingError(f"لا يمكن البيع: أقل كمية يقبلها هذا السوق {minimum.normalize():f} سهم، "
                               f"وعندك {position['shares']} فقط.")
        price = client.estimate_market_price(
            asset_id=position["asset_id"], side="SELL",
            shares=str(position["shares"]), order_type="FAK",
        )
    except InsufficientLiquidityError:
        raise TradingError("لا يوجد مشترون كافون لهذه الصفقة الآن.") from None
    except PolymarketError as e:
        raise TradingError(_redact(f"تعذر تقدير سعر البيع: {e}")) from None
    return {**position, "price": price, "proceeds": position["shares"] * price}


_REJECTIONS = {
    "fak_not_filled": "لم يُبع شيء: السعر نزل تحت الحد الأدنى الذي أكدته. اضغط بيع مرة أخرى لتحديث السعر.",
    "not_enough_balance": "رصيد الأسهم غير كافٍ أو الموافقة على التداول غير مفعلة في هذا الحساب.",
    "market_not_ready": "السوق لا يقبل أوامر الآن.",
}


def sell(key, shares, min_price):
    """Sells up to `shares` at `min_price` or better. Returns a result dict."""
    from polymarket import PolymarketError

    if not _sell_lock.acquire(blocking=False):
        raise TradingError("عملية بيع أخرى جارية، انتظر نتيجتها.")
    try:
        position = _find(key)
        shares = min(Decimal(str(shares)), position["shares"]).quantize(SHARE_STEP, rounding=ROUND_DOWN)
        if shares <= 0:
            raise TradingError("لا توجد أسهم للبيع في هذه الصفقة.")
        result = {"at": _now(), "name": position["name"], "asset_id": position["asset_id"],
                  "shares": str(shares), "min_price": str(min_price), "dry_run": dry_run(),
                  "second": position.get("second", False)}

        if dry_run():
            result.update(ok=True, status="dry_run")
        else:
            try:
                resp = _get_client(position.get("second", False)).place_market_order(
                    asset_id=position["asset_id"], side="SELL", shares=str(shares),
                    min_price=str(min_price), order_type="FAK",
                )
            except PolymarketError as e:
                result.update(ok=False, status="error", message=_redact(f"{type(e).__name__}: {e}"))
            else:
                if resp.ok:
                    result.update(ok=True, status=resp.status, order_id=resp.order_id,
                                  sold=str(resp.making_amount), received=str(resp.taking_amount))
                else:
                    result.update(ok=False, status=resp.code,
                                  message=_REJECTIONS.get(resp.code, _redact(resp.message)))

        STATUS["last_order"] = result
        logger.info(f"[TRADING] sell {result['status']}: {shares} of {position['name']}")
        return result
    finally:
        _sell_lock.release()


def await_delayed_fill(order_id, asset_id, placed_at, timeout=60, poll=3, second=False):
    """
    Live sports markets hold an order a few seconds before matching, so the
    sale is accepted as "delayed" with nothing filled yet. Polls the CLOB until
    the order's fills appear or it ends without any. Returns
    {"status": "matched", "sold", "received"} or {"status": "unfilled"},
    or None if the outcome is still unknown at the timeout.
    """
    from polymarket import PolymarketError

    client = _get_client(second)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(poll)
        try:
            fills = [t for t in client.list_account_trades(
                         asset_id=asset_id, after=str(int(placed_at) - 5)).iter_items()
                     if t.taker_order_id == order_id]
        except PolymarketError as e:
            logger.warning(f"[TRADING] reading fills of {order_id[:10]}: {_redact(str(e))}")
            fills = []
        if fills:
            sold = sum((t.size for t in fills), Decimal(0))
            received = sum((t.size * t.price for t in fills), Decimal(0))
            return _settle(order_id, {"status": "matched", "sold": sold, "received": received})
        try:
            order = client.get_order(order_id=order_id)
        except PolymarketError:
            continue
        # Ended with nothing matched: the price left the minimum during the delay.
        if (order.status or "").lower() not in ("live", "delayed", "matched") and order.size_matched == 0:
            return _settle(order_id, {"status": "unfilled"})
    return None


def _settle(order_id, outcome):
    last = STATUS.get("last_order") or {}
    if last.get("order_id") == order_id:
        last.update(status=outcome["status"], ok=outcome["status"] == "matched",
                    sold=str(outcome.get("sold", 0)), received=str(outcome.get("received", 0)))
    logger.info(f"[TRADING] delayed order {order_id[:10]} {outcome['status']}")
    return outcome
