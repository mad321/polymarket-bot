"""
Selling from the bot's wallet
=============================
Sells a position of the bot's own Polymarket wallet when you confirm in
Telegram. It only sells: it never buys, and it only touches TRADING_WALLET.

Settings (Render → Environment):
  TRADING_ENABLED=1     show "sell" buttons in Telegram (default: off)
  TRADING_DRY_RUN=0     place real orders (default: 1, simulate only)
  TRADING_WALLET        the bot account's Polymarket wallet address
                        (polymarket.com profile menu)
  TRADING_PRIVATE_KEY   private key of the MetaMask account that owns it

A sale is a Fill-and-Kill market order with a minimum price: it sells what
the order book takes at or above that price right away and cancels the rest,
so it can never fill below the price you confirmed.
"""

import os
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
}

_client = None
_client_lock = threading.Lock()
_sell_lock = threading.Lock()  # one sale at a time, so a double tap cannot sell twice


class TradingError(Exception):
    """A failure to show the user as is (Arabic)."""


def _env(name):
    return (os.environ.get(name) or "").strip()


def enabled():
    return _env("TRADING_ENABLED") == "1"


def dry_run():
    return _env("TRADING_DRY_RUN") != "0"


def trading_wallet():
    return _env("TRADING_WALLET").lower()


def configured():
    return bool(_env("TRADING_PRIVATE_KEY") and trading_wallet())


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _redact(text):
    key = _env("TRADING_PRIVATE_KEY")
    for secret in (key, key.removeprefix("0x")):
        if secret:
            text = text.replace(secret, "***")
    return text


def position_key(asset_id):
    """Short stable id for a position, to fit Telegram's 64-byte button data."""
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


def _get_client():
    global _client
    with _client_lock:
        if _client is not None:
            return _client
        if not configured():
            raise TradingError("إعدادات التداول ناقصة: أضف TRADING_WALLET و TRADING_PRIVATE_KEY في Render.")
        # Imported here so the alerts keep working even if this package fails.
        from polymarket import SecureClient
        from polymarket._internal.environment import get_environment_config
        from polymarket._internal.wallet import try_classify_wallet_type
        from polymarket.environments import PRODUCTION
        from eth_account import Account

        key, wallet = _env("TRADING_PRIVATE_KEY"), _env("TRADING_WALLET")
        try:
            signer = Account.from_key(key).address
            # A wallet the key does not own would silently be treated as a
            # session key; refuse instead, with a message that says why.
            derivation = get_environment_config(PRODUCTION).wallet_derivation
            if try_classify_wallet_type(signer=signer, wallet=wallet, config=derivation) is None:
                raise TradingError("المفتاح السري لا يملك هذه المحفظة: تأكد أن TRADING_WALLET هو عنوان محفظة "
                                   "بوليماركت لنفس حساب MetaMask الذي أخذت منه المفتاح.")
            _client = SecureClient.create(private_key=key, wallet=wallet)
        except TradingError as e:
            STATUS["client_error"] = str(e)
            raise
        except Exception as e:
            STATUS["client_error"] = _redact(f"{type(e).__name__}: {e}")
            logger.error(f"[TRADING] client error: {STATUS['client_error']}")
            raise TradingError("تعذر الاتصال بحساب التداول في بوليماركت. التفاصيل في صفحة الحالة.") from None
        STATUS.update(connected=True, wallet_type=_client.wallet_type, client_error=None)
        return _client


def _name(p):
    title = p.title or p.slug or str(p.asset_id)
    return f"{title} — {p.outcome}" if p.outcome else title


def list_positions():
    """Open positions of the trading wallet that can still be sold."""
    from polymarket import PolymarketError

    client = _get_client()
    out = []
    try:
        for p in client.list_positions(user=client.wallet, status="OPEN").iter_items():
            shares = p.current_size.quantize(SHARE_STEP, rounding=ROUND_DOWN)
            if p.redeemable or shares <= 0:
                continue
            out.append({
                "key": position_key(p.asset_id),
                "asset_id": str(p.asset_id),
                "name": _name(p),
                "shares": shares,
                "current_price": p.current_price,
            })
    except PolymarketError as e:
        raise TradingError(_redact(f"تعذر قراءة صفقات محفظة البوت: {e}")) from None
    return out


def _find(key):
    for p in list_positions():
        if p["key"] == key:
            return p
    raise TradingError("لم أجد هذه الصفقة في محفظة البوت. ربما بِيعت أو حُسم السوق.")


def quote(key):
    """Price the whole position would sell at right now, for the confirmation."""
    from polymarket import InsufficientLiquidityError, PolymarketError

    position = _find(key)
    try:
        minimum = _get_client().get_order_book(asset_id=position["asset_id"]).min_order_size
        if position["shares"] < minimum:
            raise TradingError(f"لا يمكن البيع: أقل كمية يقبلها هذا السوق {minimum.normalize():f} سهم، "
                               f"وعندك {position['shares']} فقط.")
        price = _get_client().estimate_market_price(
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
        result = {"at": _now(), "name": position["name"], "shares": str(shares),
                  "min_price": str(min_price), "dry_run": dry_run()}

        if dry_run():
            result.update(ok=True, status="dry_run")
        else:
            try:
                resp = _get_client().place_market_order(
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
