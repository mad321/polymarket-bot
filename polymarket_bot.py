import os
import logging
import threading
from flask import Flask, render_template_string, jsonify, request, make_response
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

        /* Strategy 3.0 paper test */
        .strict { margin-top: 36px; }
        .strict .summary { grid-template-columns: repeat(3, 1fr); }
        .table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 16px; background: var(--surface); }
        .table-wrap table { width: 100%; min-width: 640px; border-collapse: collapse; font-size: 0.88em; }
        .table-wrap th { color: var(--muted); font-weight: 600; text-align: start; padding: 10px 12px; border-bottom: 1px solid var(--border); }
        .table-wrap td { padding: 10px 12px; border-bottom: 1px solid var(--border); white-space: nowrap; }
        .table-wrap tr:last-child td { border-bottom: none; }
        .tag { display: inline-block; margin-inline-start: 6px; padding: 1px 8px; border-radius: 999px; font-size: 0.75em; color: var(--blue); border: 1px solid rgba(76,201,240,0.4); }
        .inds { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; margin-bottom: 14px; }
        .ind { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 16px 18px; }
        .ind h3 { font-size: 1em; font-weight: 700; margin-bottom: 2px; }
        .ind .why { color: var(--muted); font-size: 0.78em; margin-bottom: 12px; }
        .ind .row { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; margin-top: 6px; font-size: 0.9em; }
        .ind .row .lbl { color: var(--muted); }
        .chip { display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 0.8em; font-weight: 700; }
        .chip.good { color: var(--green); background: rgba(34,211,155,0.12); }
        .chip.bad { color: var(--red); background: rgba(255,90,110,0.12); }
        .chip.wait { color: var(--amber); background: rgba(245,185,66,0.12); }
        .bar { height: 8px; border-radius: 999px; background: var(--surface-2); overflow: hidden; margin-top: 10px; }
        .bar > div { height: 100%; background: linear-gradient(90deg, var(--blue), var(--green)); }
        .warn { margin-bottom: 14px; padding: 12px 16px; border-radius: 14px; background: var(--surface); border: 1px solid var(--border); color: var(--amber); font-size: 0.9em; }

        @media (max-width: 820px) {
            .summary, .strict .summary { grid-template-columns: repeat(2, 1fr); }
            .inds { grid-template-columns: 1fr; }
            .grid { grid-template-columns: 1fr; }
        }
        @media (max-width: 420px) {
            .stats { grid-template-columns: repeat(2, 1fr); }
            .brand h1 { font-size: 1.3em; }
        }
    </style>
</head>
<body>
{% macro indicator(i, title, why) %}
<div class="ind">
    <div class="row" style="margin-top:0"><h3>{{ title }}</h3><span class="chip {{ i.tone }}">{{ i.status }}</span></div>
    <div class="why">{{ why }}</div>
    <div class="row"><span class="lbl">نسبة الربح</span>
        <span>{% if i.rate is none %}—{% else %}{% if i.n %}<span style="color:var(--muted);font-size:.85em">(المدى <span class="num">{{ "%.0f"|format(i.low * 100) }}–{{ "%.0f"|format(i.high * 100) }}%</span>)</span> {% endif %}<span class="num {% if i.rate >= 0.57 %}pos{% else %}neg{% endif %}">{{ "%.0f"|format(i.rate * 100) }}%</span>{% endif %}</span></div>
    <div class="row"><span class="lbl">الصافي</span>
        <span class="num {% if i.pnl >= 0 %}pos{% else %}neg{% endif %}">{% if i.pnl >= 0 %}+${{ "%.2f"|format(i.pnl) }}{% else %}-${{ "%.2f"|format(-i.pnl) }}{% endif %}{% if i.ret is not none %} ({{ "%+.1f"|format(i.ret * 100) }}%){% endif %}</span></div>
    <div class="row"><span class="lbl">الطريق إلى الحكم</span><span class="num">{{ i.n }} / 30 صفقة</span></div>
    <div class="bar"><div style="width: {{ i.progress }}%"></div></div>
</div>
{% endmacro %}
<div class="container">
    <header class="header">
        <div class="brand">
            <div class="logo">📊</div>
            <div>
                <h1>مراقب صفقات <span>بوليماركت</span></h1>
                <p>صفقاتك وتجارب الاستراتيجية</p>
            </div>
        </div>
        <div class="live"><span class="dot"></span> مباشر · آخر تحديث <span class="num">{{ last_update }}</span></div>
    </header>

    {% if private %}
    <section class="summary">
        <div class="kpi"><div class="lbl">💼 قيمة المحفظة الآن</div>
            <div class="val num">{% if wallet_value is not none %}${{ "{:,.2f}".format(wallet_value) }}{% else %}—{% endif %}</div>
            <div class="sub">النقد + الصفقات المفتوحة بسعرها الحالي</div></div>
        <div class="kpi"><div class="lbl">💵 الكاش المتوفر</div>
            <div class="val num">{% if cash is not none %}${{ "{:,.2f}".format(cash) }}{% else %}—{% endif %}</div>
            <div class="sub">{% if cash is none %}تعذّرت القراءة الآن{% elif wallet_value %}{{ "%.0f"|format(cash / wallet_value * 100) }}% من المحفظة{% endif %}</div></div>
        <div class="kpi"><div class="lbl">📈 الصفقات المفتوحة</div>
            <div class="val num">${{ "{:,.2f}".format(total_value) }}</div>
            <div class="sub">بالسعر الحالي</div></div>
        <div class="kpi"><div class="lbl">🎯 حجم الصفقة المقترح (2%)</div>
            <div class="val num">{% if wallet_value %}${{ "%.2f"|format(wallet_value * 0.02) }}{% else %}—{% endif %}</div>
            <div class="sub">مبلغ رسالة الشراء القادمة تقريباً</div></div>
    </section>
    {% elif private_hint %}<div class="warn">{{ private_hint }}</div>{% endif %}

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

    {% if private and journal %}
    <section class="strict">
        <div class="section-title">
            <h2>📘 ما تعلمناه من صفقاتك الحقيقية</h2>
            <span>صفقات "هل سيفوز الفريق؟" منذ 1 أكتوبر · تُحدَّث بعد كل صفقة تُغلق</span>
        </div>
        <div class="inds">
            {{ indicator(journal.indicators.actual, "مؤشر صفقاتك الحقيقية منذ 3.0", "منذ " ~ journal.indicators.since ~ "، كما تداولتها فعلاً") }}
            {{ indicator(journal.indicators.hold, "لو احتفظت بها حتى النهاية", "نفس الصفقات، على ما حُسم سوقه") }}
        </div>
        <div class="summary">
            <div class="kpi"><div class="lbl">صفقات أُغلقت</div><div class="val num">{{ journal.n }}</div>
                <div class="sub">ربح {{ journal.wins }}{% if journal.n %} ({{ "%.0f"|format(journal.wins / journal.n * 100) }}%){% endif %}</div></div>
            <div class="kpi"><div class="lbl">الصافي</div>
                <div class="val num {% if journal.pnl >= 0 %}pos{% else %}neg{% endif %}">{% if journal.pnl >= 0 %}+${{ "%.2f"|format(journal.pnl) }}{% else %}-${{ "%.2f"|format(-journal.pnl) }}{% endif %}</div>
                <div class="sub">من <span class="num">${{ "%.2f"|format(journal.cost) }}</span></div></div>
            <div class="kpi"><div class="lbl">لو احتفظت بكل صفقة حتى النهاية</div>
                <div class="val num {% if journal.hold >= 0 %}pos{% else %}neg{% endif %}">{% if journal.hold >= 0 %}+${{ "%.2f"|format(journal.hold) }}{% else %}-${{ "%.2f"|format(-journal.hold) }}{% endif %}</div>
                <div class="sub">على {{ journal.hold_n }} صفقة حُسم سوقها، وصافيها الفعلي <span class="num">{% if journal.hold_pnl_same >= 0 %}+{% else %}-{% endif %}${{ "%.2f"|format(journal.hold_pnl_same|abs) }}</span></div></div>
        </div>
        <div class="table-wrap">
            <table>
                <thead><tr><th>المجموعة</th><th>صفقات</th><th>نسبة الربح</th><th>المدى المحتمل</th><th>الصافي</th><th>لو احتفظت</th><th>الحكم</th></tr></thead>
                <tbody>
                {% for g in journal.groups %}
                <tr>
                    <td>{{ g.dim }}: <bdi>{{ g.name }}</bdi></td>
                    <td class="num">{{ g.n }}</td>
                    <td class="num {% if g.rate >= 0.57 %}pos{% else %}neg{% endif %}">{{ "%.0f"|format(g.rate * 100) }}%</td>
                    <td class="num">{{ "%.0f"|format(g.low * 100) }}–{{ "%.0f"|format(g.high * 100) }}%</td>
                    <td class="num {% if g.pnl >= 0 %}pos{% else %}neg{% endif %}">{% if g.pnl >= 0 %}+${{ "%.2f"|format(g.pnl) }}{% else %}-${{ "%.2f"|format(-g.pnl) }}{% endif %}</td>
                    <td class="num">{% if g.hold_n %}{% if g.hold >= 0 %}+${{ "%.2f"|format(g.hold) }}{% else %}-${{ "%.2f"|format(-g.hold) }}{% endif %}{% else %}—{% endif %}</td>
                    <td>{{ g.verdict }}</td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
        <div class="note">"فرضية" = أقل من 30 صفقة. "يربح" أو "يخسر" = 30 صفقة أو أكثر والمدى كله فوق أو تحت التعادل (≈57%). "لو احتفظت" على الصفقات التي حُسم سوقها فقط.</div>
    </section>
    {% endif %}

    <section class="strict">
        <div class="section-title">
            <h2>🛡️ الميزان الصارم 3.0 · تجربة على الورق</h2>
            <span>بدون مال حقيقي · $25 للصفقة · 55–72¢ · بيع عند +20% أو −20%</span>
        </div>
        {% if strict is none %}
        <div class="warn">البوت ما زال يحمّل سجل التجربة، حدّث الصفحة بعد دقيقة.</div>
        {% else %}
        <div class="inds">
            {{ indicator(strict.indicators.pick, "⭐ مؤشر 3.1 الحالية: صفقة اليوم، احتفاظ حتى النهاية", "صفقة واحدة في اليوم: المرشح الأقل سعراً، بلا هدف ولا وقف") }}
            {{ indicator(strict.indicators.strategy, "مؤشر 3.0 كما هي", "بيع عند +20% أو −20%") }}
            {{ indicator(strict.indicators.hold, "مؤشر 3.1: نفس الدخول، احتفاظ حتى النهاية", "نفس الصفقات بلا هدف ولا وقف: المقارنة التي يقترحها سجلك") }}
        </div>
        {% if strict.settled < 30 %}<div class="warn">⚠️ <span class="num">{{ strict.settled }}</span> صفقة فقط: الحكم يحتاج 30 صفقة محسومة على الأقل.</div>{% endif %}
        <div class="summary">
            <div class="kpi"><div class="lbl">صفقات محسومة</div><div class="val num">{{ strict.settled }}</div>
                <div class="sub">{% if strict.open %}و {{ strict.open }} جارية{% else %}لا صفقات جارية{% endif %}</div></div>
            <div class="kpi"><div class="lbl">نسبة الربح</div>
                <div class="val num {% if strict.win_rate is not none %}{% if strict.win_rate >= strict.break_even %}pos{% else %}neg{% endif %}{% endif %}">{% if strict.win_rate is none %}—{% else %}{{ "%.0f"|format(strict.win_rate) }}%{% endif %}</div>
                <div class="sub">المطلوب {{ "%.0f"|format(strict.goal) }}% · التعادل ≈{{ strict.break_even }}%</div></div>
            <div class="kpi"><div class="lbl">الصافي</div>
                <div class="val num {% if strict.pnl >= 0 %}pos{% else %}neg{% endif %}">{% if strict.pnl >= 0 %}+${{ "%.2f"|format(strict.pnl) }}{% else %}-${{ "%.2f"|format(-strict.pnl) }}{% endif %}</div>
                <div class="sub num">{% if strict.pnl_pct is not none %}{{ "%+.1f"|format(strict.pnl_pct) }}%{% endif %}</div></div>
            <div class="kpi"><div class="lbl">لو احتفظت حتى النهاية</div>
                <div class="val num {% if strict.hold >= 0 %}pos{% else %}neg{% endif %}">{% if strict.hold >= 0 %}+${{ "%.2f"|format(strict.hold) }}{% else %}-${{ "%.2f"|format(-strict.hold) }}{% endif %}</div>
                <div class="sub">{% if strict.settled %}{% if strict.pnl > strict.hold %}الاستراتيجية أفضل بـ <span class="num">${{ "%.2f"|format(strict.pnl - strict.hold) }}</span>{% elif strict.pnl < strict.hold %}الاحتفاظ أفضل بـ <span class="num">${{ "%.2f"|format(strict.hold - strict.pnl) }}</span>{% else %}لا فرق{% endif %}{% endif %}</div></div>
            <div class="kpi"><div class="lbl">طريقة الخروج</div>
                <div class="val" style="font-size:1.2em">🎯 <span class="num">{{ strict.targets }}</span> · 🛑 <span class="num">{{ strict.stops }}</span> · ⏱️ <span class="num">{{ strict.held }}</span></div>
                <div class="sub">هدف +20% · وقف −20% · حتى النهاية</div></div>
            <div class="kpi"><div class="lbl">مباريات تُركت</div><div class="val num">{{ strict.skipped_volume + strict.skipped_price }}</div>
                <div class="sub">حجم أقل من <span class="num">$15,000</span>: {{ strict.skipped_volume }} · سعر خارج <span class="num">55–72¢</span>: {{ strict.skipped_price }}</div></div>
        </div>
        <div class="table-wrap">
            {% if strict.rows %}
            <table>
                <thead><tr><th>المباراة</th><th>الفريق</th><th>الدخول</th><th>الخروج</th><th>فاز الفريق؟</th><th>الربح</th><th>لو احتفظت</th></tr></thead>
                <tbody>
                {% for r in strict.rows %}
                <tr>
                    <td><bdi>{{ r.title }}</bdi>{% if r.open %}<span class="tag">جارية</span>{% endif %}</td>
                    <td><bdi>{{ r.team }}</bdi></td>
                    <td class="num">{{ "%.0f"|format(r.entry) }}¢</td>
                    <td>{{ r.exit }}</td>
                    <td>{% if r.won is none %}—{% elif r.won %}✅{% else %}❌{% endif %}</td>
                    <td class="num {% if r.pnl is not none %}{% if r.pnl >= 0 %}pos{% else %}neg{% endif %}{% endif %}">{% if r.pnl is none %}—{% elif r.pnl >= 0 %}+${{ "%.2f"|format(r.pnl) }}{% else %}-${{ "%.2f"|format(-r.pnl) }}{% endif %}</td>
                    <td class="num {% if r.hold is not none %}{% if r.hold >= 0 %}pos{% else %}neg{% endif %}{% endif %}">{% if r.hold is none %}—{% elif r.hold >= 0 %}+${{ "%.2f"|format(r.hold) }}{% else %}-${{ "%.2f"|format(-r.hold) }}{% endif %}</td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
            {% else %}<div class="empty" style="border:none">لا توجد صفقات ورقية بعد.</div>{% endif %}
        </div>
        {% endif %}
    </section>

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

    private = _private_figures(total_value)
    html = render_template_string(
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
        last_update=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        strict=_strict_figures(),
        **private,
    )
    response = make_response(html)
    if private["private"] and request.args.get("key"):
        response.set_cookie("dashboard_key", request.args["key"].strip(), max_age=30 * 24 * 3600,
                            httponly=True, secure=True, samesite="Lax")
    return response


def _private_figures(total_value):
    """Wallet value, cash and the trade journal, only for the owner's link
    (/?key=DASHBOARD_KEY, then a cookie). The page is public otherwise."""
    import hmac
    clean = lambda v: (v or "").strip(" \t\r\n\"'`\u200b\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u202d\u202e")
    expected = clean(os.environ.get("DASHBOARD_KEY"))
    typed = clean(request.args.get("key"))
    given = typed or clean(request.cookies.get("dashboard_key"))
    if not expected:
        return {"private": False, "private_hint": "لعرض قيمة المحفظة والكاش وما تعلمناه: أضف DASHBOARD_KEY في Render "
                                                  "ثم افتح هذه الصفحة بـ ?key= وقيمته."}
    if not hmac.compare_digest(given.encode(), expected.encode()):
        hint = None
        if typed:  # say why, without saying anything about the key itself
            hint = ("🔒 الكلمة في الرابط لا تطابق DASHBOARD_KEY في Render. استخدم حروفاً إنجليزية وأرقاماً فقط "
                    "(بلا مسافات ولا رموز مثل + # & %)، وتأكد أن الرابط ينتهي بـ ?key= ثم الكلمة نفسها.")
        return {"private": False, "private_hint": hint}
    import exposure
    import paper_trading
    cash = exposure.cash()
    return {"private": True, "private_hint": None, "cash": cash,
            "wallet_value": None if cash is None else cash + total_value,
            "journal": paper_trading.journal_figures()}


def _strict_figures():
    """Strategy 3.0 paper results for the page, or None until the ledger is loaded."""
    import paper_trading
    import strict_strategy
    ledger = paper_trading.public_ledger()
    if ledger is None:
        return None
    return strict_strategy.dashboard(ledger.get("strict_test") or {})


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
    import auto_stop
    import live_feed
    import exposure
    import match_strategy
    import strict_strategy
    import paper_trading
    import telegram_actions
    import trading
    from polymarket_monitor import STATE
    return jsonify({
        "monitor": STATE,
        "channels": alerts.status(),
        "telegram_commands": telegram_actions.STATE,
        "trading": trading.status(),
        "auto_stop": auto_stop.status(),
        "live_feed": live_feed.status(),
        "paper_trading": paper_trading.STATE,
        "position_size": exposure.STATE,
        "match_test": match_strategy.STATE,
        "strict_test": {**strict_strategy.STATE, "enabled": strict_strategy.enabled()},
    })


@app.route("/api/paper")
def paper_ledger():
    """The paper-trading ledger, for analysis: no keys, balances or wallet addresses."""
    import paper_trading
    ledger = paper_trading.public_ledger()
    if ledger is None:
        return jsonify({"error": "the ledger is not loaded yet"}), 503
    return jsonify(ledger)


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
        import live_feed
        live_feed.start()  # second-by-second prices and scores for the games the loop watches


# Run a single process (one gunicorn worker): one monitor, one Telegram poller
ensure_monitor()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") == "development"
    logger.info(f"🚀 بدء التطبيق على المنفذ {port}")
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)
