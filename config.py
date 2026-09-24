import os
from dotenv import load_dotenv

load_dotenv()

# Polymarket Configuration
POLYMARKET_HOST = "https://clob.polymarket.com"
GAMMA_API_URL = "https://gamma-api.polymarket.com"
CHAIN_ID = 137

# API Keys
PRIVATE_KEY = os.environ.get("PRIVATE_KEY")
WALLET_ADDRESS = os.environ.get("WALLET_ADDRESS")
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Trading Constraints
TIME_BUFFER_DAILY = 12 * 3600  # 12 hours in seconds
TIME_BUFFER_WEEKLY = 3 * 24 * 3600  # 3 days in seconds
MIN_LIQUIDITY_THRESHOLD = 100  # Minimum $100 in liquidity

# Allowed Markets with Live Fetching
ALLOWED_MARKETS = {
    "bitcoin-daily": {
        "name": "Crypto - Bitcoin Daily",
        "query": "bitcoin price target daily",
        "type": "daily",
        "search_term": "Bitcoin"
    },
    "bitcoin-weekly": {
        "name": "Crypto - Bitcoin Weekly",
        "query": "bitcoin price target weekly",
        "type": "weekly",
        "search_term": "Bitcoin"
    },
    "fed-rate-decision": {
        "name": "Macro - Fed Rates",
        "query": "fed interest rate decision next meeting",
        "type": "daily",
        "search_term": "Fed"
    }
}

# Model Configuration
CLAUDE_MODEL = "claude-3-5-haiku-20241022"
GEMINI_MODEL = "gemini-1.5-flash"
MAX_TOKENS = 500
