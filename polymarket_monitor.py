"""
Polymarket Hybrid Stop-Loss Monitor — Telegram Alerts
======================================================
يراقب الصفقات المفتوحة كل 30 ثانية ويرسل تنبيه تيليجرام عند:
  - الشرط A: السعر نزل 15¢ من سعر الدخول  (Price Stop-Loss)
  - الشرط B: الدقيقة 65 من المباراة بدون هدف (Time Stop-Loss)
  - الشرط C: السعر قفز فوق 80¢ (هدف سُجِّل → Take Profit)

متغيرات البيئة المطلوبة:
  TELEGRAM_BOT_TOKEN  — توكن البوت من @BotFather
  TELEGRAM_CHAT_ID    — رقم المحادثة (احصل عليه من @userinfobot)
"""

import os
import json
import time
import requests
from datetime import datetime, timezone

# ─── CONFIG ────────────────────────────────────────────────────────────────────

POLYMARKET_API  = "https://clob.polymarket.com"
GAMMA_API       = "https://gamma-api.polymarket.com"

TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT   = os.environ.get("TELEGRAM_CHAT_ID", "")

CONFIG_FILE     = "config.json"
CHECK_INTERVAL  = 30     # ثانية بين كل فحص
ALERT_COOLDOWN  = 120    # ثانية قبل إعادة إرسال نفس التنبيه

# ─── Hybrid Stop-Loss Constants ────────────────────────────────────────────────

PRICE_STOP_DROP    = 15    # ¢ — اخرج إذا نزل السعر هذا القدر من الدخول
TIME_STOP_MINUTE   = 65    # دقيقة — اخرج بعد هذا الوقت بدون هدف
GOAL_PRICE_SPIKE   = 80    # ¢ — إذا وصل السعر هذا → هدف → اخرج بربح

# ─── TELEGRAM ──────────────────────────────────────────────────────────────────

def send_telegram(message: str) -> bool:
    """ترسل رسالة نصية عبر Telegram Bot API."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        print(f"[TELEGRAM NOT CONFIGURED] {message}")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        print(f"[TELEGRAM ✓] {message[:60]}...")
        return True
    except Exception as e:
        print(f"[TELEGRAM ERROR] {e}")
        return False

# ─── PRICE FETCHING ────────────────────────────────────────────────────────────

def get_price_by_slug(slug: str) -> float | None:
    """جلب السعر الحالي للسوق عبر slug."""
    try:
        r = requests.get(f"{GAMMA_API}/markets?slug={slug}", timeout=10)
        r.raise_for_status()
        data = r.json()
        if not data:
            return None
        prices = data[0].get("outcomePrices", [])
        if isinstance(prices, str):
            prices = json.loads(prices)
        if prices:
            return round(float(prices[0]) * 100, 1)
    except Exception as e:
        print(f"[PRICE ERROR] {slug}: {e}")
    return None

def get_price_by_token_id(token_id: str) -> float | None:
    """جلب السعر مباشرة عبر token_id."""
    try:
        r = requests.get(
            f"{POLYMARKET_API}/price?token_id={token_id}&side=sell",
            timeout=10
        )
        r.raise_for_status()
        price = r.json().get("price")
        if price is not None:
            return round(float(price) * 100, 1)
    except Exception as e:
        print(f"[PRICE ERROR] token {token_id[:12]}...: {e}")
    return None

def get_price(position: dict) -> float | None:
    """اختار طريقة الجلب حسب الحقول المتوفرة في config."""
    if "token_id" in position:
        return get_price_by_token_id(position["token_id"])
    elif "slug" in position:
        return get_price_by_slug(position["slug"])
    return None

# ─── MATCH TIME ────────────────────────────────────────────────────────────────

def get_match_minute(position: dict) -> int | None:
    """
    احسب دقيقة المباراة من وقت الانطلاق المخزن في config.
    يتوقع حقل 'match_start' بصيغة ISO 8601: "2026-10-07T20:00:00+03:00"
    يعيد None إذا لم يكن الحقل موجوداً.
    """
    start_str = position.get("match_start")
    if not start_str:
        return None
    try:
        start = datetime.fromisoformat(start_str)
        # تأكد أن كلاهما aware
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        elapsed = (now - start).total_seconds()
        # لو المباراة لم تبدأ بعد
        if elapsed < 0:
            return None
        # أوقاف وعروض (45 دق + إضافي) → نضيف 10 دقائق للشوط الأول
        minute = int(elapsed / 60)
        return minute
    except Exception as e:
        print(f"[TIME ERROR] {e}")
        return None

# ─── ALERT FORMATTING ──────────────────────────────────────────────────────────

def format_alert(pos: dict, price: float, reason: str, minute: int | None = None) -> str:
    """صيغة رسالة التنبيه بالعربي."""

    time_str = datetime.now().strftime("%H:%M")
    name     = pos.get("name", "—")
    entry    = pos.get("buy_price", "—")
    shares   = pos.get("shares", "—")
    slug     = pos.get("slug", "")
    link     = f"https://polymarket.com/event/{slug}" if slug else ""

    # حساب الربح/الخسارة التقريبي
    try:
        pnl_pct = round((price - float(entry)) / float(entry) * 100, 1)
        pnl_sign = "+" if pnl_pct >= 0 else ""
        pnl_str = f"{pnl_sign}{pnl_pct}%"
    except Exception:
        pnl_str = "—"

    if reason == "price_stop":
        header  = "🔴 <b>وقف خسارة — انخفاض السعر</b>"
        action  = "بيع فوري"
        detail  = f"السعر نزل {PRICE_STOP_DROP}¢ من الدخول"
    elif reason == "time_stop":
        header  = "⏰ <b>وقف خسارة — انقضى الوقت</b>"
        action  = "بيع فوري"
        detail  = f"الدقيقة {minute} — لا يوجد هدف"
    elif reason == "take_profit":
        header  = "🟢 <b>أخذ الأرباح — هدف سُجِّل</b>"
        action  = "بيع فوري"
        detail  = f"السعر قفز فوق {GOAL_PRICE_SPIKE}¢"
    else:
        header  = "⚠️ تنبيه"
        action  = "راجع الصفقة"
        detail  = reason

    msg = (
        f"{header}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"🏟️  <b>{name}</b>\n"
        f"💰 السعر الحالي: <b>{price}¢</b>\n"
        f"📥 سعر الدخول:  {entry}¢\n"
        f"📊 الأداء:       {pnl_str}\n"
        f"🎯 الأسهم:       {shares}\n"
        f"⚡ الإجراء:      <b>{action}</b>\n"
        f"📌 السبب:        {detail}\n"
        f"🕐 الوقت:        {time_str}\n"
        f"━━━━━━━━━━━━━━━━━"
    )
    if link:
        msg += f"\n🔗 <a href=\"{link}\">فتح الصفقة</a>"
    return msg

# ─── STATE TRACKING ────────────────────────────────────────────────────────────

# يتتبع الصفقات التي أُرسل لها تنبيه مسبقاً حتى لا نُغرق الشات
_alerted: dict[str, dict] = {}
# { position_id: { "reason": str, "timestamp": float } }

def should_alert(pid: str, reason: str) -> bool:
    """هل يجب إرسال التنبيه؟ (تجنب التكرار خلال ALERT_COOLDOWN)."""
    now = time.time()
    prev = _alerted.get(pid)
    if prev and prev["reason"] == reason and (now - prev["timestamp"]) < ALERT_COOLDOWN:
        return False
    return True

def mark_alerted(pid: str, reason: str):
    _alerted[pid] = {"reason": reason, "timestamp": time.time()}

# ─── CORE LOGIC ────────────────────────────────────────────────────────────────

def check_hybrid_stoploss(pos: dict, price: float) -> str | None:
    """
    يطبق Hybrid Stop-Loss ويعيد سبب الخروج أو None إذا لم يتحقق شيء.
    الأولوية: Take Profit > Price Stop > Time Stop
    """
    entry = float(pos.get("buy_price", 0))

    # ── الشرط C: Take Profit (هدف مُسجَّل) ────────────────────────────────
    if price >= GOAL_PRICE_SPIKE:
        return "take_profit"

    # ── الشرط A: Price-Based Stop ────────────────────────────────────────
    if entry and price <= (entry - PRICE_STOP_DROP):
        return "price_stop"

    # ── الشرط B: Time-Based Stop ─────────────────────────────────────────
    minute = get_match_minute(pos)
    if minute is not None and minute >= TIME_STOP_MINUTE:
        # لو وصل السعر أصلاً فوق 80¢ في مرحلة ما، ربما سقط لاحقاً
        # لكن إذا السعر أقل من 80¢ الآن والوقت انتهى → اخرج
        if price < GOAL_PRICE_SPIKE:
            return "time_stop"

    return None

# ─── MAIN LOOP ─────────────────────────────────────────────────────────────────

def load_config():
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def main():
    print("=" * 55)
    print("Polymarket Hybrid Monitor — Telegram Alerts")
    print(f"فحص كل {CHECK_INTERVAL}s | Price Stop: {PRICE_STOP_DROP}¢ | Time Stop: د{TIME_STOP_MINUTE}")
    print("=" * 55)

    # تنبيه افتتاحي
    send_telegram(
        "✅ <b>البوت شغّال</b>\n"
        f"🔴 Price Stop: -{PRICE_STOP_DROP}¢ من الدخول\n"
        f"⏰ Time Stop:  الدقيقة {TIME_STOP_MINUTE} بدون هدف\n"
        f"🟢 Take Profit: {GOAL_PRICE_SPIKE}¢+"
    )

    while True:
        try:
            positions = load_config()
        except FileNotFoundError:
            print("[ERROR] config.json غير موجود!")
            time.sleep(60)
            continue

        active = [p for p in positions if not p.get("closed", False)]
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{ts}] فحص {len(active)} صفقة...")

        for pos in active:
            pid   = pos.get("id", pos.get("name", "unknown"))
            price = get_price(pos)

            if price is None:
                print(f"  ⚠️  {pos.get('name')}: تعذر جلب السعر")
                continue

            entry  = pos.get("buy_price", "—")
            minute = get_match_minute(pos)
            min_str = f"د{minute}" if minute is not None else "—"
            print(f"  {pos.get('name')}: {price}¢  (دخول:{entry}¢ | {min_str})")

            # ── تطبيق Hybrid Stop-Loss ──────────────────────────────────
            reason = check_hybrid_stoploss(pos, price)

            if reason and should_alert(pid, reason):
                msg = format_alert(pos, price, reason, minute)
                if send_telegram(msg):
                    mark_alerted(pid, reason)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
