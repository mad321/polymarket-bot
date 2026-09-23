import os
import requests
from flask import Flask, jsonify, request
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs

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

@app.route("/")
def home():
    return "Polymarket Dual-AI Arena Bot is Active!", 200

@app.route("/market-info/<market_slug>")
def market_info(market_slug):
    try:
        response = requests.get(f"{GAMMA_API_URL}/markets/{market_slug}")
        if response.status_code != 200:
            return jsonify({"error": "Market not found"}), 404
        return jsonify(response.json()), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/ai-trade/claude/<market_slug>")
def claude_strategy(market_slug):
    try:
        res = requests.get(f"{GAMMA_API_URL}/markets/{market_slug}")
        if res.status_code != 200:
            return jsonify({"model": "Claude", "error": "Market not found"}), 404
        
        market_data = res.json()
        question = market_data.get("question")
        
        decision = {
            "model": "Claude",
            "market": question,
            "analysis": "Simulated analysis based on market sentiment and probabilities.",
            "recommended_action": "HOLD / SIMULATED BUY",
            "confidence_score": "78%",
            "mode": "Paper Trading (Test Phase)"
        }
        return jsonify(decision), 200
    except Exception as e:
        return jsonify({"model": "Claude", "error": str(e)}), 500

@app.route("/ai-trade/gemini/<market_slug>")
def gemini_strategy(market_slug):
    try:
        res = requests.get(f"{GAMMA_API_URL}/markets/{market_slug}")
        if res.status_code != 200:
            return jsonify({"model": "Gemini", "error": "Market not found"}), 404
        
        market_data = res.json()
        question = market_data.get("question")
        
        decision = {
            "model": "Gemini",
            "market": question,
            "analysis": "Simulated quantitative and event-driven probability breakdown.",
            "recommended_action": "SIMULATED BUY",
            "confidence_score": "82%",
            "mode": "Paper Trading (Test Phase)"
        }
        return jsonify(decision), 200
    except Exception as e:
        return jsonify({"model": "Gemini", "error": str(e)}), 500

@app.route("/risk-check")
def risk_check():
    return jsonify({
        "status": "Connected successfully",
        "wallet_address": wallet_address,
        "active_arenas": ["Claude Strategy", "Gemini Strategy"],
        "phase": "1-Day / 1-Week Paper Trading Test"
    }), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
