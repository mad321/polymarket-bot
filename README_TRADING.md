# 🏛️ Dual-AI Trading Arena

نظام تداول متقدم يجلب بيانات حية من Polymarket ويحللها باستخدام Claude و Gemini.

## ✨ المميزات الأساسية

- **جلب بيانات حية من Polymarket**: اتصال مباشر مع Gamma API
- **تحليل ذكي ثنائي**: تحليلات من Claude Haiku و Gemini Flash
- **التحقق من فرص التداول**: معايير صارمة للسيولة والوقت المتبقي
- **واجهة عربية كاملة**: RTL Layout مع دعم كامل للعربية
- **API endpoints**: للتكامل مع أنظمة أخرى

## 🏗️ البنية المعمارية

```
arduino-day/
├── app.py                    # تطبيق Flask الرئيسي
├── config.py                 # الإعدادات والمفاتيح
├── polymarket_service.py     # خدمة Polymarket API
├── ai_analysis.py            # محلل الذكاء الاصطناعي
├── requirements.txt          # المكتبات المطلوبة
├── .env.example              # قالب متغيرات البيئة
└── README_TRADING.md         # هذا الملف
```

## 📋 المتطلبات

- Python 3.8+
- API Keys من:
  - [Anthropic (Claude)](https://console.anthropic.com)
  - [Google (Gemini)](https://ai.google.dev)

## 🚀 التثبيت والتشغيل

### 1. استنساخ المشروع
```bash
git clone https://github.com/mad321/arduino-day.git
cd arduino-day
```

### 2. تثبيت المكتبات
```bash
pip install -r requirements.txt
```

### 3. إعداد المتغيرات البيئية
```bash
cp .env.example .env
# ثم عدّل .env وأضف مفاتيحك
```

### 4. تشغيل التطبيق
```bash
# في بيئة التطوير
FLASK_ENV=development python app.py

# أو في بيئة الإنتاج
python app.py
```

سيكون التطبيق متاحاً على: `http://localhost:5000`

## 📊 الأسواق المدعومة

| السوق | النوع | الوصف |
|------|------|-------|
| Bitcoin Daily | يومي | تنبؤات يومية بسعر البيتكوين |
| Bitcoin Weekly | أسبوعي | تنبؤات أسبوعية بسعر البيتكوين |
| Fed Rates | يومي | قرارات البنك الفيدرالي الأمريكي |

## 🎯 معايير التداول

### متطلبات الوقت
- **صفقات يومية**: 12 ساعة على الأقل متبقية
- **صفقات أسبوعية**: 3 أيام على الأقل متبقية

### معايير السيولة
- **الحد الأدنى**: $100 سيولة إجمالية

## 🔄 تدفق العمل

```
1. اختيار السوق
   ↓
2. جلب بيانات حية من Polymarket
   ↓
3. التحقق من معايير التداول
   ↓
4. تحليل السوق بـ Claude و Gemini
   ↓
5. عرض التوصيات والتحليلات
   ↓
6. توفير رابط مباشر للسوق
```

## 📈 بيانات السوق المعروضة

- **السؤال**: نص السوق الكامل
- **الحالة**: نشط / مغلق
- **السيولة الإجمالية**: إجمالي السيولة المتاحة
- **الحجم (24 ساعة)**: حجم التداول اليومي
- **الحجم (7 أيام)**: حجم التداول الأسبوعي
- **الوقت المتبقي**: الوقت قبل إغلاق السوق
- **الأسعار الحية**: أسعار كل خيار

## 🤖 التحليلات الذكية

### Claude Haiku
- تحليل عميق لديناميات السوق
- توقعات احتمالية
- تقييم المخاطر
- توصيات الشراء

### Gemini Flash
- تحليل سريع للسوق
- تقييم الفرص
- استراتيجيات دخول
- حسابات العوائد المتوقعة

## 🔌 API Endpoints

### جلب بيانات السوق
```bash
GET /api/market/<market_slug>
```

**الرد:**
```json
{
  "market_id": "...",
  "question": "...",
  "direct_url": "https://polymarket.com/market/...",
  "prices": {
    "Yes": 0.65,
    "No": 0.35
  },
  "total_liquidity": 5000,
  "time_remaining_seconds": 86400
}
```

### جلب التحليلات
```bash
GET /api/analysis/<market_slug>
```

### فحص صحة التطبيق
```bash
GET /health
```

## ⚙️ متغيرات البيئة

| المتغير | الوصف | إجباري |
|---------|-------|--------|
| `CLAUDE_API_KEY` | مفتاح Anthropic API | نعم |
| `GEMINI_API_KEY` | مفتاح Google API | نعم |
| `PRIVATE_KEY` | مفتاح محفظة Polymarket | لا |
| `WALLET_ADDRESS` | عنوان المحفظة | لا |
| `PORT` | منفذ التطبيق | لا (افتراضي: 5000) |
| `FLASK_ENV` | بيئة التطوير/الإنتاج | لا |

## 🔒 الأمان

- **لا تخزن المفاتيح في الكود**: استخدم ملف `.env`
- **لا تشارك `.env`**: أضفه إلى `.gitignore`
- **مفاتيح API آمنة**: استخدم متغيرات البيئة في الإنتاج

## 📝 معالجة الأخطاء

النظام يتعامل تلقائياً مع:
- فشل اتصالات API
- بيانات سوق ناقصة
- أسواق مغلقة أو راكدة
- عدم توفر المفاتيح

## 🚀 النشر على Render

```bash
# الملف: render.yaml
services:
  - type: web
    name: dual-ai-trading
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: python app.py
```

## 📚 المراجع

- [Polymarket Gamma API](https://gamma-api.polymarket.com)
- [Anthropic Claude API](https://docs.anthropic.com)
- [Google Generative AI](https://ai.google.dev)
- [Flask Documentation](https://flask.palletsprojects.com)

## 🐛 استكشاف الأخطاء

### "مفتاح API غير مسجل"
تأكد من إضافة المفاتيح في ملف `.env`

### "لم يتم العثور على أسواق"
تحقق من اتصالك بالإنترنت أو جرّب اسم بحث مختلف

### الأسعار لا تتحدث
تأكد من أن الـ API قيد التشغيل وأن السوق نشط

## 📞 الدعم

للإبلاغ عن مشاكل أو الحصول على المساعدة:
- فتح issue على GitHub
- التحقق من logs التطبيق

## 📄 الترخيص

هذا المشروع مفتوح المصدر ومتاح للاستخدام التعليمي والتجاري.

---

**آخر تحديث**: سبتمبر 2026
