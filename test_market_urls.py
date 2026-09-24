#!/usr/bin/env python3
"""
اختبار روابط الأسواق - الصيغة الصحيحة
"""

from polymarket_service import PolymarketService

print("\n" + "="*70)
print("🔗 اختبار روابط الأسواق - الصيغة الصحيحة /event/")
print("="*70 + "\n")

service = PolymarketService()

# اختبار الدالة الموثوقة get_reliable_market_url
print("1️⃣  اختبار get_reliable_market_url:\n")

reliable_tests = [
    {
        "name": "مع slug → /event/",
        "market_id": "123",
        "slug": "bitcoin-above-on-september-24-2026",
        "expected": "https://polymarket.com/event/bitcoin-above-on-september-24-2026"
    },
    {
        "name": "بدون slug (استخدم ID)",
        "market_id": "456",
        "slug": "",
        "expected": "https://polymarket.com/market/456"
    }
]

for test in reliable_tests:
    url = service.get_reliable_market_url(test["market_id"], test["slug"])
    status = "✅" if url == test["expected"] else "❌"
    print(f"{status} {test['name']}")
    print(f"   النتيجة: {url}")
    print(f"   المتوقع: {test['expected']}")
    print()

# اختبار الدالة build_market_url
print("\n2️⃣  اختبار build_market_url:\n")

build_tests = [
    {
        "name": "مع slug → /event/",
        "market": {
            "id": "123",
            "slug": "bitcoin-above-on-september-24-2026",
            "question": "Will Bitcoin be above $X?"
        },
        "expected_format": "event"
    },
    {
        "name": "مع events array",
        "market": {
            "id": "789",
            "slug": "",
            "events": [
                {"slug": "bitcoin-above-on-september-24-2026"}
            ],
            "question": "Will Bitcoin be above $X?"
        },
        "expected_format": "event"
    }
]

for test in build_tests:
    url = service.build_market_url(test["market"])
    has_correct_format = test["expected_format"] in url
    status = "✅" if has_correct_format else "❌"
    print(f"{status} {test['name']}")
    print(f"   الرابط: {url}")
    print()

print("="*70)
print("✅ انتهى اختبار الروابط - الصيغة الصحيحة")
print("="*70 + "\n")
