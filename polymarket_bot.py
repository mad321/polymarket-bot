import os
import requests
from flask import Flask, jsonify
from py_clob_client.client import ClobClient

app = Flask(__name__)

# --- الإعدادات والمفاتيح ---
host = "https://clob.polymarket.com"
chain_id = 137 # شبكة بوليجون

private_key = os.environ.get("PRIVATE_KEY")
# ستحتاج لإضافة عنوان محفظتك العامة كمتغير بيئة لتتمكن من جلب بيانات محفظتك
wallet_address = os.environ.get("WALLET_ADDRESS")

# تهيئة عميل CLOB (للتداول والأسعار اللحظية)
client = ClobClient(host, key=private_key, chain_id=chain_id)

# الروابط الأساسية لـ Gamma و Data
GAMMA_API_URL = "https://gamma-api.polymarket.com"
DATA_API_URL = "https://data-api.polymarket.com"

@app.route("/")
def home():
    return "Polymarket Bot is Active with Gamma and Data APIs!", 200

# ---------------------------------------------------------
# 1. استخدام Gamma API: للبحث عن سوق وجلب الـ Token ID
# ---------------------------------------------------------
@app.route("/search-market/<market_slug>")
def search_market(market_slug):
    """
    مثال: /search-market/saudi-arabia-to-win-gulf-cup
    """
    try:
        # جلب تفاصيل السوق باستخدام الـ Slug
        response = requests.get(f"{GAMMA_API_URL}/markets/{market_slug}")
        
        if response.status_code != 200:
            return jsonify({"error": "Market not found"}), 404
            
        market_data = response.json()
        
        # استخراج الـ Token ID لخيارات السوق (مثل نعم / لا)
        tokens = market_data.get("tokens", [])
        
        return jsonify({
            "market_question": market_data.get("question"),
            "tokens": tokens
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------------------------------------------------------
# 2. استخدام Data API: لجلب قيمة المحفظة وإدارة المخاطر (10% كحد أقصى)
# ---------------------------------------------------------
@app.route("/risk-check")
def risk_check():
    """
    مسار يتحقق من قيمة المحفظة ويحسب الحد الأقصى المسموح للدخول (10%)
    """
    if not wallet_address:
        return jsonify({"error": "WALLET_ADDRESS not set in Environment Variables"}), 400
        
    try:
        # استخدام Data API لجلب قيمة المحفظة (Portfolio Value)
        # ملاحظة: بعض مسارات Data API تتطلب تمرير المستخدم كمعلمة
        response = requests.get(f"{DATA_API_URL}/portfolio?user={wallet_address}")
        
        if response.status_code != 200:
            return jsonify({"error": "Failed to fetch portfolio"}), 500
            
        portfolio_data = response.json()
        total_value = float(portfolio_data.get("value", 0))
        
        # تطبيق قاعدة الانضباط: الحد الأقصى للرهان هو 10% من البنكرول
        max_bet_size = total_value * 0.10
        
        return jsonify({
            "total_portfolio_value": f"${total_value:.2f}",
            "max_allowed_bet_10_percent": f"${max_bet_size:.2f}",
            "status": "Ready to trade within limits"
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
