import os
import requests
from flask import Flask, jsonify, render_template_string
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

# الأسواق المعتمدة لفترة التجربة (24 ساعة)
ALLOWED_MARKETS = {
    "bitcoin-up-or-down-today": "Crypto - Bitcoin Daily",
    "fed-interest-rate-decision": "Macro - Fed Rates"
}

# محاكاة سجل الصفقات وأداء النماذج (Paper Trading Data)
TRADES_HISTORY = {
    "claude": {
        "total_trades": 4,
        "winning_trades": 3,
        "win_rate": "75.0%",
        "total_pnl": "+$42.50",
        "active_trades": [
            {"market": "Bitcoin Daily", "entry_price": "$0.52", "current_price": "$0.58", "action": "BUY", "pnl": "+11.5%"}
        ]
    },
    "gemini": {
        "total_trades": 4,
        "winning_trades": 4,
        "win_rate": "100.0%",
        "total_pnl": "+$68.00",
        "active_trades": [
            {"market": "Bitcoin Daily", "entry_price": "$0.51", "current_price": "$0.58", "action": "BUY", "pnl": "+13.7%"}
        ]
    }
}

# تصميم لوحة التحكم المحدثة مع سجل الصفقات
DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Polymarket Dual-AI Arena - Live Paper Trading</title>
    <style>
        body { font-family: Tahoma, sans-serif; background-color: #f4f7f6; margin: 0; padding: 20px; color: #333; }
        .container { max-width: 1050px; margin: auto; background: #fff; padding: 25px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }
        h1 { color: #2c3e50; text-align: center; margin-bottom: 5px; }
        .subtitle { text-align: center; color: #7f8c8d; margin-bottom: 25px; font-size: 14px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .card { background: #fafafa; border: 1px solid #e1e8ed; border-radius: 8px; padding: 15px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }
        .card h3 { margin-top: 0; color: #2980b9; border-bottom: 2px solid #3498db; padding-bottom: 8px; }
        .metric { margin: 10px 0; font-size: 15px; }
        .badge { display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; }
        .badge-success { background: #2ecc71; color: white; }
        .badge-profit { background: #27ae60; color: white; }
        .refresh-btn { display: block; width: 100%; padding: 12px; background: #3498db; color: white; border: none; border-radius: 6px; font-size: 16px; cursor: pointer; text-align: center; margin-top: 25px; text-decoration: none; }
        .refresh-btn:hover { background: #2980b9; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: center; font-size: 13px; }
        th { background-color: #f2f2f2; }
    </style>
</head>
<body>
    <div class="container">
        <h1>حلبة الذكاء الاصطناعي الثنائية (Dual-AI Arena)</h1>
        <div class="subtitle">متابعة صفقات التداول الافتراضي (Paper Trading) ونسب النجاح اللحظية</div>

        <div class="grid">
            <!-- بطاقة Claude -->
            <div class="card">
                <h3>Claude Haiku (Eco Live)</h3>
                <div class="metric"><b>الموديل:</b> `claude-3-5-haiku`</div>
                <div class="metric"><b>نسبة الصفقات الناجحة (Win Rate):</b> <span class="badge badge-success">{{ claude.win_rate }}</span></div>
                <div class="metric"><b>إجمالي الأرباح الافتراضية (PnL):</b> <span class="badge badge-profit">{{ claude.total_pnl }}</span></div>
                <div class="metric"><b>الصفقات الرابحة / الإجمالي:</b> {{ claude.winning_trades }} / {{ claude.total_trades }}</div>
            </div>

            <!-- بطاقة Gemini -->
            <div class="card">
                <h3>Gemini Flash (Eco Live)</h3>
                <div class="metric"><b>الموديل:</b> `gemini-2.5-flash`</div>
                <div class="metric"><b>نسبة الصفقات الناجحة (Win Rate):</b> <span class="badge badge-success">{{ gemini.win_rate }}</span></div>
                <div class="metric"><b>إجمالي الأرباح الافتراضية (PnL):</b> <span class="badge badge-profit">{{ gemini.total_pnl }}</span></div>
                <div class="metric"><b>الصفقات الرابحة / الإجمالي:</b> {{ gemini.winning_trades }} / {{ gemini.total_trades }}</div>
            </div>
        </div>

        <!-- جدول الصفقات النشطة -->
        <div style="margin-top: 30px;">
            <h3>سجل الصفقات الافتراضية الحالية (Active Paper Trades)</h3>
            <table>
                <tr>
                    <th>النموذج</th>
                    <th>السوق</th>
                    <th>الإجراء</th>
                    <th>سعر الدخول</th>
                    <th>السعر الحالي</th>
                    <th>العائد (PnL)</th>
                </tr>
                <tr>
                    <td><b>Claude Haiku</b></td>
                    <td>Bitcoin Daily</td>
                    <td><span class="badge badge-success">شراء (BUY)</span></td>
                    <td>{{ claude.active_trades[0].entry_price }}</td>
                    <td>{{ claude.active_trades[0].current_price }}</td>
                    <td><b style="color: green;">{{ claude.active_trades[0].pnl }}</b></td>
                </tr>
                <tr>
                    <td><b>Gemini Flash</b></td>
                    <td>Bitcoin Daily</td>
                    <td><span class="badge badge-success">شراء (BUY)</span></td>
                    <td>{{ gemini.active_trades[0].entry_price }}</td>
                    <td>{{ gemini.active_trades[0].current_price }}</td>
                    <td><b style="color: green;">{{ gemini.active_trades[0].pnl }}</b></td>
                </tr>
            </table>
        </div>

        <a href="/" class="refresh-btn">تحديث لوحة الصفقات والأداء</a>
    </div>
</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(
        DASHBOARD_TEMPLATE, 
        claude=TRADES_HISTORY["claude"], 
        gemini=TRADES_HISTORY["gemini"]
    )

@app.route("/ai-trade/claude/<market_slug>")
def claude_strategy(market_slug):
    if market_slug not in ALLOWED_MARKETS:
        return jsonify({"error": "Market not allowed in 24H trial scope."}), 400
    return jsonify({
        "trial_period": "24 Hours Day 1",
        "model": "Claude Haiku (Eco Live)",
        "market_category": ALLOWED_MARKETS[market_slug],
        "metrics": TRADES_HISTORY["claude"]
    }), 200

@app.route("/ai-trade/gemini/<market_slug>")
def gemini_strategy(market_slug):
    if market_slug not in ALLOWED_MARKETS:
        return jsonify({"error": "Market not allowed in 24H trial scope."}), 400
    return jsonify({
        "trial_period": "24 Hours Day 1",
        "model": "Gemini Flash (Eco Live)",
        "market_category": ALLOWED_MARKETS[market_slug],
        "metrics": TRADES_HISTORY["gemini"]
    }), 200

@app.route("/trial-status")
def trial_status():
    return jsonify({
        "status": "24-Hour Trial Active",
        "paper_trading": "Enabled",
        "allowed_markets": ALLOWED_MARKETS
    }), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
