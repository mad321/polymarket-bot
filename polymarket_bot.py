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
    DAILY_PROFIT_TARGET =
