import os
import logging
from flask import Flask, render_template_string, request, jsonify
from datetime import datetime
from polymarket_service import PolymarketService
from ai_analysis import AIAnalyzer
from config import ALLOWED_MARKETS

# إعداد الـ logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# تهيئة الخدمات
pm_service = PolymarketService()
ai_analyzer = AIAnalyzer()

# قالب الواجهة الأمامية
DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dual-AI Trading Arena - نظام التداول الثنائي</title>
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            margin: 0;
            padding: 20px;
            color: #333;
            direction: rtl;
            text-align: right;
            min-height: 100vh;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 15px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.3);
            padding: 30px;
        }
        .header {
            text-align: center;
            margin-bottom: 30px;
            border-bottom: 3px solid #667eea;
            padding-bottom: 20px;
        }
        .header h1 {
            margin: 0;
            color: #667eea;
            font-size: 2.5em;
        }
        .header p {
            margin: 10px 0 0 0;
            color: #666;
            font-size: 1.1em;
        }
        .control-panel {
            background: #f5f7fa;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 30px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 15px;
            flex-wrap: wrap;
        }
        .control-panel select {
            padding: 10px 15px;
            border: 2px solid #667eea;
            border-radius: 5px;
            font-size: 1em;
            background: white;
            cursor: pointer;
            font-family: inherit;
        }
        .control-panel button {
            padding: 10px 25px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 5px;
            font-size: 1em;
            cursor: pointer;
            transition: transform 0.2s;
        }
        .control-panel button:hover {
            transform: translateY(-2px);
        }
        .market-info {
            background: #fff8e1;
            border-left: 4px solid #ffc107;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
        }
        .market-info.error {
            background: #ffebee;
            border-left-color: #f44336;
        }
        .market-info.success {
            background: #e8f5e9;
            border-left-color: #4caf50;
        }
        .market-question {
            font-size: 1.3em;
            font-weight: bold;
            margin: 10px 0;
            color: #333;
        }
        .market-stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }
        .stat {
            background: white;
            padding: 15px;
            border-radius: 5px;
            border: 1px solid #e0e0e0;
            text-align: center;
        }
        .stat-label {
            font-size: 0.9em;
            color: #666;
            margin-bottom: 5px;
        }
        .stat-value {
            font-size: 1.5em;
            font-weight: bold;
            color: #667eea;
        }
        .ai-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-top: 20px;
        }
        .ai-card {
            background: #f9f9f9;
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            padding: 20px;
            transition: all 0.3s;
        }
        .ai-card:hover {
            border-color: #667eea;
            box-shadow: 0 5px 20px rgba(102, 126, 234, 0.2);
        }
        .ai-card h3 {
            margin-top: 0;
            color: #667eea;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .ai-card .model-name {
            font-size: 0.9em;
            color: #999;
            font-weight: normal;
        }
        .analysis-text {
            background: white;
            padding: 15px;
            border-radius: 5px;
            line-height: 1.8;
            color: #333;
            font-size: 0.95em;
            max-height: 400px;
            overflow-y: auto;
            white-space: pre-wrap;
            word-wrap: break-word;
        }
        .loading {
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 10px;
            color: #667eea;
            font-weight: bold;
        }
        .spinner {
            border: 3px solid #f3f3f3;
            border-top: 3px solid #667eea;
            border-radius: 50%;
            width: 20px;
            height: 20px;
            animation: spin 1s linear infinite;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        .error-message {
            color: #f44336;
            background: #ffebee;
            padding: 10px;
            border-radius: 5px;
            margin-top: 10px;
        }
        .market-link {
            display: inline-block;
            margin-top: 15px;
            padding: 10px 20px;
            background: #667eea;
            color: white;
            text-decoration: none;
            border-radius: 5px;
            transition: background 0.2s;
        }
        .market-link:hover {
            background: #764ba2;
        }
        .prices-table {
            width: 100%;
            margin-top: 15px;
            border-collapse: collapse;
        }
        .prices-table th, .prices-table td {
            padding: 10px;
            border: 1px solid #e0e0e0;
            text-align: center;
        }
        .prices-table th {
            background: #f5f5f5;
            font-weight: bold;
            color: #333;
        }
        @media (max-width: 768px) {
            .ai-grid {
                grid-template-columns: 1fr;
            }
            .header h1 {
                font-size: 1.8em;
            }
        }
    </style>
    <script>
        function updateMarket() {
            const market = document.getElementById('market-select').value;
            window.location.href = '/?market=' + market;
        }

        function copyToClipboard(text) {
            navigator.clipboard.writeText(text);
            alert('تم النسخ!');
        }
    </script>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🏛️ حلبة الذكاء الاصطناعي الثنائية</h1>
            <p>نظام تداول حقيقي يجلب بيانات مباشرة من Polymarket ويحللها مع Claude و Gemini</p>
        </div>

        <div class="control-panel">
            <div>
                <label for="market-select"><strong>اختر السوق:</strong></label>
                <select id="market-select" onchange="updateMarket()">
                    {% for key, market in allowed_markets.items() %}
                        <option value="{{ key }}" {% if key == current_market %}selected{% endif %}>
                            {{ market.name }}
                        </option>
                    {% endfor %}
                </select>
            </div>
            <button onclick="updateMarket()">🔄 تحديث البيانات</button>
        </div>

        {% if error_message %}
        <div class="market-info error">
            <div class="market-question">❌ خطأ</div>
            <p>{{ error_message }}</p>
        </div>
        {% elif market_data %}
        <div class="market-info {% if market_data.is_valid %}success{% else %}error{% endif %}">
            <div class="market-question">{{ market_data.question }}</div>
            <p>{{ market_data.validation_msg or market_data.validation_error }}</p>
            <div class="market-stats">
                <div class="stat">
                    <div class="stat-label">السيولة الإجمالية</div>
                    <div class="stat-value">${{ "%.2f"|format(market_data.total_liquidity) }}</div>
                </div>
                <div class="stat">
                    <div class="stat-label">الحجم (24 ساعة)</div>
                    <div class="stat-value">${{ "%.2f"|format(market_data.volume) }}</div>
                </div>
                <div class="stat">
                    <div class="stat-label">الوقت المتبقي</div>
                    <div class="stat-value">{{ "%.1f"|format(market_data.time_remaining_seconds / 3600) }} ساعة</div>
                </div>
                <div class="stat">
                    <div class="stat-label">أفضل سعر شراء</div>
                    <div class="stat-value">${{ "%.3f"|format(market_data.best_buy_price or 0) }}</div>
                </div>
            </div>

            {% if market_data.prices %}
            <table class="prices-table">
                <tr>
                    <th>الخيار</th>
                    <th>السعر الحالي</th>
                </tr>
                {% for outcome, price in market_data.prices.items() %}
                <tr>
                    <td>{{ outcome }}</td>
                    <td>${{ "%.3f"|format(price) }}</td>
                </tr>
                {% endfor %}
            </table>
            {% endif %}

            <a href="{{ market_data.direct_url }}" target="_blank" class="market-link">
                🔗 فتح السوق على Polymarket
            </a>
        </div>

        <div class="ai-grid">
            {% if analyses %}
                {% if analyses.claude.status == 'success' %}
                <div class="ai-card">
                    <h3>🤖 Claude Haiku <span class="model-name">({{ analyses.claude.model }})</span></h3>
                    <div class="analysis-text">{{ analyses.claude.analysis }}</div>
                </div>
                {% else %}
                <div class="ai-card">
                    <h3>🤖 Claude Haiku</h3>
                    <div class="error-message">{{ analyses.claude.message }}</div>
                </div>
                {% endif %}

                {% if analyses.gemini.status == 'success' %}
                <div class="ai-card">
                    <h3>✨ Gemini Flash <span class="model-name">({{ analyses.gemini.model }})</span></h3>
                    <div class="analysis-text">{{ analyses.gemini.analysis }}</div>
                </div>
                {% else %}
                <div class="ai-card">
                    <h3>✨ Gemini Flash</h3>
                    <div class="error-message">{{ analyses.gemini.message }}</div>
                </div>
                {% endif %}
            {% else %}
            <div class="ai-card" style="grid-column: 1/-1; text-align: center;">
                <div class="loading">
                    <div class="spinner"></div>
                    جارٍ تحميل التحليلات...
                </div>
            </div>
            {% endif %}
        </div>
        {% endif %}
    </div>
</body>
</html>
"""


@app.route("/")
def home():
    """الصفحة الرئيسية للداشبورد"""
    try:
        selected_market = request.args.get("market", "bitcoin-daily")

        if selected_market not in ALLOWED_MARKETS:
            selected_market = "bitcoin-daily"

        market_config = ALLOWED_MARKETS[selected_market]

        # جلب بيانات السوق من Polymarket
        logger.info(f"جارٍ البحث عن السوق: {selected_market}")
        markets = pm_service.search_markets(market_config["search_term"], limit=5)

        if not markets:
            return render_template_string(
                DASHBOARD_TEMPLATE,
                allowed_markets=ALLOWED_MARKETS,
                current_market=selected_market,
                error_message=f"لم يتم العثور على أي أسواق تطابق '{market_config['search_term']}'",
                market_data=None,
                analyses=None
            )

        # اختيار السوق الأول (الأكثر صلة)
        selected_market_data = markets[0]
        market_slug = selected_market_data.get("slug")

        logger.info(f"تم اختيار السوق: {market_slug}")

        # جلب البيانات الحية
        market_opportunity = pm_service.get_market_opportunity(market_slug, market_config["type"])

        if not market_opportunity:
            return render_template_string(
                DASHBOARD_TEMPLATE,
                allowed_markets=ALLOWED_MARKETS,
                current_market=selected_market,
                error_message="فشل في جلب بيانات السوق",
                market_data=None,
                analyses=None
            )

        # تحليل السوق باستخدام AI
        logger.info("جارٍ تحليل السوق...")
        analyses = ai_analyzer.analyze_market(market_opportunity)

        return render_template_string(
            DASHBOARD_TEMPLATE,
            allowed_markets=ALLOWED_MARKETS,
            current_market=selected_market,
            market_data=market_opportunity,
            analyses=analyses,
            error_message=None
        )

    except Exception as e:
        logger.error(f"خطأ في الصفحة الرئيسية: {e}", exc_info=True)
        return render_template_string(
            DASHBOARD_TEMPLATE,
            allowed_markets=ALLOWED_MARKETS,
            current_market=request.args.get("market", "bitcoin-daily"),
            error_message=f"حدث خطأ: {str(e)}",
            market_data=None,
            analyses=None
        ), 500


@app.route("/api/market/<market_slug>")
def get_market_api(market_slug):
    """API endpoint لجلب بيانات السوق"""
    try:
        market_opportunity = pm_service.get_market_opportunity(market_slug, "daily")

        if not market_opportunity:
            return jsonify({"error": "لم يتم العثور على السوق"}), 404

        return jsonify(market_opportunity)
    except Exception as e:
        logger.error(f"خطأ في API: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/analysis/<market_slug>")
def get_analysis_api(market_slug):
    """API endpoint لجلب التحليلات"""
    try:
        market_opportunity = pm_service.get_market_opportunity(market_slug, "daily")

        if not market_opportunity:
            return jsonify({"error": "لم يتم العثور على السوق"}), 404

        analyses = ai_analyzer.analyze_market(market_opportunity)
        return jsonify(analyses)
    except Exception as e:
        logger.error(f"خطأ في API: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health_check():
    """فحص صحة التطبيق"""
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") == "development"
    logger.info(f"🚀 بدء التطبيق على المنفذ {port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
