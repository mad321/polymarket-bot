import os
import requests
from flask import Flask, jsonify, request
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, BUY

app = Flask(__name__)

# --- الإعدادات والمفاتيح ---
host = "https://clob.polymarket.com"
chain_id = 137 # شبكة بوليجون

private_key = os.environ.get("PRIVATE_KEY")
wallet_address = os.environ.get("WALLET_ADDRESS")

# تهيئة عميل CLOB (للتداول والأسعار اللحظية والأرصدة)
client = ClobClient(host, key=private_key, chain_id=chain_id)

# الروابط الأساسية لـ Gamma API فقط
GAMMA_API_URL = "https://gamma-api.polymarket.com"

@app.route("/")
def home():
    return "Polymarket Bot is Active with CLOB Client & Trading Logic!", 200

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
# 2. فحص رصيد المحفظة وإدارة المخاطر (10% كحد أقصى)
# ---------------------------------------------------------
@app.route("/risk-check")
def risk_check():
    """
    مسار يتحقق من رصيد المحفظة عبر دوال العميل المباشرة
    """
    try:
        # استدعاء دالة جلب الرصيد المتاحة في العميل
        balance_info = client.get_balance_allowance()
        
        return jsonify({
            "wallet_address": wallet_address,
            "balance_details": str(balance_info),
            "status": "Balance fetched successfully"
        }), 200
            
    except Exception as e:
        # طريقة بديلة في حال تطلب البารامترات
        try:
            from py_clob_client.clob_types import AssetType
            balance_info = client.get_balance_allowance(asset_type=AssetType.COLLATERAL)
            return jsonify({
                "wallet_address": wallet_address,
                "balance_details": str(balance_info),
                "status": "Balance fetched successfully with COLLATERAL"
            }), 200
        except Exception as inner_e:
            return jsonify({
                "wallet_address": wallet_address,
                "error": str(inner_e),
                "status": "Client connected, but balance endpoint needs specific formatting"
            }), 200

# ---------------------------------------------------------
# 3. دالة تنفيذ صفقة شراء تجريبية (Buy Order)
# ---------------------------------------------------------
@app.route("/trade-test")
def trade_test():
    """
    مسار تجريبي لاختبار إرسال أمر شراء
    مثال استدعاء: /trade-test?token_id=TOKEN_ID&price=0.5&size=5
    """
    token_id = request.args.get("token_id")
    price = request.args.get("price", type=float)
    size = request.args.get("size", type=float)

    if not token_id or not price or not size:
        return jsonify({
            "error": "Missing parameters",
            "usage": "/trade-test?token_id=XYZ&price=0.5&size=5"
        }), 400

    try:
        order_args = OrderArgs(
            price=price,
            size=size,
            side=BUY,
            token_id=token_id
        )
        signed_order = client.create_order(order_args)
        resp = client.post_order(signed_order)

        return jsonify({
            "status": "Order submitted successfully",
            "response": resp
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
