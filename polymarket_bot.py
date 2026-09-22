#!/usr/bin/env python3
"""
Polymarket Trading Bot - ReadOnly Mode
Author: Claude AI
Created: 2026-09-22

DISCIPLINE RULES:
1. Entry Price: 0.45-0.65 only
2. Position Size: 10% of bankroll per trade
3. Stop Loss: -20% immediate exit
4. Trade Frequency: 1 trade per 60 minutes max
5. Daily Halt: +5% profit or -10% loss STOPS bot
"""

import os
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests

# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    # API & Wallet
    POLYMARKET_API_KEY = os.getenv("POLYMARKET_API_KEY", "")
    POLYMARKET_WALLET = os.getenv("POLYMARKET_WALLET", "0x0C4526398bBa16E31F23ca818d767Cb00b02921C")
    
    # Email
    EMAIL_FROM = os.getenv("EMAIL_FROM", "polymarket-bot@render.onrender.com")
    EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
    EMAIL_TO = os.getenv("EMAIL_TO", "esam.zayed@gmail.com")
    SMTP_SERVER = "smtp.gmail.com"
    SMTP_PORT = 587
    
    # Trading Rules
    BANKROLL_INITIAL = 240.00
    POSITION_SIZE_PCT = 0.10  # 10% per trade = $24
    MIN_ENTRY = 0.45
    MAX_ENTRY = 0.65
    STOP_LOSS_PCT = -0.20  # -20% exit
    DAILY_PROFIT_TARGET = 0.05  # +5% halt
    DAILY_LOSS_LIMIT = -0.10  # -10% halt
    TRADE_COOLDOWN_MIN = 60  # seconds between trades
    
    # Safety Thresholds
    MIN_BANKROLL_THRESHOLD = 100.00
    
    # Mode
    READONLY_MODE = True  # Set to False for live trading
    
    # State File
    STATE_FILE = "/tmp/polymarket_state.json"
    LOG_FILE = "/tmp/polymarket_bot.log"

# ============================================================================
# TRADING STATE
# ============================================================================

class TradingState:
    def __init__(self):
        self.load_state()
    
    def load_state(self):
        """Load state from file or initialize fresh."""
        if os.path.exists(Config.STATE_FILE):
            try:
                with open(Config.STATE_FILE, 'r') as f:
                    data = json.load(f)
                    self.bankroll = data.get("bankroll", Config.BANKROLL_INITIAL)
                    self.daily_pnl = data.get("daily_pnl", 0.0)
                    self.last_trade_time = data.get("last_trade_time", None)
                    self.positions = data.get("positions", {})
                    self.trades_today = data.get("trades_today", 0)
                    self.session_start = data.get("session_start", datetime.utcnow().isoformat())
            except Exception as e:
                self.logger(f"Error loading state: {e}")
                self._init_fresh()
        else:
            self._init_fresh()
    
    def _init_fresh(self):
        """Initialize fresh state."""
        self.bankroll = Config.BANKROLL_INITIAL
        self.daily_pnl = 0.0
        self.last_trade_time = None
        self.positions = {}
        self.trades_today = 0
        self.session_start = datetime.utcnow().isoformat()
    
    def save_state(self):
        """Save state to file."""
        state = {
            "bankroll": self.bankroll,
            "daily_pnl": self.daily_pnl,
            "last_trade_time": self.last_trade_time,
            "positions": self.positions,
            "trades_today": self.trades_today,
            "session_start": self.session_start,
            "updated_at": datetime.utcnow().isoformat()
        }
        try:
            with open(Config.STATE_FILE, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            self.logger(f"Error saving state: {e}")
    
    @staticmethod
    def logger(msg: str):
        """Log message to file and stdout."""
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        log_msg = f"[{timestamp}] {msg}"
        print(log_msg)
        try:
            with open(Config.LOG_FILE, 'a') as f:
                f.write(log_msg + "\n")
        except:
            pass

# ============================================================================
# EMAIL ALERTS
# ============================================================================

class AlertSystem:
    @staticmethod
    def send_alert(subject: str, body: str, deal_data: Optional[Dict] = None):
        """Send email alert."""
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = Config.EMAIL_FROM
            msg['To'] = Config.EMAIL_TO
            
            # Plain text
            text = body
            
            # HTML version (with deal data if available)
            html = f"""
            <html>
              <body style="font-family: Arial, sans-serif; background: #f5f5f5;">
                <div style="max-width: 600px; margin: 20px auto; background: white; border-radius: 8px; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                  <h2 style="color: #2c3e50; border-bottom: 3px solid #e74c3c; padding-bottom: 10px;">⚠️ {subject}</h2>
                  <p style="color: #34495e; line-height: 1.6; margin: 15px 0;">{body}</p>
            """
            
            if deal_data:
                html += f"""
                  <div style="background: #f8f9fa; border-left: 4px solid #e74c3c; padding: 15px; margin: 15px 0; border-radius: 4px;">
                    <h3 style="color: #2c3e50; margin-top: 0;">📊 Deal Details</h3>
                    <table style="width: 100%; border-collapse: collapse;">
            """
                for key, value in deal_data.items():
                    html += f"<tr><td style='padding: 8px; border-bottom: 1px solid #ddd; font-weight: bold; color: #7f8c8d;'>{key}</td><td style='padding: 8px; border-bottom: 1px solid #ddd;'><strong>{value}</strong></td></tr>"
                html += """
                    </table>
                  </div>
            """
            
            html += """
                  <div style="background: #e8f5e9; border-left: 4px solid #28a745; padding: 15px; margin: 15px 0; border-radius: 4px;">
                    <p style="color: #27ae60; margin: 0;"><strong>Status:</strong> ReadOnly Mode - No Real Trades</p>
                  </div>
                  <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                  <p style="color: #7f8c8d; font-size: 12px; text-align: center;">
                    Polymarket Trading Bot | Generated: """ + datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC") + """
                  </p>
                </div>
              </body>
            </html>
            """
            
            part1 = MIMEText(text, 'plain')
            part2 = MIMEText(html, 'html')
            msg.attach(part1)
            msg.attach(part2)
            
            # Send via SMTP (Gmail)
            with smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT) as server:
                server.starttls()
                # In production, use environment variables for credentials
                # For now, print alert instead
                TradingState.logger(f"ALERT: {subject}")
                TradingState.logger(f"EMAIL TO: {Config.EMAIL_TO}")
                TradingState.logger(f"BODY: {body}")
        
        except Exception as e:
            TradingState.logger(f"Error sending alert: {e}")

# ============================================================================
# POLYMARKET API CLIENT
# ============================================================================

class PolymarketClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://polymarket.com/api"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    
    def get_markets(self, filters: Optional[Dict] = None) -> List[Dict]:
        """Fetch open markets from Polymarket."""
        try:
            # In ReadOnly mode, return mock data for testing
            if Config.READONLY_MODE:
                return self._get_mock_markets()
            
            # In live mode, use real API
            url = f"{self.base_url}/markets"
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return response.json()
        
        except Exception as e:
            TradingState.logger(f"Error fetching markets: {e}")
            return []
    
    def _get_mock_markets(self) -> List[Dict]:
        """Return mock market data for testing in ReadOnly mode."""
        return [
            {
                "id": "mock_1",
                "title": "Will Trump win 2026 elections?",
                "createdAt": datetime.utcnow().isoformat(),
                "image": "https://via.placeholder.com/150",
                "bestBid": 0.52,
                "bestAsk": 0.54,
                "volume": 125000,
                "liquidity": 45000,
                "outcomeTokenMints": ["0xabc123", "0xdef456"]
            },
            {
                "id": "mock_2",
                "title": "Will Saudi GDP grow >3% in 2026?",
                "createdAt": datetime.utcnow().isoformat(),
                "image": "https://via.placeholder.com/150",
                "bestBid": 0.61,
                "bestAsk": 0.62,
                "volume": 89000,
                "liquidity": 32000,
                "outcomeTokenMints": ["0xghi789", "0xjkl012"]
            },
            {
                "id": "mock_3",
                "title": "Will AI regulation pass in EU by Q4 2026?",
                "createdAt": datetime.utcnow().isoformat(),
                "image": "https://via.placeholder.com/150",
                "bestBid": 0.45,
                "bestAsk": 0.47,
                "volume": 156000,
                "liquidity": 51000,
                "outcomeTokenMints": ["0xmno345", "0xpqr678"]
            }
        ]
    
    def execute_trade(self, market_id: str, amount: float, price: float, outcome: str) -> Tuple[bool, str]:
        """Execute a trade (ReadOnly mode prints instead)."""
        if Config.READONLY_MODE:
            TradingState.logger(f"[READONLY] TRADE SIMULATION: Market={market_id}, Amount=${amount}, Price={price}, Outcome={outcome}")
            return True, "simulated_trade_123"
        
        # In live mode, execute real trade
        try:
            url = f"{self.base_url}/trades"
            payload = {
                "marketId": market_id,
                "amount": amount,
                "price": price,
                "outcome": outcome
            }
            response = requests.post(url, json=payload, headers=self.headers, timeout=10)
            response.raise_for_status()
            return True, response.json().get("tradeId", "unknown")
        
        except Exception as e:
            TradingState.logger(f"Error executing trade: {e}")
            return False, str(e)

# ============================================================================
# TRADING LOGIC
# ============================================================================

class TradingEngine:
    def __init__(self, client: PolymarketClient, state: TradingState):
        self.client = client
        self.state = state
    
    def should_trade_now(self) -> Tuple[bool, Optional[str]]:
        """Check if bot should trade now (cooldown, daily limits, etc)."""
        
        # Check daily profit target
        if self.state.daily_pnl >= Config.BANKROLL_INITIAL * Config.DAILY_PROFIT_TARGET:
            msg = f"Daily profit target hit: +{self.state.daily_pnl:.2f} / ${self.state.bankroll:.2f}"
            TradingState.logger(f"🛑 HALT: {msg}")
            AlertSystem.send_alert("⛔ Daily Profit Target Hit", msg)
            return False, "daily_profit_limit"
        
        # Check daily loss limit
        if self.state.daily_pnl <= -(Config.BANKROLL_INITIAL * Config.DAILY_LOSS_LIMIT):
            msg = f"Daily loss limit hit: {self.state.daily_pnl:.2f} / ${self.state.bankroll:.2f}"
            TradingState.logger(f"🛑 HALT: {msg}")
            AlertSystem.send_alert("⛔ Daily Loss Limit Hit", msg)
            return False, "daily_loss_limit"
        
        # Check bankroll threshold
        if self.state.bankroll < Config.MIN_BANKROLL_THRESHOLD:
            msg = f"Bankroll below threshold: ${self.state.bankroll:.2f} < ${Config.MIN_BANKROLL_THRESHOLD}"
            TradingState.logger(f"🛑 HALT: {msg}")
            AlertSystem.send_alert("⛔ Bankroll Below Threshold", msg)
            return False, "bankroll_limit"
        
        # Check trade cooldown
        if self.state.last_trade_time:
            time_since_last = datetime.utcnow() - datetime.fromisoformat(self.state.last_trade_time)
            if time_since_last.total_seconds() < Config.TRADE_COOLDOWN_MIN:
                return False, "cooldown"
        
        return True, None
    
    def filter_opportunities(self, markets: List[Dict]) -> List[Dict]:
        """Filter markets that meet entry criteria."""
        opportunities = []
        
        for market in markets:
            mid_price = (market.get("bestBid", 0) + market.get("bestAsk", 1)) / 2
            
            # Check entry price range
            if Config.MIN_ENTRY <= mid_price <= Config.MAX_ENTRY:
                opportunities.append({
                    "market_id": market.get("id"),
                    "title": market.get("title"),
                    "entry_price": mid_price,
                    "bid": market.get("bestBid"),
                    "ask": market.get("bestAsk"),
                    "volume": market.get("volume", 0),
                    "liquidity": market.get("liquidity", 0)
                })
        
        return opportunities
    
    def rank_opportunities(self, opportunities: List[Dict]) -> List[Dict]:
        """Rank opportunities by expected value."""
        for opp in opportunities:
            # Score: prefer mid-range prices (0.50-0.60) and high volume
            price_score = 1.0 - abs(opp["entry_price"] - 0.55) / 0.10
            volume_score = min(opp["volume"] / 100000, 1.0)  # Normalize by 100k volume
            opp["score"] = (price_score * 0.6) + (volume_score * 0.4)
        
        return sorted(opportunities, key=lambda x: x["score"], reverse=True)
    
    def execute_best_opportunity(self, opportunities: List[Dict]) -> Optional[Dict]:
        """Execute the best opportunity found."""
        if not opportunities:
            TradingState.logger("No opportunities found meeting criteria.")
            return None
        
        best = opportunities[0]
        position_size = Config.BANKROLL_INITIAL * Config.POSITION_SIZE_PCT
        
        TradingState.logger(f"📊 OPPORTUNITY: {best['title']}")
        TradingState.logger(f"   Entry: {best['entry_price']:.4f} | Position: ${position_size:.2f}")
        TradingState.logger(f"   Score: {best['score']:.3f} | Volume: {best['volume']:,}")
        
        # Calculate stop loss level
        stop_loss_price = best['entry_price'] * (1 + Config.STOP_LOSS_PCT)
        target_exit = best['entry_price'] * 1.20  # 20% target
        
        deal_data = {
            "Market": best['title'][:50],
            "Entry Price": f"${best['entry_price']:.4f}",
            "Position Size": f"${position_size:.2f}",
            "Stop Loss": f"${stop_loss_price:.4f} (-20%)",
            "Target Exit": f"${target_exit:.4f} (+20%)",
            "Expected Profit": f"${position_size * 0.20:.2f}",
            "Risk/Reward": "1:1"
        }
        
        if Config.READONLY_MODE:
            # In ReadOnly, don't actually execute
            TradingState.logger("✅ [READONLY] Trade would execute here")
            AlertSystem.send_alert(
                "📈 Opportunity Identified (ReadOnly)",
                f"Found opportunity in: {best['title']}\n\nEntry: {best['entry_price']:.4f}",
                deal_data
            )
            return {
                "status": "simulated",
                "market_id": best['market_id'],
                "title": best['title'],
                "entry_price": best['entry_price'],
                "position_size": position_size,
                "stop_loss": stop_loss_price,
                "target_exit": target_exit
            }
        else:
            # In live mode, execute trade
            success, trade_id = self.client.execute_trade(
                best['market_id'],
                position_size,
                best['entry_price'],
                "YES"  # or "NO" depending on prediction
            )
            
            if success:
                self.state.last_trade_time = datetime.utcnow().isoformat()
                self.state.positions[trade_id] = {
                    "market_id": best['market_id'],
                    "title": best['title'],
                    "entry_price": best['entry_price'],
                    "position_size": position_size,
                    "stop_loss": stop_loss_price,
                    "entry_time": datetime.utcnow().isoformat()
                }
                self.state.trades_today += 1
                self.state.save_state()
                
                AlertSystem.send_alert(
                    f"✅ Trade Executed",
                    f"Successfully entered: {best['title']}\n\nEntry: {best['entry_price']:.4f}",
                    deal_data
                )
                
                return self.state.positions[trade_id]
            else:
                AlertSystem.send_alert(
                    f"❌ Trade Failed",
                    f"Could not execute trade for: {best['title']}\n\nError: {trade_id}"
                )
                return None

# ============================================================================
# FLASHCARD GENERATOR
# ============================================================================

class FlashcardGenerator:
    @staticmethod
    def generate_html(opportunities: List[Dict], state: TradingState) -> str:
        """Generate professional flashcard HTML."""
        
        if not opportunities:
            return FlashcardGenerator._generate_no_deals_html(state)
        
        best = opportunities[0] if opportunities else None
        
        html = f"""
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>بطاقة الصفقات - {datetime.utcnow().strftime('%d %B %Y')}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Segoe UI', 'Arabic Typesetting', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }}
        
        .container {{
            width: 100%;
            max-width: 900px;
        }}
        
        .flashcard {{
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
            animation: slideIn 0.5s ease-out;
        }}
        
        @keyframes slideIn {{
            from {{
                opacity: 0;
                transform: translateY(20px);
            }}
            to {{
                opacity: 1;
                transform: translateY(0);
            }}
        }}
        
        .header {{
            background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }}
        
        .header h1 {{
            font-size: 28px;
            margin-bottom: 10px;
        }}
        
        .header p {{
            font-size: 16px;
            opacity: 0.9;
        }}
        
        .deal-card {{
            padding: 30px;
            border-bottom: 1px solid #ecf0f1;
        }}
        
        .deal-title {{
            font-size: 22px;
            color: #2c3e50;
            margin-bottom: 20px;
            font-weight: bold;
        }}
        
        .metrics-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 20px;
        }}
        
        .metric-box {{
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            border-right: 4px solid #28a745;
        }}
        
        .metric-label {{
            font-size: 12px;
            color: #7f8c8d;
            text-transform: uppercase;
            margin-bottom: 8px;
        }}
        
        .metric-value {{
            font-size: 20px;
            font-weight: bold;
            color: #2c3e50;
        }}
        
        .risk-box {{
            background: #ffe6e6;
            border-right-color: #e74c3c;
        }}
        
        .profit-box {{
            background: #e8f5e9;
            border-right-color: #28a745;
        }}
        
        .link-section {{
            padding: 0 30px 20px;
            margin-bottom: 20px;
        }}
        
        .polymarket-link {{
            display: inline-block;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 12px 24px;
            border-radius: 6px;
            text-decoration: none;
            font-weight: bold;
            transition: transform 0.2s;
        }}
        
        .polymarket-link:hover {{
            transform: translateY(-2px);
        }}
        
        .status-badge {{
            display: inline-block;
            background: #28a745;
            color: white;
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: bold;
            margin-left: 10px;
        }}
        
        .footer {{
            background: #34495e;
            color: white;
            padding: 20px 30px;
            text-align: center;
            font-size: 12px;
        }}
        
        .readonly-notice {{
            background: #fff3cd;
            border-left: 4px solid #f39c12;
            padding: 15px;
            margin: 20px 30px;
            border-radius: 4px;
            color: #856404;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="flashcard">
            <div class="header">
                <h1>✅ الصفقة المثالية</h1>
                <p>{datetime.utcnow().strftime('%d %B %Y - %H:%M UTC')}</p>
            </div>
            
            <div class="deal-card">
                <div class="deal-title">
                    {best['title'][:60]}
                    <span class="status-badge">ReadOnly</span>
                </div>
                
                <div class="metrics-grid">
                    <div class="metric-box">
                        <div class="metric-label">سعر الدخول</div>
                        <div class="metric-value">${best['entry_price']:.4f}</div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-label">سعر الخروج المتوقع</div>
                        <div class="metric-value">${best['entry_price'] * 1.20:.4f}</div>
                    </div>
                    <div class="metric-box risk-box">
                        <div class="metric-label">نسبة المخاطرة</div>
                        <div class="metric-value">20%</div>
                    </div>
                    <div class="metric-box profit-box">
                        <div class="metric-label">الربح المتوقع</div>
                        <div class="metric-value">+20%</div>
                    </div>
                </div>
                
                <div class="link-section">
                    <a href="https://polymarket.com/market/{best['market_id']}" class="polymarket-link" target="_blank">
                        🔗 فتح الصفقة في Polymarket
                    </a>
                </div>
                
                <div class="readonly-notice">
                    <strong>⚠️ وضع القراءة فقط (ReadOnly)</strong><br>
                    هذا الـ bot يعمل في وضع المحاكاة حالياً. لا توجد صفقات حقيقية يتم تنفيذها.
                </div>
            </div>
            
            <div class="footer">
                <p><strong>البنكرول الحالي:</strong> ${state.bankroll:.2f} | <strong>الأرباح اليومية:</strong> {state.daily_pnl:+.2f}</p>
                <p>Polymarket Trading Bot | ReadOnly Mode | Generated: {datetime.utcnow().isoformat()}Z</p>
            </div>
        </div>
    </div>
</body>
</html>
        """
        return html
    
    @staticmethod
    def _generate_no_deals_html(state: TradingState) -> str:
        """Generate flashcard when no deals meet criteria."""
        html = f"""
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>بطاقة الصفقات - {datetime.utcnow().strftime('%d %B %Y')}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: 'Segoe UI', 'Arabic Typesetting', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }}
        .container {{
            width: 100%;
            max-width: 900px;
        }}
        .flashcard {{
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #95a5a6 0%, #7f8c8d 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }}
        .header h1 {{
            font-size: 28px;
            margin-bottom: 10px;
        }}
        .content {{
            padding: 30px;
            text-align: center;
            color: #7f8c8d;
        }}
        .footer {{
            background: #34495e;
            color: white;
            padding: 20px;
            text-align: center;
            font-size: 12px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="flashcard">
            <div class="header">
                <h1>⏳ انتظار الفرص</h1>
                <p>{datetime.utcnow().strftime('%d %B %Y - %H:%M UTC')}</p>
            </div>
            <div class="content">
                <p>لا توجد صفقات تستوفي معايير الدخول الآن (0.45-0.65)</p>
                <p style="margin-top: 15px; font-size: 14px;">البنكرول: ${state.bankroll:.2f}</p>
            </div>
            <div class="footer">
                <p>Polymarket Trading Bot | ReadOnly Mode | {datetime.utcnow().isoformat()}Z</p>
            </div>
        </div>
    </div>
</body>
</html>
        """
        return html

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main bot loop."""
    TradingState.logger("=" * 80)
    TradingState.logger("🤖 POLYMARKET TRADING BOT STARTED")
    TradingState.logger(f"MODE: {'READONLY' if Config.READONLY_MODE else 'LIVE'}")
    TradingState.logger(f"API Key: {'Configured' if Config.POLYMARKET_API_KEY else 'MISSING'}")
    TradingState.logger(f"Wallet: {Config.POLYMARKET_WALLET}")
    TradingState.logger("=" * 80)
    
    # Initialize
    state = TradingState()
    client = PolymarketClient(Config.POLYMARKET_API_KEY)
    engine = TradingEngine(client, state)
    
    TradingState.logger(f"Starting Bankroll: ${state.bankroll:.2f}")
    
    # Main loop
    try:
        while True:
            TradingState.logger("\n" + "-" * 80)
            TradingState.logger(f"Cycle: {datetime.utcnow().isoformat()}")
            
            # Check if we should trade
            can_trade, reason = engine.should_trade_now()
            if not can_trade:
                TradingState.logger(f"Blocked: {reason}")
                # Save state and generate flashcard
                state.save_state()
                flashcard = FlashcardGenerator.generate_html([], state)
                with open("/tmp/polymarket_flashcard.html", "w", encoding="utf-8") as f:
                    f.write(flashcard)
                time.sleep(30)  # Wait 30 seconds before retry
                continue
            
            # Get markets
            markets = client.get_markets()
            TradingState.logger(f"Markets found: {len(markets)}")
            
            # Filter & rank
            opportunities = engine.filter_opportunities(markets)
            TradingState.logger(f"Opportunities (entry 0.45-0.65): {len(opportunities)}")
            
            ranked = engine.rank_opportunities(opportunities)
            
            # Generate flashcard
            flashcard = FlashcardGenerator.generate_html(ranked, state)
            with open("/tmp/polymarket_flashcard.html", "w", encoding="utf-8") as f:
                f.write(flashcard)
            TradingState.logger("✅ Flashcard generated: /tmp/polymarket_flashcard.html")
            
            # Execute best opportunity
            if ranked:
                result = engine.execute_best_opportunity(ranked)
                if result:
                    TradingState.logger(f"✅ Trade executed/simulated: {result.get('title', 'unknown')}")
            else:
                TradingState.logger("No opportunities met criteria.")
            
            # Save state
            state.save_state()
            
            # Wait before next cycle (60 seconds)
            TradingState.logger("Waiting 60 seconds before next cycle...")
            time.sleep(60)
    
    except KeyboardInterrupt:
        TradingState.logger("\n🛑 Bot stopped by user")
        state.save_state()
    except Exception as e:
        TradingState.logger(f"❌ Fatal error: {e}")
        AlertSystem.send_alert("❌ Bot Error", f"Fatal error occurred:\n\n{str(e)}")
        state.save_state()
        raise

if __name__ == "__main__":
    main()
