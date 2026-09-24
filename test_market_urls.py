#!/usr/bin/env python3
"""
اختبار بناء روابط الأسواق الموثوقة
"""

from polymarket_service import PolymarketService

print("\n" + "="*70)
print("🔗 اختبار روابط الأسواق الموثوقة")
print("="*70 + "\n")

service = PolymarketService()

# اختبار الدالة الموثوقة get_reliable_market_url
print("1️⃣  اختبار get_reliable_market_url (الدالة الموثوقة):\n")

reliable_tests = [
    {
        "name": "مع slug",
        "market_id": "123",
        "slug": "bitcoin-daily",
        "expected": "https://polymarket.com/market/bitcoin-daily"
    },
    {
        "name": "بدون slug (استخدم ID)",
        "market_id": "456",
        "slug": "",
        "expected": "https://polymarket.com/market/456"
    },
    {
        "name": "بدون معرف",
        "market_id": "",
        "slug": "",
        "expected": "https://polymarket.com"
    }
]

for test in reliable_tests:
    url = service.get_reliable_market_url(test["market_id"], test["slug"])
    status = "✅" if url == test["expected"] else "❌"
    print(f"{status} {test['name']}")
    print(f"   النتيجة: {url}")
    print()

# اختبار الدالة build_market_url (مع بديل البحث)
print("\n2️⃣  اختبار build_market_url (مع خيارات بديلة):\n")

build_tests = [
    {
        "name": "مع slug فقط",
        "market": {
            "id": "123",
            "slug": "bitcoin-daily",
            "question": "هل سيتجاوز البيتكوين 115,000؟"
        }
    },
    {
        "name": "مع URL مباشر",
        "market": {
            "id": "456",
            "url": "https://polymarket.com/market/will-bitcoin-exceed",
            "question": "هل سيتجاوز البيتكوين 115,000؟"
        }
    },
    {
        "name": "بدون slug - مع ID",
        "market": {
            "id": "789",
            "slug": "",
            "question": "هل سيتجاوز البيتكوين 115,000؟"
        }
    },
    {
        "name": "بدون معرف - مع سؤال",
        "market": {
            "id": "",
            "slug": "",
            "question": "هل سيتجاوز البيتكوين 115,000؟"
        }
    }
]

for test in build_tests:
    url = service.build_market_url(test["market"])
    is_valid = url != "https://polymarket.com" or "search" in url or "question" in test["market"]
    status = "✅" if is_valid else "⚠️"
    print(f"{status} {test['name']}")
    print(f"   الرابط: {url[:70]}...")
    print()

print("="*70)
print("✅ انتهى اختبار الروابط الموثوقة")
print("="*70 + "\n")
