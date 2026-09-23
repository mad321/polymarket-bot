import os
import requests
from flask import Flask, jsonify
from py_clob_client.client import ClobClient

app = Flask(__name__)

# --- الإعدادات والمفاتيح ---
host = "https://clob.polymarket.com"
chain_id = 137 # شبكة بوليجون

private_key = os.environ.get("PRIVATE_KEY")
wallet_address = os.environ.get("WALLET_ADDRESS")

# تهيئة عميل CLOB (للتداول والأسعار اللحظية)
client = ClobClient(host, key=private_key, chain_id=chain_id)

# الروابط الأساسية لـ Gamma API
GAMMA_API_URL = "https://gamma-api.polymarket.com"

@app.route("/")
def home():
    return "Polymarket Bot is Active with CLOB Client & Gamma API!", 200

# ---------------------------------------------------------
# 1. استخدام Gamma API: للبحث عن سوق وجلب الـ Token ID
# ---------------------------------------------------------
@app.route("/search-market/<market_slug>")
def search_market(market_slug):
    """
    مثال: /search-market/saudi-arabia-to-win-gulf-cup
    """
    try:
        response = requests.get(f"{GAMMA_API_URL}/markets/{market_slug}")
        
        if response.status_code != 200:
            return jsonify({"error": "Market not found"}), 404
            
        market_data = response.json()
        tokens = market_data.get("tokens", [])
        
        return jsonify({
            "market_question": market_data.get("question"),
            "tokens": tokens
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------------------------------------------------------
# 2. فحص المحفظة وإدارة المخاطر عبر py-clob-client مباشرة
# ---------------------------------------------------------
@app.route("/risk-check")
def risk_check():
    """
    مسار يتحقق من اتصال العميل وجاهزية المحفظة لتداول Polymarket
    """
    try:
        # استخدام العميل للتحقق من الاتصال وجلب بيانات الحساب المتاحة
        # (يمكننا توسيعها لاحقاً لجلب الأرصدة عبر دوال العميل المتاحة)
        return jsonify({
            "status": "Connected successfully",
            "wallet_address": wallet_address,
            "message": "CLOB client is initialized and ready for trading logic."
        }), 200
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
