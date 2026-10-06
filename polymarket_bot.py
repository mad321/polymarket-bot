import os
import logging
import threading
from flask import Flask, render_template_string, jsonify
from datetime import datetime

from positions import load_positions

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="30">
    <title>مراقب صفقات بوليماركت</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0b0f1a;
            --surface: rgba(255,255,255,0.04);
            --surface-2: rgba(255,255,255,0.07);
            --border: rgba(255,255,255,0.08);
            --text: #f1f3f9;
            --muted: #8b93a7;
            --accent: #e94560;
            --green: #22d39b;
            --red: #ff5a6e;
            --blue: #4cc9f0;
            --amber: #f5b942;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Tajawal', 'Segoe UI', Tahoma, sans-serif;
            background:
                radial-gradient(900px 500px at 85% -10%, rgba(233,69,96,0.18), transparent 60%),
                radial-gradient(800px 500px at 0% 10%, rgba(76,201,240,0.12), transparent 60%),
                var(--bg);
            background-attachment: fixed;
            min-height: 100vh;
            padding: 24px 16px 40px;
            color: var(--text);
            -webkit-font-smoothing: antialiased;
        }
        .num { font-variant-numeric: tabular-nums; direction: ltr; unicode-bidi: isolate; }
        .container { max-width: 1040px; margin: 0 auto; }

        /* Header */
        .header {
            display: flex; align-items: center; justify-content: space-between;
            gap: 16px; flex-wrap: wrap; margin-bottom: 28px;
        }
        .brand { display: flex; align-items: center; gap: 14px; }
        .logo {
            width: 52px; height: 52px; border-radius: 14px;
            display: grid; place-items: center; font-size: 26px;
            background: linear-gradient(135deg, var(--accent), #ff8a5b);
            box-shadow: 0 10px 30px -8px rgba(233,69,96,0.6);
        }
        .brand h1 { font-size: 1.6em; font-weight: 800; line-height: 1.2; }
        .brand h1 span { color: var(--accent); }
        .brand p { color: var(--muted); font-size: 0.92em; margin-top: 2px; }
        .live {
            display: inline-flex; align-items: center; gap: 8px;
            padding: 8px 14px; border-radius: 999px;
            background: var(--surface); border: 1px solid var(--border);
            color: var(--muted); font-size: 0.85em;
        }
        .dot {
            width: 8px; height: 8px; border-radius: 50%; background: var(--green);
            box-shadow: 0 0 0 0 rgba(34,211,155,0.7); animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0% { box-shadow: 0 0 0 0 rgba(34,211,155,0.6); }
            70% { box-shadow: 0 0 0 8px rgba(34,211,155,0); }
            100% { box-shadow: 0 0 0 0 rgba(34,211,155,0); }
        }

        /* Summary */
        .summary {
            display: grid; grid-template-columns: repeat(4, 1fr);
            gap: 14px; margin-bottom: 28px;
        }
        .kpi {
            background: var(--surface); border: 1px solid var(--border);
            border-radius: 16px; padding: 18px 20px;
            backdrop-filter: blur(8px);
        }
        .kpi .lbl { color: var(--muted); font-size: 0.82em; margin-bottom: 8px; }
        .kpi .val { font-size: 1.7em; font-weight: 800; }
        .kpi .sub { color: var(--muted); font-size: 0.78em; margin-top: 4px; }

        .section-title {
            display: flex; justify-content: space-between; align-items: baseline;
            margin-bottom: 14px; color: var(--muted); font-size: 0.9em;
        }
        .section-title h2 { color: var(--text); font-size: 1.15em; font-weight: 700; }

        /* Cards */
        .grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
        .card {
            position: relative; overflow: hidden;
            background: linear-gradient(180deg, var(--surface-2), var(--surface));
            border: 1px solid var(--border); border-radius: 18px;
            padding: 20px 20px 18px;
            transition: transform .2s ease, border-color .2s ease, box-shadow .2s ease;
        }
        .card::before {
            content: ""; position: absolute; inset-inline-start: 0; top: 0; bottom: 0;
            width: 4px; background: var(--tone, var(--blue));
        }
        .card:hover {
            transform: translateY(-3px);
            border-color: rgba(255,255,255,0.16);
            box-shadow: 0 18px 40px -20px rgba(0,0,0,0.8);
        }
        .card.profit { --tone: var(--green); }
        .card.loss   { --tone: var(--red); }
        .card.error  { --tone: var(--amber); }

        .card-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; margin-bottom: 16px; }
        .name { font-size: 1.15em; font-weight: 700; margin-bottom: 6px; }
        .badge {
            display: inline-flex; align-items: center; gap: 5px;
            padding: 3px 10px; border-radius: 999px; font-size: 0.75em; font-weight: 700;
            background: color-mix(in srgb, var(--tone, var(--blue)) 16%, transparent);
            color: var(--tone, var(--blue));
        }
        .link {
            flex-shrink: 0; color: var(--text); text-decoration: none; font-size: 0.8em;
            padding: 6px 12px; border-radius: 10px;
            background: var(--surface-2); border: 1px solid var(--border);
            transition: background .2s, border-color .2s;
        }
        .link:hover { background: var(--accent); border-color: var(--accent); }

        .price-row { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 16px; }
        .price-now .lbl, .pnl-box .lbl { color: var(--muted); font-size: 0.78em; margin-bottom: 2px; }
        .price-now .big { font-size: 2em; font-weight: 800; color: var(--blue); line-height: 1; }
        .pnl-box { text-align: left; }
        .pnl-box .big { font-size: 1.35em; font-weight: 800; line-height: 1.1; }
        .pnl-box .usd { font-size: 0.82em; color: var(--muted); }
        .pos { color: var(--green); }
        .neg { color: var(--red); }

        .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
        .stat {
            background: rgba(0,0,0,0.25); border-radius: 10px; padding: 9px 6px; text-align: center;
        }
        .stat .lbl { color: var(--muted); font-size: 0.7em; margin-bottom: 3px; }
        .stat .v { font-weight: 700; font-size: 0.98em; }
        .c-stop { color: var(--red); }
        .c-tp { color: var(--green); }

        /* Range bar: stop-loss on the left → take-profit on the right */
        .range { margin-top: 18px; direction: ltr; }
        .track {
            position: relative; height: 8px; border-radius: 999px;
            background: linear-gradient(90deg, rgba(255,90,110,0.35), rgba(255,255,255,0.08) 50%, rgba(34,211,155,0.35));
        }
        .buy-tick {
            position: absolute; top: -3px; width: 2px; height: 14px;
            background: rgba(255,255,255,0.55); transform: translateX(-50%); border-radius: 2px;
        }
        .thumb {
            position: absolute; top: 50%; width: 16px; height: 16px; border-radius: 50%;
            transform: translate(-50%, -50%);
            background: var(--tone, var(--blue)); border: 3px solid var(--bg);
            box-shadow: 0 0 0 2px var(--tone, var(--blue)), 0 0 14px var(--tone, var(--blue));
        }
        .range-labels {
            display: flex; justify-content: space-between; margin-top: 8px;
            font-size: 0.72em; color: var(--muted);
        }
        .note { margin-top: 12px; font-size: 0.8em; color: var(--muted); }

        .empty {
            text-align: center; padding: 60px 20px; color: var(--muted);
            background: var(--surface); border: 1px dashed var(--border); border-radius: 18px;
        }
        .empty .icon { font-size: 40px; margin-bottom: 10px; }

        .footer {
            display: flex; justify-content: center; align-items: center; gap: 14px;
            flex-wrap: wrap; margin-top: 30px; color: var(--muted); font-size: 0.85em;
        }
        .refresh-btn {
            font-family: inherit; font-weight: 700; font-size: 0.95em;
            padding: 11px 26px; border: none; border-radius: 12px; cursor: pointer; color: #fff;
            background: linear-gradient(135deg, var(--accent), #ff6b6b);
            box-shadow: 0 10px 24px -10px rgba(233,69,96,0.8);
            transition: transform .15s, opacity .15s;
        }
        .refresh-btn:hover { transform: translateY(-1px); opacity: .92; }

        @media (max-width: 820px) {
            .summary { grid-template-columns: repeat(2, 1fr); }
            .grid { grid-template-columns: 1fr; }
        }
        @media (max-width: 420px) {
            .stats { grid-template-columns: repeat(2, 1fr); }
            .brand h1 { font-size: 1.3em; }
        }
    </style>
</head>
<body>
<div class="container">
    <header class="header">
        <div class="brand">
            <div class="logo">📊</div>
            <div>
                <h1>مراقب صفقات <span>بوليماركت</span></h1>
                <p>دوري أمم أوروبا</p>
            </div>
        </div>
        <div class="live"><span class="dot"></span> مباشر · آخر تحديث <span class="num">{{ last_update }}</span></div>
    </header>

    <section class="summary">
        <div class="kpi">
            <div class="lbl">الصفقات المفتوحة</div>
            <div class="val num">{{ positions|length }}</div>
            <div class="sub">{{ winners }} رابحة · {{ losers }} خاسرة</div>
        </div>
        <div class="kpi">
            <div class="lbl">متوسط الأداء</div>
            <div class="val num {% if total_pnl >= 0 %}pos{% else %}neg{% endif %}">
                {% if total_pnl >= 0 %}+{% endif %}{{ "%.1f"|format(total_pnl) }}%
            </div>
            <div class="sub">على الصفقات المسعّرة</div>
        </div>
        <div class="kpi">
            <div class="lbl">رأس المال المستثمر</div>
            <div class="val num">${{ "%.2f"|format(total_cost) }}</div>
            <div class="sub">للصفقات المسعّرة بسعر الشراء</div>
        </div>
        <div class="kpi">
            <div class="lbl">الربح / الخسارة</div>
            <div class="val num {% if total_pnl_usd >= 0 %}pos{% else %}neg{% endif %}">
                {% if total_pnl_usd >= 0 %}+${{ "%.2f"|format(total_pnl_usd) }}{% else %}-${{ "%.2f"|format(-total_pnl_usd) }}{% endif %}
            </div>
            <div class="sub">القيمة الحالية <span class="num">${{ "%.2f"|format(total_value) }}</span></div>
        </div>
    </section>

    <div class="section-title">
        <h2>الصفقات</h2>
        <span>{% if data_source == 'wallet' %}مكتشفة تلقائياً من المحفظة{% else %}من ملف config.json{% endif %} · تحديث تلقائي كل 30 ثانية</span>
    </div>

    {% if error %}<div class="note" style="margin-bottom:14px;color:var(--amber)">⚠ تعذر الوصول للمحفظة، يتم العرض من config.json مؤقتاً</div>{% endif %}

    {% if positions %}
    <div class="grid">
        {% for pos in positions %}
        <article class="card {{ pos.status }}">
            <div class="card-top">
                <div>
                    <div class="name">{{ pos.name }}</div>
                    {% if pos.status == 'profit' %}<span class="badge">▲ في الربح</span>
                    {% elif pos.status == 'loss' %}<span class="badge">▼ في الخسارة</span>
                    {% elif pos.status == 'error' %}<span class="badge">⚠ تعذر جلب السعر</span>
                    {% else %}<span class="badge">● عند سعر الشراء</span>{% endif %}
                </div>
                <a href="{{ pos.url }}" target="_blank" rel="noopener" class="link">فتح الصفقة ↗</a>
            </div>

            <div class="price-row">
                <div class="price-now">
                    <div class="lbl">السعر الحالي</div>
                    <div class="big num">{% if pos.current_price is not none %}{{ pos.current_price }}¢{% else %}—{% endif %}</div>
                </div>
                <div class="pnl-box">
                    <div class="lbl">الأداء</div>
                    {% if pos.pnl is not none %}
                    <div class="big num {% if pos.pnl >= 0 %}pos{% else %}neg{% endif %}">{% if pos.pnl >= 0 %}+{% endif %}{{ "%.1f"|format(pos.pnl) }}%</div>
                    <div class="usd num">{% if pos.pnl_usd >= 0 %}+${{ "%.2f"|format(pos.pnl_usd) }}{% else %}-${{ "%.2f"|format(-pos.pnl_usd) }}{% endif %}</div>
                    {% else %}<div class="big">—</div>{% endif %}
                </div>
            </div>

            <div class="stats">
                <div class="stat"><div class="lbl">الشراء</div><div class="v num">{{ pos.buy_price }}¢</div></div>
                <div class="stat"><div class="lbl">وقف الخسارة</div><div class="v num c-stop">{{ pos.stop_loss }}¢</div></div>
                <div class="stat"><div class="lbl">الهدف</div><div class="v num c-tp">{{ pos.take_profit }}¢</div></div>
                <div class="stat"><div class="lbl">الأسهم</div><div class="v num">{{ pos.shares }}</div></div>
            </div>

            {% if pos.thumb_pct is not none %}
            <div class="range">
                <div class="track">
                    <div class="buy-tick" style="left: {{ pos.buy_pct }}%"></div>
                    <div class="thumb" style="left: {{ pos.thumb_pct }}%"></div>
                </div>
                <div class="range-labels">
                    <span class="c-stop num">SL {{ pos.stop_loss }}¢</span>
                    <span class="num">Buy {{ pos.buy_price }}¢</span>
                    <span class="c-tp num">TP {{ pos.take_profit }}¢</span>
                </div>
            </div>
            {% endif %}

            {% if pos.notes %}<div class="note">📝 {{ pos.notes }}</div>{% endif %}
        </article>
        {% endfor %}
    </div>
    {% else %}
    <div class="empty">
        <div class="icon">📭</div>
        <div>لا توجد صفقات مفتوحة حالياً</div>
        {% if data_source == 'wallet' %}<div class="note">تأكد أن WALLET_ADDRESS هو عنوان محفظة Polymarket (من صفحة البروفايل) وليس عنوان المفتاح</div>{% endif %}
    </div>
    {% endif %}

    <footer class="footer">
        <button class="refresh-btn" onclick="location.reload()">🔄 تحديث الأسعار</button>
    </footer>
</div>
</body>
</html>
"""


def enrich(pos):
    """Adds dashboard-only fields: status and range-bar positions."""
    cur, buy = pos["current_price"], pos["buy_price"]
    stop, tp = pos["stop_loss"], pos["take_profit"]

    status = "hold"
    if cur is None:
        status = "error"
    elif cur >= tp:
        status = "profit"
    elif cur <= stop:
        status = "loss"
    elif pos["pnl"] is not None and pos["pnl"] > 0:
        status = "profit"
    elif pos["pnl"] is not None and pos["pnl"] < 0:
        status = "loss"

    # Positions on the stop-loss → take-profit bar, clamped to 0–100%
    thumb_pct = buy_pct = None
    span = tp - stop
    if cur is not None and span > 0:
        clamp = lambda v: max(0, min(100, round(v, 1)))
        thumb_pct = clamp((cur - stop) / span * 100)
        buy_pct = clamp((buy - stop) / span * 100)

    return {**pos, "status": status, "thumb_pct": thumb_pct, "buy_pct": buy_pct}


@app.route("/")
def home():
    raw, source, error = load_positions()
    positions = [enrich(p) for p in raw]

    priced = [p for p in positions if p["current_price"] is not None]
    total_cost = sum(p["shares"] * p["buy_price"] / 100 for p in priced)
    total_value = sum(p["shares"] * p["current_price"] / 100 for p in priced)
    pnl_list = [p["pnl"] for p in priced if p["pnl"] is not None]
    total_pnl = round(sum(pnl_list) / len(pnl_list), 1) if pnl_list else 0

    return render_template_string(
        DASHBOARD_TEMPLATE,
        positions=positions,
        data_source=source,
        error=error,
        total_pnl=total_pnl,
        total_cost=round(total_cost, 2),
        total_value=round(total_value, 2),
        total_pnl_usd=round(total_value - total_cost, 2),
        winners=sum(1 for p in positions if p["status"] == "profit"),
        losers=sum(1 for p in positions if p["status"] == "loss"),
        last_update=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )


@app.route("/api/positions")
def api_positions():
    from flask import make_response
    positions, source, error = load_positions()
    resp = make_response(jsonify({
        "positions": positions,
        "source": source,
        "error": error,
        "updated_at": datetime.now().isoformat(),
    }))
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@app.route("/health")
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})


@app.route("/api/alerts/status")
def alerts_status():
    """Is the monitor running, did the last alerts go out, and is selling set up?
    No secrets here."""
    import alerts
    import paper_trading
    import telegram_actions
    import trading
    from polymarket_monitor import STATE
    return jsonify({
        "monitor": STATE,
        "channels": alerts.status(),
        "telegram_commands": telegram_actions.STATE,
        "trading": trading.status(),
        "paper_trading": paper_trading.STATE,
    })


def start_monitor():
    try:
        from polymarket_monitor import main as monitor_main
        logger.info("🔍 بدء مراقبة الصفقات المفتوحة...")
        monitor_main()
    except Exception as e:
        logger.error(f"خطأ في المراقب: {e}")


def start_telegram_commands():
    try:
        from telegram_actions import poll_forever
        poll_forever()
    except Exception as e:
        logger.error(f"خطأ في أوامر تيليجرام: {e}")


def start_paper_trading():
    try:
        from paper_trading import run_forever
        run_forever()
    except Exception as e:
        logger.error(f"خطأ في التداول على الورق: {e}")


_monitor_started = False


def ensure_monitor():
    """Start the alert monitor, the Telegram command listener and paper
    trading once per process (gunicorn never runs __main__)."""
    global _monitor_started
    if _monitor_started or os.environ.get("ENABLE_MONITOR", "1") == "0":
        return
    _monitor_started = True
    threading.Thread(target=start_monitor, daemon=True).start()
    logger.info("✅ مراقب الأسعار شغّال في الخلفية")
    if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
        threading.Thread(target=start_telegram_commands, daemon=True).start()
    import paper_trading
    if paper_trading.ledger_available():  # paper trading and the stop-alert review
        threading.Thread(target=start_paper_trading, daemon=True).start()


# Run a single process (one gunicorn worker): one monitor, one Telegram poller
ensure_monitor()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") == "development"
    logger.info(f"🚀 بدء التطبيق على المنفذ {port}")
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)
