# 🏛️ Dual-AI Trading Arena

نظام تداول متقدم يجلب بيانات حية من Polymarket ويحللها باستخدام Claude و Gemini.

## ✨ المميزات

- **جلب بيانات حية من Polymarket**: الاتصال المباشر مع Gamma API
- **تحليل ذكي ثنائي**: Claude Haiku و Gemini Flash
- **معايير تداول صارمة**: التحقق من السيولة والوقت المتبقي
- **واجهة عربية كاملة**: RTL Layout مع دعم شامل
- **API endpoints**: للتكامل مع أنظمة أخرى

## 🚀 البدء السريع

```bash
# 1. استنساخ المشروع
git clone https://github.com/mad321/polymarket-bot.git
cd polymarket-bot

# 2. تثبيت المكتبات
pip install -r requirements.txt

# 3. إعداد المفاتيح
cp .env.example .env
# عدّل .env وأضف المفاتيح

# 4. التشغيل
python app.py
```

التطبيق يعمل على: **http://localhost:5000**

## 📚 الملفات الرئيسية

- `app.py` - تطبيق Flask الرئيسي
- `config.py` - الإعدادات والثوابت
- `polymarket_service.py` - خدمة Polymarket API
- `ai_analysis.py` - تحليلات Claude و Gemini
- `requirements.txt` - المكتبات المطلوبة

## 🧪 الاختبارات

```bash
# اختبار محلي بدون إنترنت
python test_local.py

# اختبار كامل مع APIs
python test_apis.py

# تشخيص سريع
python diagnose.py
```

## 📖 التوثيق

- [README_TRADING.md](README_TRADING.md) - دليل شامل
- [TESTING.md](TESTING.md) - دليل الاختبارات

## 🔑 متغيرات البيئة المطلوبة

```
CLAUDE_API_KEY=your_key_here
GEMINI_API_KEY=your_key_here
PRIVATE_KEY=your_key_here (اختياري)
WALLET_ADDRESS=your_address_here (اختياري)
```

## 🔔 تنبيهات تيليجرام

المراقب يفحص الصفقات كل 30 ثانية، ويرسل تنبيهاً عندما يصل السعر لوقف الخسارة أو الهدف. هو يرسل تنبيهات فقط ولا يبيع.

1. في تيليجرام افتح **@BotFather** وأرسل `/newbot`، ثم اختر اسماً للبوت. سيعطيك رمزاً (token) مثل `123456:ABC...`.
2. افتح البوت الجديد واضغط **Start**.
3. افتح في المتصفح `https://api.telegram.org/bot<الرمز>/getUpdates` بعد وضع رمزك مكان `<الرمز>`، وانسخ الرقم الذي بعد `"chat":{"id":`.
4. في Render أضف `TELEGRAM_BOT_TOKEN` و`TELEGRAM_CHAT_ID` في Environment ثم احفظ.

بعد إعادة التشغيل تصلك رسالة "✅ مراقب بوليماركت بدأ العمل". إذا تكررت هذه الرسالة كثيراً فالخادم ينام ويستيقظ، والمراقب لا يعمل وهو نائم.

لمعرفة حالة المراقب افتح `/api/alerts/status`. الصفحة تعرض هل المراقب يعمل، ومتى فحص آخر مرة، وآخر خطأ في الإرسال. لا تظهر فيها أي رموز سرية.

إعدادات اختيارية: `ALERT_COOLDOWN` (ثوانٍ قبل تكرار تنبيه نفس الصفقة، الافتراضي 3600)، `STARTUP_ALERT=0` لإيقاف رسالة البدء، `ALERT_TZ` (الافتراضي `Asia/Riyadh`).

ملاحظة عن واتساب: إذا ضبطت `WHATSAPP_TOKEN` و`PHONE_NUMBER_ID` و`RECIPIENT_PHONE` يرسل البوت لواتساب أيضاً. لكن واتساب لا يوصل الرسائل النصية إلا خلال 24 ساعة من آخر رسالة أرسلتها أنت للرقم، لذلك تيليجرام أضمن.

## 📊 الأسواق المدعومة

- Bitcoin Daily (يومي)
- Bitcoin Weekly (أسبوعي)
- Fed Rates (قرارات البنك الفيدرالي)

## 🌐 النشر على Render

أضف متغيرات البيئة في الإعدادات وادفع الكود.

---

**الإصدار:** 1.0.0  
**آخر تحديث:** سبتمبر 2026
