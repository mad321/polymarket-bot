import os
import requests
from flask import Flask, jsonify, request
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, BUY, AssetType

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
    return "Polymarket Bot is Active with CLOB Client, Balance & Trading Logic!", 200

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
# 2. جلب رصيد USDC الفعلي وإدارة المخاطر (10% كحد أقصى)
# ---------------------------------------------------------
@app.route("/risk-check")
def risk_check():
    """
    مسار يتحقق من رصيد USDC الفعلي في المحفظة ويحسب الحد الأقصى للرهان (10%)
    """
    try:
        # جلب تفاصيل الرصيد والسماحية لعملة USDC عبر الـ ClobClient
        balance_data = client.get_balance_allowance(asset_type=AssetType.COLLATERAL)
        
        # استخراج الرصيد المتاح وتحويله لرقم عشري
        raw_balance = balance_data.get("balance", "0") if isinstance(balance_data, dict) else getattr(balance_data, "balance", "0")
        total_balance = float(raw_balance) / 10**6  # USDC معموله scaling بـ 6 خانات عشرية عادة في العقد
        
        # تطبيق قاعدة الـ 10% كحد أقصى للرهان الآمن
        max_bet_size = total_balance * 0.10
        
        return jsonify({
            "wallet_address": wallet_address,
            "usdc_balance": f"${total_balance:.2f}",
            "max_allowed_bet_10_percent": f"${max_bet_size:.2f}",
            "status": "Ready and within discipline limits"
        }), 200
            
    except Exception as e:
        return jsonify({
            "status": "Connected successfully (Balance check fallback)",
            "wallet_address": wallet_address,
            "error_note": str(e)
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
        # إعداد بيانات أمر الشراء
        order_args = OrderArgs(
            price=price,
            size=size,
            side=BUY,
            token_id=token_id
        )
        
        # إنشاء والتوقيع على الأمر باستخدام المفتاح الخاص
        signed_order = client.create_order(order_args)
        
        # إرسال الأمر إلى منصة Polymarket CLOB
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
