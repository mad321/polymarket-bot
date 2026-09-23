import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
from flask import Flask, jsonify, render_template_string, redirect, url_for
from py_clob_client.client import ClobClient

app = Flask(__name__)

# --- الإعدادات والمفاتيح ---
host = "https://clob.polymarket.com"
chain_id = 137

private_key = os.environ.get("PRIVATE_KEY")
wallet_address = os.environ.get("WALLET_ADDRESS")
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# إعدادات التنبيهات
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

client = ClobClient(host, key=private_key, chain_id=chain_id)
GAMMA_API_URL = "https://gamma-api.polymarket.com"

ALLOWED_MARKETS = {
    "bitcoin-up-or-down-today": "Crypto - Bitcoin Daily",
    "fed-interest-rate-decision": "Macro - Fed Rates"
}

def send_telegram_alert(message):
    """إرسال تنبيه عبر تليجرام مع جلب رسالة الخطأ أو النجاح الدقيقة"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False, "Telegram credentials missing"
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        res = requests.post(url, json=payload, timeout=5)
        res_data = res.json()
        if res.status_code == 200 and res_data.get("ok"):
            return True, "تم الإرسال بنجاح إلى تليجرام!"
        else:
            # إرجاع الخطأ الدقيق من تليجرام (مثل: Bot was blocked by the user أو chat not found)
            error_desc = res_data.get("description", "Unknown error")
            return False, f"خطأ من تليجرام: {error_desc}"
    except Exception as e:
        return False, str(e)

def fetch_live_market_data(slug):
    try:
        res = requests.get(f"{GAMMA_API_URL}/markets/{slug}", timeout=5)
        if res.status_code == 200:
            data = res.json()
            return {
                "question": data.get("question", slug),
                "active": data.get("active", True),
                "closed": data.get("closed", False),
                "volume": data.get("volume", "غير متوفر"),
            }
    except Exception:
        pass
    return {"question": slug, "active": True, "closed": False, "volume": "N/A"}

DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dual-AI Arena - Telegram Debug</title>
    <style>
        body { font-family: Tahoma, sans-serif; background-color: #f4f7f6; margin: 0; padding: 20px; color: #333; }
        .container { max-width: 900px; margin: auto; background: #fff; padding: 25px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }
        h1 { color: #2c3e50; text-align: center; }
        .control-panel { background: #e8f4f8; padding: 15px; border-radius: 8px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; }
        select, button { padding: 8px 12px; border-radius: 5px; border: 1px solid #bdc3c7; font-family: Tahoma; }
        .btn-action { background: #2980b9; color: white; border: none; cursor: pointer; }
        .btn-alert { background: #e67e22; color: white; border: none; cursor: pointer; text-decoration: none; display: inline-block; padding: 8px 12px; border-radius: 5px; }
        .alert-status { margin-bottom: 20px; padding: 12px; background: #fff3cd; color: #856404; border: 1px solid #ffeeba; border-radius: 5px; text-align: center; font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <h1>اختبار وتشخيص تنبيهات تليجرام</h1>
        
        {% if alert_msg %}
        <div class="alert-status">{{ alert_msg }}</div>
        {% endif %}

        <div class="control-panel">
            <form method="GET" action="/" style="display: flex; gap: 10px; align-items: center; margin: 0;">
                <label for="market"><b>اختر السوق:</b></label>
                <select name="market" id="market">
                    {% for slug, name in allowed_markets.items() %}
                        <option value="{{ slug }}" {% if slug == current_slug %}selected{% endif %}>{{ name }}</option>
                    {% endfor %}
                </select>
                <button type="submit" class="btn-action">تحديث السوق</button>
            </form>
            
            <a href="/test-telegram?market={{ current_slug }}" class="btn-alert">🔔 اختبار إرسال تليجرام الآن</a>
        </div>

        <div style="background: #fafafa; padding: 15px; border-radius: 8px; border: 1px solid #ddd;">
            <h3>معلومات الاتصال الحالية:</h3>
            <p><b>البوت المستخدم:</b> @esampolymarketbot</p>
            <p><b>رقم الـ Chat ID المسجل في Render:</b> {{ chat_id_status }}</p>
            <p style="color: #c0392b; font-size: 13px;">ملاحظة هامة: تأكد تماماً أنك قمت بالدخول على تليجرام والضغط على <b>Start</b> داخل محادثة بوتك الخاص `@esampolymarketbot` وإرسال رسالة إليه قبل الضغط على زر الاختبار.</p>
        </div>
    </div>
</body>
</html>
"""

@app.route("/")
def home():
    from flask import request
    selected_market = request.args.get("market", "bitcoin-up-or-down-today")
    alert_msg = request.args.get("alert_msg", "")
    chat_id_val = TELEGRAM_CHAT_ID if TELEGRAM_CHAT_ID else "غير مسجل"
    
    return render_template_string(
        DASHBOARD_TEMPLATE, 
        allowed_markets=ALLOWED_MARKETS,
        current_slug=selected_market,
        alert_msg=alert_msg,
        chat_id_status=chat_id_val
    )

@app.route("/test-telegram")
def test_telegram():
    from flask import request
    selected_market = request.args.get("market", "bitcoin-up-or-down-today")
    
    alert_text = "🚨 اختبار ناجح من حلبة Dual-AI Arena! نظام التنبيهات يعمل بكفاءة."
    success, msg = send_telegram_alert(alert_text)
    
    return redirect(url_for('home', market=selected_market, alert_msg=msg))

@app.route("/trial-status")
def trial_status():
    return jsonify({"status": "Active"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
