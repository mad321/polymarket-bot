import requests
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from config import (
    GAMMA_API_URL,
    TIME_BUFFER_DAILY,
    TIME_BUFFER_WEEKLY,
    MIN_LIQUIDITY_THRESHOLD
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PolymarketService:
    """خدمة جلب البيانات الحية من Polymarket"""

    def __init__(self):
        self.gamma_url = GAMMA_API_URL
        self.session = requests.Session()

    def build_market_url(self, market: Dict) -> str:
        """بناء رابط صحيح للسوق من بيانات API"""
        # الأولوية: استخدام الرابط الموجود مباشرة
        if market.get("url"):
            return market.get("url")

        # محاولة بناء الرابط من الـ slug
        slug = market.get("slug", "")
        if slug:
            return f"https://polymarket.com/market/{slug}"

        # محاولة بناء الرابط من المعرّف
        market_id = market.get("id", "")
        if market_id:
            return f"https://polymarket.com/market/{market_id}"

        # البحث في events
        events = market.get("events", [])
        if events:
            event_slug = events[0].get("slug", "")
            if event_slug:
                return f"https://polymarket.com/event/{event_slug}"

        return "https://polymarket.com"

    def search_markets(self, query: str, limit: int = 10) -> List[Dict]:
        """البحث عن الأسواق بناءً على الاستعلام"""
        try:
            url = f"{self.gamma_url}/markets/search"
            params = {"query": query, "limit": limit}
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            markets = response.json()
            logger.info(f"وجدت {len(markets)} سوق للاستعلام: {query}")
            return markets
        except requests.RequestException as e:
            logger.error(f"خطأ في البحث عن الأسواق: {e}")
            return []

    def get_market_details(self, market_id: str) -> Optional[Dict]:
        """جلب تفاصيل السوق الكاملة"""
        try:
            url = f"{self.gamma_url}/markets/{market_id}"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            logger.info(f"تم جلب بيانات السوق: {market_id}")
            return data
        except requests.RequestException as e:
            logger.error(f"خطأ في جلب تفاصيل السوق {market_id}: {e}")
            return None

    def get_market_by_slug(self, slug: str) -> Optional[Dict]:
        """جلب بيانات السوق باستخدام الـ slug"""
        try:
            url = f"{self.gamma_url}/markets/{slug}"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"خطأ في جلب السوق {slug}: {e}")
            return None

    def extract_live_market_data(self, market: Dict) -> Dict:
        """استخراج البيانات الحية من السوق"""
        try:
            market_id = market.get("id", "unknown")
            slug = market.get("slug", "")
            question = market.get("question", "")

            # جلب وقت الإغلاق
            close_time_str = market.get("endDate")
            close_time = datetime.fromisoformat(close_time_str.replace("Z", "+00:00")) if close_time_str else None
            time_remaining = (close_time - datetime.now(close_time.tzinfo)).total_seconds() if close_time else 0

            # جلب الأسعار الحية من الخيارات
            outcomes = market.get("outcomes", [])
            prices = {}
            total_liquidity = 0

            for outcome in outcomes:
                outcome_label = outcome.get("label", "")
                price = float(outcome.get("price", 0))
                prices[outcome_label] = price
                total_liquidity += outcome.get("liquidity", 0)

            # بناء الرابط المباشر للسوق باستخدام دالة محسّنة
            direct_url = self.build_market_url(market)

            return {
                "market_id": market_id,
                "slug": slug,
                "question": question,
                "direct_url": direct_url,
                "close_time": close_time,
                "time_remaining_seconds": max(0, time_remaining),
                "prices": prices,
                "total_liquidity": total_liquidity,
                "outcomes": outcomes,
                "is_closed": market.get("closed", False),
                "volume": market.get("volume24h", 0),
                "volume_7d": market.get("volume7d", 0)
            }
        except Exception as e:
            logger.error(f"خطأ في استخراج البيانات: {e}")
            return {}

    def validate_trading_opportunity(
        self,
        market_data: Dict,
        market_type: str
    ) -> tuple[bool, str]:
        """
        التحقق من صحة فرصة التداول
        - هل يوجد وقت كافي قبل الإغلاق؟
        - هل السيولة كافية؟
        - هل السوق نشط؟
        """
        if not market_data:
            return False, "لا توجد بيانات للسوق"

        if market_data.get("is_closed"):
            return False, "السوق مغلق بالفعل"

        time_remaining = market_data.get("time_remaining_seconds", 0)
        time_buffer = TIME_BUFFER_WEEKLY if market_type == "weekly" else TIME_BUFFER_DAILY

        if time_remaining < time_buffer:
            hours_left = time_remaining / 3600
            required_hours = time_buffer / 3600
            return False, f"وقت غير كافي: {hours_left:.1f} ساعة متبقية (مطلوب {required_hours:.0f} ساعة)"

        liquidity = market_data.get("total_liquidity", 0)
        if liquidity < MIN_LIQUIDITY_THRESHOLD:
            return False, f"سيولة غير كافية: ${liquidity:.2f} (مطلوب ${MIN_LIQUIDITY_THRESHOLD})"

        return True, "السوق صالح للتداول"

    def calculate_expected_return(self, entry_price: float, target_price: float) -> float:
        """حساب العائد المتوقع"""
        if entry_price <= 0:
            return 0
        return ((target_price - entry_price) / entry_price) * 100

    def get_market_opportunity(self, market_slug: str, market_type: str) -> Optional[Dict]:
        """جلب فرصة تداول كاملة للسوق"""
        market = self.get_market_by_slug(market_slug)
        if not market:
            return None

        market_data = self.extract_live_market_data(market)
        is_valid, validation_msg = self.validate_trading_opportunity(market_data, market_type)

        if not is_valid:
            market_data["validation_error"] = validation_msg
            return market_data

        market_data["is_valid"] = True
        market_data["validation_msg"] = "✅ السوق صالح للتداول"

        # حساب العوائد المتوقعة (بناءً على أفضل سعر شراء)
        if market_data.get("prices"):
            best_buy_price = min(market_data["prices"].values())
            market_data["best_buy_price"] = best_buy_price
            market_data["estimated_profit_percent"] = self.calculate_expected_return(best_buy_price, 0.95)

        return market_data
