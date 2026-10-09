# 🧪 دليل الاختبارات

## اختبارات الوحدة (بدون إنترنت)

```bash
python -m unittest test_alerts.py test_trading.py test_paper.py test_exposure.py test_match.py test_alert_memory.py
```

**ماذا تختبر:** المراقب، والتنبيهات، وقراءة الصفقات من Data API v2، وزر البيع في تيليجرام، والبيع من محفظة البوت، والتداول على الورق وحفظ سجله، ومراجعة تنبيهات الوقف والهدف، وتنبيه حجم الصفقة، واختبار الوقف المختلط للمباريات. كل الاتصالات الخارجية فيها وهمية، فلا ترسل شيئاً ولا تبيع شيئاً.

**الوقت:** أقل من ثانية ⚡

---

## اختبار محلي سريع (بدون إنترنت)

```bash
python test_local.py
```

**ماذا يختبر:**
- ✅ استيراد جميع الوحدات
- ✅ الإعدادات والثوابت
- ✅ منطق `PolymarketService` (بيانات وهمية)
- ✅ بناء المطالبات للـ AI
- ✅ تطبيق Flask والمسارات
- ✅ الأمان (عدم وجود مفاتيح مباشرة)

**الوقت:** ~5 ثواني ⚡

---

## اختبار كامل مع APIs (يحتاج إنترنت)

```bash
python test_apis.py
```

**ماذا يختبر:**
- ✅ فحص متغيرات البيئة
- ✅ الاتصال بـ Polymarket Gamma API
- ✅ جلب بيانات أسواق حقيقية
- ✅ تحليل Claude
- ✅ تحليل Gemini
- ✅ تطبيق Flask

**المتطلبات:**
1. اتصال بالإنترنت
2. مفاتيح API صحيحة في `.env`:
   ```bash
   CLAUDE_API_KEY=sk-ant-...
   GEMINI_API_KEY=AIzaSy...
   ```

**الوقت:** ~30 ثانية ⏱️

---

## تشخيص سريع

```bash
python diagnose.py
```

**ماذا يفحص:**
- ✅ المتغيرات البيئية
- ✅ الاتصال بالإنترنت
- ✅ Polymarket API
- ✅ Claude API
- ✅ Gemini API
- ✅ Flask
- ✅ المكتبات

---

## تشغيل التطبيق

### محلياً

```bash
# 1. إعداد البيئة
pip install -r requirements.txt
cp .env.example .env

# 2. أضف القيم في .env
nano .env

# 3. شغّل التطبيق
python polymarket_bot.py

# 4. افتح المتصفح
open http://localhost:5000
```

لا تستخدم محلياً نفس `TELEGRAM_BOT_TOKEN` الذي يعمل على Render، أو أضف `ENABLE_MONITOR=0`. التفاصيل في README.

### على Render

1. أضف متغيرات البيئة في **Environment**. القائمة في README، قسم "متغيرات البيئة".
2. ادمج التعديلات في فرع `monitor-branch`، وRender ينشرها تلقائياً.

---

## اختبار اليد (Manual Testing)

### 1. الصفحة الرئيسية
- [ ] افتح http://localhost:5000
- [ ] تحقق من ظهور الصفقات والأسعار والعربية

### 2. واجهات API
- [ ] `/api/positions` ترجع الصفقات بصيغة JSON
- [ ] `/api/alerts/status` تُظهر أن المراقب يعمل (`running: true`) ووقت آخر فحص

### 3. تيليجرام (على النسخة المنشورة)
- [ ] أرسل `/positions` من زر **Menu**، ويجب أن يصل رد
- [ ] جرّب زر البيع في وضع التجربة (`TRADING_DRY_RUN` غير مضبوط أو `1`)

---

## معلومات عن الاختبارات المحلية ✅

```
✅ استيراد الوحدات: نجاح
✅ الإعدادات: 3 أسواق
✅ PolymarketService: يعمل
✅ AIAnalyzer: يعمل
✅ Flask: يعمل
✅ الأمان: نعم
```

### بيانات الاختبار الوهمية

```json
{
  "question": "هل سيتجاوز البيتكوين 115,000 دولار؟",
  "prices": {
    "Yes": 0.65,
    "No": 0.35
  },
  "total_liquidity": 8000,
  "volume": 5000,
  "time_remaining_seconds": 86400
}
```

---

## استكشاف الأخطاء 🐛

### الخطأ: "الاتصال مرفوع"
```
❌ ProxyError: Unable to connect to proxy
```
**الحل:** هذا طبيعي في بيئة محلية مقيدة. استخدم `test_local.py` بدلاً من `test_apis.py`.

### الخطأ: "مفتاح API غير موجود"
```
❌ CLAUDE_API_KEY: غير موجود
```
**الحل:** أضف المفاتيح في `.env`:
```bash
cp .env.example .env
nano .env
```

### الخطأ: "لم يتم العثور على وحدة"
```
❌ ModuleNotFoundError: No module named 'flask'
```
**الحل:** ثبت المكتبات:
```bash
pip install -r requirements.txt
```

---

## قبل الدمج

لا يوجد CI في هذا المستودع، فلا تُشغَّل الاختبارات تلقائياً. شغّل اختبارات الوحدة بنفسك قبل الدمج في `monitor-branch`، لأن Render ينشر كل دمج فوراً:

```bash
python -m unittest test_alerts.py test_trading.py test_paper.py test_exposure.py test_match.py test_alert_memory.py
```

---

## نصائح الاختبار 💡

1. **اختبر المحلي أولاً**: استخدم `test_local.py`
2. **اختبر الـ UI يدوياً**: تفاعل مع الواجهة مباشرة
3. **اختبر معالجة الأخطاء**: حاول إرسال بيانات خاطئة
4. **اختبر الأمان**: تأكد من عدم وجود مفاتيح في الكود

---

**آخر تحديث:** أكتوبر 2026
