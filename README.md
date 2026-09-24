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

## 📊 الأسواق المدعومة

- Bitcoin Daily (يومي)
- Bitcoin Weekly (أسبوعي)
- Fed Rates (قرارات البنك الفيدرالي)

## 🌐 النشر على Render

أضف متغيرات البيئة في الإعدادات وادفع الكود.

---

**الإصدار:** 1.0.0  
**آخر تحديث:** سبتمبر 2026
