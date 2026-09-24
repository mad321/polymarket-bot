#!/usr/bin/env python3
"""
اختبار شامل لجميع الـ APIs والاتصالات
"""

import os
import sys
import logging
from dotenv import load_dotenv
from datetime import datetime

# إعداد الـ logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# تحميل متغيرات البيئة
load_dotenv()

print("\n" + "="*60)
print("🧪 اختبار نظام التداول الثنائي")
print("="*60 + "\n")

# ===== 1. اختبار الإعدادات =====
print("📋 1. فحص الإعدادات والمفاتيح:")
print("-" * 60)

try:
    from config import (
        CLAUDE_API_KEY,
        GEMINI_API_KEY,
        POLYMARKET_HOST,
        GAMMA_API_URL,
        ALLOWED_MARKETS,
        TIME_BUFFER_DAILY,
        TIME_BUFFER_WEEKLY
    )

    print(f"✅ Polymarket Host: {POLYMARKET_HOST}")
    print(f"✅ Gamma API URL: {GAMMA_API_URL}")
    print(f"✅ Time Buffer Daily: {TIME_BUFFER_DAILY / 3600:.0f} ساعات")
    print(f"✅ Time Buffer Weekly: {TIME_BUFFER_WEEKLY / (24*3600):.0f} أيام")
    print(f"✅ الأسواق المتاحة: {', '.join(ALLOWED_MARKETS.keys())}")

    # التحقق من المفاتيح
    claude_status = "✅ موجود" if CLAUDE_API_KEY else "❌ غير موجود"
    gemini_status = "✅ موجود" if GEMINI_API_KEY else "❌ غير موجود"

    print(f"\n🔑 المفاتيح:")
    print(f"   Claude API: {claude_status}")
    print(f"   Gemini API: {gemini_status}")

except Exception as e:
    logger.error(f"❌ خطأ في تحميل الإعدادات: {e}")
    sys.exit(1)

# ===== 2. اختبار Polymarket API =====
print("\n\n🌐 2. اختبار Polymarket Gamma API:")
print("-" * 60)

try:
    from polymarket_service import PolymarketService

    pm = PolymarketService()
    print("✅ تم تهيئة PolymarketService")

    # اختبار البحث عن السوق
    print("\n🔍 البحث عن أسواق Bitcoin...")
    markets = pm.search_markets("bitcoin", limit=3)

    if markets:
        print(f"✅ تم العثور على {len(markets)} سوق:")
        for i, market in enumerate(markets[:3], 1):
            print(f"\n   [{i}] {market.get('question', 'N/A')[:60]}...")
            print(f"       الـ Slug: {market.get('slug', 'N/A')}")
            print(f"       الحالة: {'نشط' if market.get('active') else 'غير نشط'}")

            # اختبار جلب التفاصيل
            if i == 1:
                slug = market.get("slug")
                if slug:
                    print(f"\n   🔎 جلب التفاصيل من {slug}...")
                    details = pm.get_market_by_slug(slug)
                    if details:
                        print(f"   ✅ تم الحصول على التفاصيل")
                        print(f"      - السؤال: {details.get('question', 'N/A')[:50]}...")
                        print(f"      - تاريخ الإغلاق: {details.get('endDate', 'N/A')}")
                        print(f"      - النتائج: {len(details.get('outcomes', []))} خيارات")

                        # استخراج البيانات الحية
                        market_data = pm.extract_live_market_data(details)
                        print(f"\n   ✅ البيانات الحية المستخرجة:")
                        print(f"      - السيولة: ${market_data.get('total_liquidity', 0):.2f}")
                        print(f"      - الحجم: ${market_data.get('volume', 0):.2f}")
                        print(f"      - الأسعار: {market_data.get('prices', {})}")
                        print(f"      - الوقت المتبقي: {market_data.get('time_remaining_seconds', 0) / 3600:.2f} ساعة")

                        # اختبار التحقق
                        is_valid, msg = pm.validate_trading_opportunity(market_data, "daily")
                        print(f"\n   🎯 التحقق من صحة التداول:")
                        print(f"      - الحالة: {'✅ صالح' if is_valid else '❌ غير صالح'}")
                        print(f"      - الرسالة: {msg}")
    else:
        print("❌ لم يتم العثور على أي أسواق")

except Exception as e:
    logger.error(f"❌ خطأ في اختبار Polymarket: {e}", exc_info=True)

# ===== 3. اختبار Claude API =====
print("\n\n🤖 3. اختبار Claude API:")
print("-" * 60)

if CLAUDE_API_KEY:
    try:
        from ai_analysis import AIAnalyzer

        analyzer = AIAnalyzer()
        print("✅ تم تهيئة AIAnalyzer")

        # بيانات اختبار وهمية
        test_market_data = {
            "question": "هل سيتجاوز سعر البيتكوين 115,000 دولار بحلول غداً؟",
            "prices": {"Yes": 0.65, "No": 0.35},
            "volume": 5000,
            "volume_7d": 25000,
            "total_liquidity": 8000,
            "time_remaining_seconds": 86400
        }

        print(f"\n📝 اختبار مطالبة التحليل:")
        prompt = analyzer.build_analysis_prompt(test_market_data)
        print(f"   ✅ تم بناء المطالبة ({len(prompt)} حرف)")

        print(f"\n🔄 استدعاء Claude API...")
        result = analyzer.get_claude_analysis(test_market_data)

        if result["status"] == "success":
            print(f"   ✅ تم الحصول على التحليل")
            print(f"   📊 الرموز المستخدمة: {result.get('tokens_used', 0)}")
            print(f"   📄 أول 200 حرف من التحليل:")
            print(f"      {result['analysis'][:200]}...")
        else:
            print(f"   ❌ خطأ: {result.get('message')}")

    except Exception as e:
        logger.error(f"❌ خطأ في اختبار Claude: {e}", exc_info=True)
else:
    print("⚠️  مفتاح Claude API غير موجود - تخطي الاختبار")

# ===== 4. اختبار Gemini API =====
print("\n\n✨ 4. اختبار Gemini API:")
print("-" * 60)

if GEMINI_API_KEY:
    try:
        from ai_analysis import AIAnalyzer

        analyzer = AIAnalyzer()

        # بيانات اختبار وهمية
        test_market_data = {
            "question": "هل سيتجاوز سعر البيتكوين 115,000 دولار بحلول غداً؟",
            "prices": {"Yes": 0.65, "No": 0.35},
            "volume": 5000,
            "volume_7d": 25000,
            "total_liquidity": 8000,
            "time_remaining_seconds": 86400
        }

        print(f"🔄 استدعاء Gemini API...")
        result = analyzer.get_gemini_analysis(test_market_data)

        if result["status"] == "success":
            print(f"   ✅ تم الحصول على التحليل")
            print(f"   📊 الرموز المستخدمة: {result.get('tokens_used', 0)}")
            print(f"   📄 أول 200 حرف من التحليل:")
            print(f"      {result['analysis'][:200]}...")
        else:
            print(f"   ❌ خطأ: {result.get('message')}")

    except Exception as e:
        logger.error(f"❌ خطأ في اختبار Gemini: {e}", exc_info=True)
else:
    print("⚠️  مفتاح Gemini API غير موجود - تخطي الاختبار")

# ===== 5. اختبار التطبيق =====
print("\n\n🚀 5. اختبار التطبيق Flask:")
print("-" * 60)

try:
    from app import app

    print("✅ تم تحميل تطبيق Flask")

    # اختبار المسارات
    with app.test_client() as client:
        print("\n🔍 اختبار المسارات:")

        # اختبار الصفحة الرئيسية
        print("\n   GET /")
        response = client.get("/")
        if response.status_code == 200:
            print(f"   ✅ حالة 200 OK")
            if "حلبة الذكاء الاصطناعي" in response.get_data(as_text=True):
                print(f"   ✅ الواجهة العربية موجودة")
        else:
            print(f"   ❌ خطأ: حالة {response.status_code}")

        # اختبار health check
        print("\n   GET /health")
        response = client.get("/health")
        if response.status_code == 200:
            print(f"   ✅ حالة 200 OK")
            data = response.get_json()
            print(f"   ✅ الحالة: {data.get('status')}")
        else:
            print(f"   ❌ خطأ: حالة {response.status_code}")

except Exception as e:
    logger.error(f"❌ خطأ في اختبار التطبيق: {e}", exc_info=True)

# ===== ملخص =====
print("\n\n" + "="*60)
print("✅ انتهى الاختبار")
print("="*60)
print("\n📋 الخطوات التالية:")
print("   1. تأكد من ملء جميع المفاتيح في ملف .env")
print("   2. شغّل التطبيق: python app.py")
print("   3. افتح المتصفح على: http://localhost:5000")
print("   4. اختر السوق المطلوب والاستعلام\n")
