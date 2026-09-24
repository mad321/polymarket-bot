#!/usr/bin/env python3
"""
اختبار بناء روابط الأسواق
"""

from polymarket_service import PolymarketService

print("\n" + "="*70)
print("🔗 اختبار بناء روابط الأسواق")
print("="*70 + "\n")

service = PolymarketService()

# حالات اختبار مختلفة
test_cases = [
    {
        "name": "الحالة 1: مع slug فقط",
        "market": {
            "id": "123",
            "slug": "bitcoin-daily",
            "question": "هل سيتجاوز البيتكوين 115,000؟"
        }
    },
    {
        "name": "الحالة 2: مع URL مباشر",
        "market": {
            "id": "456",
            "url": "https://polymarket.com/market/will-bitcoin-exceed-115000",
            "question": "هل سيتجاوز البيتكوين 115,000؟"
        }
    },
    {
        "name": "الحالة 3: مع event slug",
        "market": {
            "id": "789",
            "slug": "",
            "events": [
                {"slug": "bitcoin-price-targets"}
            ],
            "question": "هل سيتجاوز البيتكوين 115,000؟"
        }
    },
    {
        "name": "الحالة 4: بدون معلومات كافية",
        "market": {
            "id": "999",
            "question": "هل سيتجاوز البيتكوين 115,000؟"
        }
    }
]

print("اختبار بناء الروابط:\n")

for i, test in enumerate(test_cases, 1):
    url = service.build_market_url(test["market"])
    print(f"[{i}] {test['name']}")
    print(f"    الرابط: {url}")
    print(f"    ✅ صحيح" if url != "https://polymarket.com" else f"    ⚠️  افتراضي")
    print()

print("="*70)
print("✅ اختبار الروابط انتهى")
print("="*70 + "\n")
