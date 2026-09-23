import os
import requests
from flask import Flask, jsonify, render_template_string, request
from py_clob_client.client import ClobClient

app = Flask(__name__)

# --- الإعدادات والمفاتيح ---
host = "https://clob.polymarket.com"
chain_id = 137

private_key = os.environ.get("PRIVATE_KEY")
wallet_address = os.environ.get("WALLET_ADDRESS")
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

client = ClobClient(host, key=private_key, chain_id=chain_id)
GAMMA_API_URL = "https://gamma-api.polymarket.com"

# النطاق المتفق عليه (الأسواق المسموحة فقط)
ALLOWED_MARKETS = {
    "bitcoin-up-or-down-today": "Crypto - Bitcoin Daily",
    "fed-interest-rate-decision": "Macro - Fed Rates"
}

def fetch_live_market_data(slug):
    """جلب بيانات السوق الحية من Polymarket Gamma API"""
    try:
        res = requests.get(f"{GAMMA_API_URL}/markets/{slug}", timeout=5)
        if res.status_code == 200:
            data = res.json()
            return {
                "question": data.get("question", slug),
                "active": data.get("active", True),
                "closed": data.get("closed", False),
                "outcomes": data.get("outcomes", ["Yes", "No"])
            }
    except Exception:
        pass
    return {"question": slug, "active": True, "closed": False, "outcomes": ["Yes", "No"]}

def get_claude_analysis(question):
    """استعلام حقيقي من نموذج Claude عبر الـ API"""
    if not CLAUDE_API_KEY:
        return "مفتاح Claude API غير مسجل في متغيرات البيئة."
    try:
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": CLAUDE_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        payload = {
            "model": "claude-3-haiku-20240307",
            "max_tokens": 150,
            "messages": [{"role": "user", "content": f"بصفتك خبير تداول ذكي، قم بتحليل هذا السوق باختصار شديد واعطني توصية (شراء نعم أو لا) مع النسبة المئوية للثقة:\n{question}"}]
        }
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        if res.status_code == 200:
            return res.json()["content"][0]["text"]
        else:
            return f"خطأ في الاتصال بـ Claude API: {res.status_code}"
    except Exception as e:
        return f"فشل الاستعلام: {str(e)}"

def get_gemini_analysis(question):
    """استعلام حقيقي من نموذج Gemini عبر الـ API"""
    if not GEMINI_API_KEY:
        return "مفتاح Gemini API غير مسجل في متغيرات البيئة."
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        headers = {"content-type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": f"بصفتك خبير تداول ذكي، قم بتحليل هذا السوق باختصار شديد واعطني توصية (شراء نعم أو لا) مع النسبة المئوية للثقة:\n{question}"}]}]
        }
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        if res.status_code == 200:
            data = res.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            return f"خطأ في الاتصال بـ Gemini API: {res.status_code}"
    except Exception as e:
        return f"فشل الاستعلام: {str(e)}"

# تصميم الداشبورد المحدث للاستعلامات الحية
DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dual-AI Arena - Live Model Inference</title>
    <style>
        body { font-family: Tahoma, sans-serif; background-color: #f4f7f6; margin: 0; padding: 20px; color: #333; }
        .container { max-width: 1100px; margin: auto; background: #fff; padding: 25px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }
        h1 { color: #2c3e50; text-align: center; margin-bottom: 5px; }
        .subtitle { text-align: center; color: #7f8c8d; margin-bottom: 25px; font-size: 14px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .card { background: #fafafa; border: 1px solid #e1e8ed; border-radius: 8px; padding: 15px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }
        .card h3 { margin-top: 0; color: #2980b9; border-bottom: 2px solid #3498db; padding-bottom: 8px; }
        .metric { margin: 10px 0; font-size: 14px; }
        .badge { display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; }
        .badge-success { background: #2ecc71; color: white; }
        .control-panel { background: #e8f4f8; padding: 15px; border-radius: 8px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; }
        select, button { padding: 8px 12px; border-radius: 5px; border: 1px solid #bdc3c7; font-family: Tahoma; }
        .btn-action { background: #2980b9; color: white; border: none; cursor: pointer; }
        .btn-action:hover { background: #1f618d; }
        .ai-response { background: #fff; border: 1px solid #3498db; padding: 12px; border-radius: 6px; margin-top: 10px; font-size: 13px; white-space: pre-wrap; line-height: 1.6; }
        .live-market-info { background: #fff8e1; padding: 12px; border-radius: 6px; margin-bottom: 20px; border: 1px solid #ffe0b2; }
    </style>
</head>
<body>
    <div class="container">
        <h1>حلبة الذكاء الاصطناعي الثنائية (Dual-AI Arena)</h1>
        <div class="subtitle">التشغيل الفعلي لاستعلامات النماذج الحية (Claude Haiku & Gemini Flash API)</div>

        <!-- معلومات السوق الحي -->
        <div class="live-market-info">
            <b>📊 معلومات السوق الحالي المستعلم عنه:</b><br>
            <span style="color: #d35400;">السؤال:</span> {{ market_info.question }}<br>
            <span style="color: #27ae60;">حالة السوق:</span> {{ "نشط ومتاح للتداول" if market_info.active else "مغلق" }}
        </div>

        <!-- لوحة التحكم -->
        <div class="control-panel">
            <form method="GET" action="/" style="display: flex; width: 100%; justify-content: space-between; align-items: center; margin: 0;">
                <div>
                    <label for="market"><b>اختر السوق المستهدف:</b></label>
                    <select name="market" id="market">
                        {% for slug, name in allowed_markets.items() %}
                            <option value="{{ slug }}" {% if slug == current_slug %}selected{% endif %}>{{ name }}</option>
                        {% endfor %}
                    </select>
                </div>
                <button type="submit" class="btn-action">🔄 إرسال واستعلام حي من النماذج</button>
            </form>
        </div>

        <div class="grid">
            <!-- بطاقة تحليل Claude الحية -->
            <div class="card">
                <h3>Claude Haiku (Live API Inference)</h3>
                <div class="metric"><b>حالة النموذج:</b> <span class="badge badge-success">متصل وفعّال</span></div>
                <div class="metric"><b>تحليل السوق الحي والتوصية:</b></div>
                <div class="ai-response">{{ claude_resp }}</div>
            </div>

            <!-- بطاقة تحليل Gemini الحية -->
            <div class="card">
                <h3>Gemini Flash (Live API Inference)</h3>
                <div class="metric"><b>حالة النموذج:</b> <span class="badge badge-success">متصل وفعّال</span></div>
                <div class="metric"><b>تحليل السوق الحي والتوصية:</b></div>
                <div class="ai-response">{{ gemini_resp }}</div>
            </div>
        </div>
    </div>
</body>
</html>
"""

@app.route("/")
def home():
    selected_market = request.args.get("market", "bitcoin-up-or-down-today")
    if selected_market not in ALLOWED_MARKETS:
        selected_market = "bitcoin-up-or-down-today"
        
    market_info = fetch_live_market_data(selected_market)
    
    # جلب الاستعلامات الحية من النماذج بناءً على سؤال السوق الحالي
    claude_resp = get_claude_analysis(market_info["question"])
    gemini_resp = get_gemini_analysis(market_info["question"])
    
    return render_template_string(
        DASHBOARD_TEMPLATE, 
        allowed_markets=ALLOWED_MARKETS,
        current_slug=selected_market,
        market_info=market_info,
        claude_resp=claude_resp,
        gemini_resp=gemini_resp
    )

@app.route("/trial-status")
def trial_status():
    return jsonify({
        "status": "24-Hour Trial Active with Live Model Inference",
        "allowed_markets": ALLOWED_MARKETS
    }), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
