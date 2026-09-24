#!/usr/bin/env python3
"""
تشخيص سريع لاختبار الاتصالات والمشاكل
"""

import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

print("\n" + "="*70)
print("🔧 تشخيص نظام التداول")
print("="*70 + "\n")

# 1. فحص المفاتيح
print("1️⃣  فحص المتغيرات البيئية:")
print("-" * 70)

checks = {
    "CLAUDE_API_KEY": os.environ.get("CLAUDE_API_KEY"),
    "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY"),
    "PRIVATE_KEY": os.environ.get("PRIVATE_KEY"),
    "WALLET_ADDRESS": os.environ.get("WALLET_ADDRESS")
}

for key, value in checks.items():
    if value:
        masked = value[:10] + "..." + value[-10:] if len(str(value)) > 20 else value
        print(f"   ✅ {key}: {masked}")
    else:
        print(f"   ⚠️  {key}: غير موجود")

# 2. اختبار الاتصال بالإنترنت
print("\n\n2️⃣  فحص الاتصال بالإنترنت:")
print("-" * 70)

try:
    response = requests.get("https://www.google.com", timeout=5)
    print(f"   ✅ الاتصال متاح (Google)")
except:
    print(f"   ❌ لا يوجد اتصال بالإنترنت")

# 3. اختبار Gamma API
print("\n\n3️⃣  فحص Polymarket Gamma API:")
print("-" * 70)

try:
    url = "https://gamma-api.polymarket.com/markets/search"
    params = {"query": "bitcoin", "limit": 1}
    response = requests.get(url, params=params, timeout=10)

    if response.status_code == 200:
        data = response.json()
        print(f"   ✅ API متاح")
        print(f"   ✅ البحث عن 'bitcoin' أرجع {len(data)} نتائج")
        if data:
            print(f"   📊 أول سوق: {data[0].get('question', 'N/A')[:50]}...")
    else:
        print(f"   ❌ خطأ: الحالة {response.status_code}")
except requests.exceptions.Timeout:
    print(f"   ❌ انقطع الاتصال (Timeout)")
except requests.exceptions.ConnectionError:
    print(f"   ❌ لم يتم الوصول للـ API")
except Exception as e:
    print(f"   ❌ خطأ: {e}")

# 4. اختبار Claude API
print("\n\n4️⃣  فحص Claude API:")
print("-" * 70)

claude_key = os.environ.get("CLAUDE_API_KEY")
if not claude_key:
    print(f"   ⚠️  المفتاح غير موجود")
else:
    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=claude_key)
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=100,
            messages=[{"role": "user", "content": "مرحباً"}]
        )
        print(f"   ✅ API متاح")
        print(f"   📝 الرد: {response.content[0].text[:50]}...")
    except Exception as e:
        print(f"   ❌ خطأ: {str(e)[:100]}")

# 5. اختبار Gemini API
print("\n\n5️⃣  فحص Gemini API:")
print("-" * 70)

gemini_key = os.environ.get("GEMINI_API_KEY")
if not gemini_key:
    print(f"   ⚠️  المفتاح غير موجود")
else:
    try:
        import google.generativeai as genai

        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content("مرحباً")
        print(f"   ✅ API متاح")
        print(f"   📝 الرد: {response.text[:50]}...")
    except Exception as e:
        print(f"   ❌ خطأ: {str(e)[:100]}")

# 6. اختبار Flask
print("\n\n6️⃣  فحص Flask والتطبيق:")
print("-" * 70)

try:
    from app import app
    print(f"   ✅ تطبيق Flask يُحمّل بنجاح")

    # اختبار الطلب
    with app.test_client() as client:
        response = client.get("/health")
        if response.status_code == 200:
            print(f"   ✅ Endpoint /health يعمل")
        else:
            print(f"   ⚠️  /health أرجع حالة {response.status_code}")
except Exception as e:
    print(f"   ❌ خطأ في تحميل التطبيق: {e}")

# 7. المتطلبات
print("\n\n7️⃣  فحص المكتبات:")
print("-" * 70)

libs = {
    "flask": "Flask",
    "requests": "requests",
    "anthropic": "Anthropic",
    "google.generativeai": "Google Generative AI",
    "dotenv": "python-dotenv"
}

for lib, name in libs.items():
    try:
        __import__(lib)
        print(f"   ✅ {name}")
    except ImportError:
        print(f"   ❌ {name} (تثبيت: pip install -r requirements.txt)")

# ملخص
print("\n\n" + "="*70)
print("📋 الملخص والتوصيات:")
print("="*70)

print("""
✅ إذا مرّت جميع الاختبارات:
   → الكود جاهز للتشغيل
   → استخدم: python app.py
   → افتح: http://localhost:5000

❌ إذا فشل أي اختبار:
   → تحقق من ملف .env
   → تأكد من توفر المفاتيح
   → تحقق من الاتصال بالإنترنت
   → تحقق من انتهاء صلاحية المفاتيح

⚠️  للمزيد من التفاصيل:
   → شغّل: python test_apis.py
   → راجع logs في التطبيق
""")

print("="*70 + "\n")
