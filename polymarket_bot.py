import os
import json
import logging
import threading
import requests
from flask import Flask, render_template_string, jsonify
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

GAMMA_API = "https://gamma-api.polymarket.com"
CONFIG_FILE = "config.json"

DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>مراقب صفقات بوليماركت</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Segoe UI', Tahoma, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            min-height: 100vh;
            padding: 20px;
            color: #eee;
        }
        .container { max-width: 1000px; margin: 0 auto; }
        .header {
            text-align: center;
            padding: 30px 0 20px;
            border-bottom: 2px solid #e94560;
            margin-bottom: 30px;
        }
        .header h1 { font-size: 2em; color: #e94560; margin-bottom: 8px; }
        .header p { color: #aaa; font-size: 0.95em; }
        .last-update { text-align: center; color: #666; font-size: 0.85em; margin-bottom: 25px; }

        .position-card {
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 12px;
            padding: 20px 25px;
            margin-bottom: 18px;
            transition: border-color 0.3s;
        }
        .position-card:hover { border-color: #e94560; }

        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 18px;
            flex-wrap: wrap;
            gap: 10px;
        }
        .position-name { font-size: 1.2em; font-weight: bold; color: #fff; }
        .position-link {
            color: #e94560;
            text-decoration: none;
            font-size: 0.85em;
            border: 1px solid #e94560;
            padding: 4px 12px;
            border-radius: 20px;
            transition: all 0.2s;
        }
        .position-link:hover { background: #e94560; color: #fff; }

        .card-stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
            gap: 12px;
        }
        .stat {
            background: rgba(0,0,0,0.3);
            border-radius: 8px;
            padding: 12px;
            text-align: center;
        }
        .stat-label { font-size: 0.75em; color: #888; margin-bottom: 6px; }
        .stat-value { font-size: 1.3em; font-weight: bold; }

        .price-current { color: #00d4ff; }
        .price-buy { color: #aaa; }
        .price-stop { color: #ff4d4d; }
        .price-tp { color: #00d084; }
        .pnl-positive { color: #00d084; }
        .pnl-negative { color: #ff4d4d; }

        .progress-bar-wrap {
            margin-top: 15px;
            position: relative;
            height: 8px;
            background: rgba(255,255,255,0.1);
            border-radius: 4px;
            overflow: visible;
        }
        .progress-bar-fill {
            height: 100%;
            border-radius: 4px;
            transition: width 0.5s;
        }
        .progress-markers {
            position: relative;
            margin-top: 6px;
            height: 16px;
            font-size: 0.7em;
            color: #666;
        }
        .marker-stop { position: absolute; color: #ff4d4d; }
        .marker-buy { position: absolute; color: #aaa; transform: translateX(-50%); }
        .marker-tp { position: absolute; color: #00d084; transform: translateX(-100%); }

        .status-badge {
            display: inline-block;
            padding: 3px 10px;
            border-radius: 12px;
            font-size: 0.75em;
            font-weight: bold;
            margin-right: 8px;
        }
        .status-profit { background: rgba(0,208,132,0.2); color: #00d084; }
        .status-loss { background: rgba(255,77,77,0.2); color: #ff4d4d; }
        .status-hold { background: rgba(0,212,255,0.15); color: #00d4ff; }
        .status-error { background: rgba(255,255,255,0.1); color: #888; }

        .refresh-btn {
            display: block;
            margin: 25px auto;
            padding: 12px 35px;
            background: #e94560;
            color: white;
            border: none;
            border-radius: 25px;
            font-size: 1em;
            cursor: pointer;
            transition: opacity 0.2s;
        }
        .refresh-btn:hover { opacity: 0.85; }

        .summary-bar {
            display: flex;
            justify-content: center;
            gap: 30px;
            margin-bottom: 25px;
            flex-wrap: wrap;
        }
        .summary-item { text-align: center; }
        .summary-item .val { font-size: 1.4em; font-weight: bold; }
        .summary-item .lbl { font-size: 0.75em; color: #888; margin-top: 3px; }

        @media (max-width: 600px) {
            .card-stats { grid-template-columns: repeat(3, 1fr); }
        }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>📊 مراقب صفقات بوليماركت</h1>
        <p>دوري أمم أوروبا - تحديث تلقائي كل 30 ثانية</p>
    </div>

    <div class="last-update">آخر تحديث: {{ last_update }}</div>

    <div class="summary-bar">
        <div class="summary-item">
            <div class="val">{{ positions|length }}</div>
            <div class="lbl">صفقة مفتوحة</div>
        </div>
        <div class="summary-item">
            <div class="val {% if total_pnl >= 0 %}pnl-positive{% else %}pnl-negative{% endif %}">
                {% if total_pnl >= 0 %}+{% endif %}{{ "%.1f"|format(total_pnl) }}%
            </div>
            <div class="lbl">متوسط الأداء</div>
        </div>
    </div>

    {% for pos in positions %}
    <div class="position-card">
        <div class="card-header">
            <div>
                {% if pos.status == 'profit' %}
                    <span class="status-badge status-profit">📈 في الربح</span>
                {% elif pos.status == 'loss' %}
                    <span class="status-badge status-loss">📉 في الخسارة</span>
                {% elif pos.status == 'error' %}
                    <span class="status-badge status-error">⚠️ تعذر الجلب</span>
                {% else %}
                    <span class="status-badge status-hold">⏸ عادي</span>
                {% endif %}
                <span class="position-name">{{ pos.name }}</span>
            </div>
            <a href="{{ pos.url }}" target="_blank" class="position-link">🔗 الصفقة</a>
        </div>

        <div class="card-stats">
            <div class="stat">
                <div class="stat-label">السعر الحالي</div>
                <div class="stat-value price-current">
                    {% if pos.current_price %}{{ pos.current_price }}¢{% else %}—{% endif %}
                </div>
            </div>
            <div class="stat">
                <div class="stat-label">سعر الشراء</div>
                <div class="stat-value price-buy">{{ pos.buy_price }}¢</div>
            </div>
            <div class="stat">
                <div class="stat-label">وقف الخسارة</div>
                <div class="stat-value price-stop">{{ pos.stop_loss }}¢</div>
            </div>
            <div class="stat">
                <div class="stat-label">هدف الربح</div>
                <div class="stat-value price-tp">{{ pos.take_profit }}¢</div>
            </div>
            <div class="stat">
                <div class="stat-label">الأسهم</div>
                <div class="stat-value">{{ pos.shares }}</div>
            </div>
            <div class="stat">
                <div class="stat-label">الأداء</div>
                <div class="stat-value {% if pos.pnl and pos.pnl >= 0 %}pnl-positive{% elif pos.pnl %}pnl-negative{% endif %}">
                    {% if pos.pnl is not none %}
                        {% if pos.pnl >= 0 %}+{% endif %}{{ "%.1f"|format(pos.pnl) }}%
                    {% else %}—{% endif %}
                </div>
            </div>
        </div>

        {% if pos.current_price %}
        <div class="progress-bar-wrap">
            {% set range = pos.take_profit - pos.stop_loss %}
            {% set fill_pct = ((pos.current_price - pos.stop_loss) / range * 100)|round|int %}
            {% set fill_clamped = [0, [fill_pct, 100]|min]|max %}
            <div class="progress-bar-fill" style="
                width: {{ fill_clamped }}%;
                background: {% if pos.pnl and pos.pnl >= 0 %}#00d084{% else %}#ff4d4d{% endif %};
            "></div>
        </div>
        <div class="progress-markers">
            <span class="marker-stop" style="left: 0%">{{ pos.stop_loss }}¢</span>
            {% set buy_pct = ((pos.buy_price - pos.stop_loss) / range * 100)|round|int %}
            <span class="marker-buy" style="left: {{ buy_pct }}%">{{ pos.buy_price }}¢</span>
            <span class="marker-tp" style="left: 100%">{{ pos.take_profit }}¢</span>
        </div>
        {% endif %}
    </div>
    {% endfor %}

    <button class="refresh-btn" onclick="location.reload()">🔄 تحديث الأسعار</button>
</div>
</body>
</html>
"""


def get_price_by_slug(slug: str):
    try:
        url = f"{GAMMA_API}/markets?slug={slug}"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        if not data:
            return None
        prices_raw = data[0].get("outcomePrices", [])
        if isinstance(prices_raw, str):
            prices_raw = json.loads(prices_raw)
        if prices_raw:
            return round(float(prices_raw[0]) * 100, 1)
    except Exception as e:
        logger.error(f"خطأ في جلب سعر {slug}: {e}")
    return None


def build_polymarket_url(slug: str) -> str:
    return f"https://polymarket.com/event/{slug}"


def load_positions():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []


@app.route("/")
def home():
    raw_positions = load_positions()
    active = [p for p in raw_positions if not p.get("closed", False)]

    enriched = []
    pnl_list = []

    for pos in active:
        slug = pos.get("slug", "")
        current_price = get_price_by_slug(slug) if slug else None

        buy_price = pos.get("buy_price", 0)
        stop_loss = pos.get("stop_loss", 0)
        take_profit = pos.get("take_profit", 100)

        pnl = None
        status = "hold"
        if current_price is not None and buy_price:
            pnl = ((current_price - buy_price) / buy_price) * 100
            pnl_list.append(pnl)
            if current_price >= take_profit:
                status = "profit"
            elif current_price <= stop_loss:
                status = "loss"
            elif pnl >= 0:
                status = "profit"
            else:
                status = "loss"
        elif current_price is None:
            status = "error"

        enriched.append({
            "name": pos.get("name", ""),
            "slug": slug,
            "url": build_polymarket_url(slug),
            "shares": pos.get("shares", 0),
            "buy_price": buy_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "current_price": current_price,
            "pnl": round(pnl, 1) if pnl is not None else None,
            "status": status,
            "notes": pos.get("notes", ""),
        })

    total_pnl = round(sum(pnl_list) / len(pnl_list), 1) if pnl_list else 0

    return render_template_string(
        DASHBOARD_TEMPLATE,
        positions=enriched,
        total_pnl=total_pnl,
        last_update=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )


@app.route("/health")
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})


def start_monitor():
    try:
        from polymarket_monitor import main as monitor_main
        logger.info("🔍 بدء مراقبة الصفقات المفتوحة...")
        monitor_main()
    except Exception as e:
        logger.error(f"خطأ في المراقب: {e}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") == "development"

    monitor_thread = threading.Thread(target=start_monitor, daemon=True)
    monitor_thread.start()
    logger.info("✅ مراقب الأسعار شغّال في الخلفية")

    logger.info(f"🚀 بدء التطبيق على المنفذ {port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
