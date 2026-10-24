"""
Bookmaker odds (The Odds API), to compare with Polymarket
=========================================================
Pinnacle is the sharpest public bookmaker: its odds, without its margin, are
a good estimate of each team's real chance. When a Polymarket Yes costs less
than that chance by more than the fees, the trade has an edge. The 70-match
trial (trial.py) records this edge for every match, so we can see whether it
predicts the results.

Odds are read only for the leagues with a match about to start, at most once
every CACHE_FOR per league, so the free plan (500 requests a month) suffices.

Settings:
  ODDS_API_KEY   key from the-odds-api.com (free plan); without it, no odds
"""

import os
import re
import time
import logging
import unicodedata
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

API = "https://api.the-odds-api.com/v4/sports/{sport}/odds"
SPORTS = {"epl": "soccer_epl", "lal": "soccer_spain_la_liga", "bun": "soccer_germany_bundesliga",
          "sea": "soccer_italy_serie_a", "ucl": "soccer_uefa_champs_league",
          "unl": "soccer_uefa_nations_league", "spl": "soccer_saudi_arabia_pro_league"}
CACHE_FOR = 1200  # seconds
STOP_WORDS = {"fc", "cf", "ac", "ssc", "sc", "afc", "club", "de", "calcio", "the", "cd", "ud", "rc", "rcd",
              "sv", "vfb", "vfl", "tsg", "bc", "as", "us", "ss", "saudi", "1", "04", "09", "1907", "1899",
              "balompie", "futbol", "sad", "al", "fk", "if", "real"}

STATE = {"enabled": False, "requests_remaining": None, "last_error": None, "matched": 0, "unmatched": 0}
_cache = {}  # league -> (fetched at, events)


def enabled():
    return bool((os.environ.get("ODDS_API_KEY") or "").strip())


ALIASES = {"internazionale": "inter", "milano": "milan", "munchen": "munich", "muenchen": "munich",
           "koln": "cologne", "koeln": "cologne",
           "psg": "paris", "germain": "paris"}


def _words(name):
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    return {ALIASES.get(w, w) for w in re.split(r"[^a-z0-9]+", text) if w and w not in STOP_WORDS}


def same_team(a, b):
    """Loose name match: 'Club Atlético de Madrid' ~ 'Atletico Madrid'."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return False
    return wa <= wb or wb <= wa  # every word of the shorter name is in the other


def no_vig(outcomes):
    """Decimal odds of the three outcomes -> probabilities without the margin."""
    inv = {o["name"]: 1 / float(o["price"]) for o in outcomes if float(o.get("price") or 0) > 1}
    total = sum(inv.values())
    return {k: v / total for k, v in inv.items()} if len(inv) == 3 and total > 0 else None


def probabilities(event):
    """Pinnacle's no-margin chances, else the average of the other bookmakers'."""
    books = {}
    for b in event.get("bookmakers") or []:
        for m in b.get("markets") or []:
            if m.get("key") == "h2h":
                p = no_vig(m.get("outcomes") or [])
                if p:
                    books[b["key"]] = p
    if "pinnacle" in books:
        return books["pinnacle"], "pinnacle"
    if not books:
        return None, None
    names = set.intersection(*(set(p) for p in books.values()))
    return {n: sum(p[n] for p in books.values()) / len(books) for n in names}, f"{len(books)} books"


def fetch_league(league, now=None):
    now = now or time.time()
    sport = SPORTS.get(league)
    if not sport or not enabled():
        return []
    at, events = _cache.get(league, (0, []))
    if now - at < CACHE_FOR:
        return events
    r = requests.get(API.format(sport=sport), params={"apiKey": os.environ["ODDS_API_KEY"].strip(),
                                                      "regions": "eu", "markets": "h2h", "oddsFormat": "decimal"},
                     timeout=20)
    STATE["requests_remaining"] = r.headers.get("x-requests-remaining")
    r.raise_for_status()
    events = r.json()
    _cache[league] = (now, events)
    return events


def lookup(game, now=None):
    """{side: chance} for a Polymarket game, with the source, or (None, None)."""
    STATE["enabled"] = enabled()
    try:
        events = fetch_league(game["league"], now)
    except Exception as e:
        STATE["last_error"] = f"{type(e).__name__}: {str(e).replace(os.environ.get('ODDS_API_KEY', '') or '~', '***')}"[:200]
        logger.warning(f"[ODDS] {STATE['last_error']}")
        return None, None
    for e in events:
        try:
            start = datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if abs((start - game["start"]).total_seconds()) > 3 * 3600:
            continue
        home, away = game["sides"]["home"]["team"], game["sides"]["away"]["team"]
        if not (same_team(home, e.get("home_team")) and same_team(away, e.get("away_team"))):
            continue
        probs, source = probabilities(e)
        if not probs:
            break
        out = {}
        for side, name in (("home", e["home_team"]), ("away", e["away_team"])):
            if name in probs:
                out[side] = round(probs[name], 4)
        if len(out) == 2:
            STATE["matched"] += 1
            return out, source
    STATE["unmatched"] += 1
    return None, None
