"""
Live feed: prices and scores as they happen
===========================================
The ledger loop reads prices once a minute, so a stop could be seen up to 60
seconds after the price crossed it. This module keeps two of Polymarket's own
WebSocket feeds open instead:

  - the market channel (wss://ws-subscriptions-clob.polymarket.com/ws/market):
    every change of the best bid / ask of the watched "Will <team> win?" Yes
    tokens, within about a second;
  - the sports channel (wss://sports-api.polymarket.com/ws): live scores of
    every game, pushed as they change.

Two uses:
  1. Automatic stop-loss (auto_stop.py): when a covered position's price is
     20% or more below the buy price while its game is live, the sale is
     asked for at once instead of at the next minute.
  2. Measurement: for every goal in a watched game, the price of both teams
     is kept from 90 seconds before the score update to 90 seconds after. It
     answers how many seconds pass between a goal and the price move, and
     whether a −20% stop can still be caught before the jump. Records go to
     the ledger ("latency", the last MAX_RECORDS) and /api/paper.

Watched: every game of the chosen leagues that is under way (from the minute
loop's schedule), and your covered positions. Nothing here places orders by
itself; auto_stop.py does, under its own setting.

Settings:
  LIVE_FEED=0   turn it off (the minute loop keeps working as before)
"""

import os
import json
import time
import asyncio
import logging
import threading
from collections import deque
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

MARKET_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
SPORTS_WS = "wss://sports-api.polymarket.com/ws"
WINDOW = 90           # seconds of price kept before and after a goal
HISTORY = 240         # seconds of price history kept per token
MAX_RECORDS = 300
WIDE_SPREAD = 0.10    # same rule as match_strategy.mid_price

STATE = {"running": False, "market_connected": False, "sports_connected": False,
         "tokens": 0, "games": 0, "price_updates": 0, "score_updates": 0, "goals": 0,
         "stops_asked": 0, "last_error": None}

_lock = threading.Lock()
_watch = {}       # token -> {"game_id", "slug", "team", "pos": position or None, "live": bool}
_games = {}       # game id -> {"score", "live", "ended"}
_quotes = {}      # token -> {"bid", "ask", "last"}
_history = {}     # token -> deque of (epoch seconds, mid)
_pending = []     # goal records waiting for their 90 seconds after
_done = []        # finished goal records, until drained into the ledger
_started = False
_resubscribe = threading.Event()


def enabled():
    return (os.environ.get("LIVE_FEED") or "").strip() != "0"


def start():
    """Opens the feeds on a background thread (once per process)."""
    global _started
    with _lock:
        if _started or not enabled():
            return
        _started = True
    threading.Thread(target=lambda: asyncio.run(_main()), daemon=True, name="live-feed").start()


def watch(games, positions):
    """Called by the minute loop with the games under way and your covered
    positions in them (each tagged with _game and _side)."""
    tokens = {}
    for game in games:
        for side, s in game["sides"].items():
            tokens[s["token_id"]] = {"game_id": game.get("game_id"), "slug": game["slug"],
                                     "team": s["team"], "pos": None,
                                     "live": game.get("live", False) and not game.get("ended", False)}
    for pos in positions:
        game = pos["_game"]
        entry = tokens.setdefault(str(pos["id"]), {"game_id": game.get("game_id"), "slug": game["slug"],
                                                   "team": game["sides"][pos["_side"]]["team"],
                                                   "live": game.get("live", False)})
        entry["pos"] = pos
    with _lock:
        changed = set(tokens) != set(_watch)
        _watch.clear()
        _watch.update(tokens)
        STATE.update(tokens=len(tokens), games=len({t["slug"] for t in tokens.values()}))
    if changed:
        _resubscribe.set()


def drain():
    """Finished goal records, for the ledger (called under the ledger lock)."""
    with _lock:
        out, _done[:] = list(_done), []
    return out

# ─── PRICES ──────────────────────────────────────────────────────────────────

def mid(quote):
    bid, ask, last = quote.get("bid"), quote.get("ask"), quote.get("last")
    if bid is not None and ask is not None and 0 < ask - bid <= WIDE_SPREAD + 1e-9:
        return (bid + ask) / 2
    if bid is not None and ask is not None and ask == bid:
        return bid
    return last


def on_market(message, now=None):
    """Handles one market-channel message (a dict or a list of them)."""
    now = now or time.time()
    events = message if isinstance(message, list) else [message]
    touched = set()
    for e in events:
        kind = e.get("event_type")
        if kind == "book":
            bids = [float(b["price"]) for b in e.get("bids") or []]
            asks = [float(a["price"]) for a in e.get("asks") or []]
            _quote(e.get("asset_id"), bid=max(bids) if bids else None, ask=min(asks) if asks else None)
            touched.add(e.get("asset_id"))
        elif kind == "best_bid_ask":
            _quote(e.get("asset_id"), bid=_num(e.get("best_bid")), ask=_num(e.get("best_ask")))
            touched.add(e.get("asset_id"))
        elif kind == "price_change":
            for c in e.get("price_changes") or []:
                _quote(c.get("asset_id"), bid=_num(c.get("best_bid")), ask=_num(c.get("best_ask")))
                touched.add(c.get("asset_id"))
        elif kind == "last_trade_price":
            _quote(e.get("asset_id"), last=_num(e.get("price")))
            touched.add(e.get("asset_id"))
    for token in touched:
        _priced(token, now)


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _quote(token, **values):
    if token is None:
        return
    with _lock:
        q = _quotes.setdefault(token, {})
        q.update({k: v for k, v in values.items() if v is not None or k != "last"})


def _priced(token, now):
    with _lock:
        info = _watch.get(token)
        q = dict(_quotes.get(token) or {})
    m = mid(q)
    if info is None or m is None:
        return
    STATE["price_updates"] += 1
    with _lock:
        h = _history.setdefault(token, deque())
        if not h or h[-1][1] != m:
            h.append((now, m))
        while h and now - h[0][0] > HISTORY:
            h.popleft()
    _check_stop(info, m)


def _check_stop(info, m):
    import auto_stop
    import strict_strategy

    pos = info.get("pos")
    if pos is None or not _live(info):
        return
    buy = float(pos.get("buy_price") or 0) / 100
    if buy <= 0 or m > buy * (1 - strict_strategy.STOP) + 1e-9:
        return
    if auto_stop.applies(pos) and auto_stop.request(pos, m):
        STATE["stops_asked"] += 1
        logger.info(f"[LIVE] stop asked for {info['team']} at {m * 100:.1f}¢ (bought {buy * 100:.1f}¢)")


def _live(info):
    game = _games.get(info.get("game_id"))
    if game is not None:
        return game["live"] and not game["ended"]
    return info.get("live", False)

# ─── SCORES ──────────────────────────────────────────────────────────────────

def _goals(score):
    try:
        home, away = str(score).split("|")[0].split("-")
        return int(home), int(away)
    except (ValueError, AttributeError):
        return None


def on_sports(message, now=None):
    """Handles one sports-channel message: records a goal in a watched game."""
    now = now or time.time()
    events = message if isinstance(message, list) else [message]
    for e in events:
        game_id = e.get("gameId")
        if game_id is None:
            continue
        with _lock:
            old = _games.get(game_id)
            _games[game_id] = {"score": e.get("score"), "live": bool(e.get("live")), "ended": bool(e.get("ended"))}
            tokens = [t for t, info in _watch.items() if info.get("game_id") == game_id]
        STATE["score_updates"] += 1
        before, after = _goals(old["score"]) if old else None, _goals(e.get("score"))
        if not tokens or before is None or after is None or after == before or sum(after) <= sum(before):
            continue
        STATE["goals"] += 1
        with _lock:
            info = _watch[tokens[0]]
            _pending.append({"game": info["slug"], "game_id": game_id, "at": now, "prev": old["score"],
                             "score": e.get("score"),
                             "teams": {t: _watch[t]["team"] for t in tokens}, "tokens": tokens})


def finish(now=None):
    """Turns goals older than WINDOW into records with their price history."""
    now = now or time.time()
    with _lock:
        ready = [g for g in _pending if now - g["at"] >= WINDOW]
        for g in ready:
            _pending.remove(g)
            prices = {}
            for token in g["tokens"]:
                h = _history.get(token) or ()
                earlier = [(t, m) for t, m in h if t < g["at"] - WINDOW]  # the price at the window's start
                points = earlier[-1:] + [(t, m) for t, m in h if g["at"] - WINDOW <= t]
                prices[g["teams"][token]] = sorted({(round(t - g["at"], 1), round(m, 4)) for t, m in points
                                                    if t - g["at"] <= WINDOW})
            _done.append({"game": g["game"], "at": datetime.fromtimestamp(g["at"], timezone.utc)
                          .isoformat(timespec="seconds"), "prev": g["prev"], "score": g["score"],
                          "prices": {team: [list(p) for p in pts] for team, pts in prices.items()}})

# ─── CONNECTIONS ─────────────────────────────────────────────────────────────

async def _main():
    STATE["running"] = True
    await asyncio.gather(_market_loop(), _sports_loop(), _finisher())


async def _finisher():
    while True:
        await asyncio.sleep(5)
        finish()


async def _market_loop():
    import websockets
    while True:
        with _lock:
            tokens = sorted(_watch)
        _resubscribe.clear()
        if not tokens:
            await asyncio.sleep(5)
            continue
        try:
            async with websockets.connect(MARKET_WS, open_timeout=20, ping_interval=None) as ws:
                await ws.send(json.dumps({"type": "market", "assets_ids": tokens, "custom_feature_enabled": True}))
                STATE["market_connected"] = True
                last_ping = time.monotonic()
                while not _resubscribe.is_set():
                    if time.monotonic() - last_ping >= 10:
                        await ws.send("PING")
                        last_ping = time.monotonic()
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                    except asyncio.TimeoutError:
                        continue
                    if raw == "PONG":
                        continue
                    on_market(json.loads(raw))
        except Exception as e:
            STATE["last_error"] = f"market: {type(e).__name__}: {e}"[:300]
            logger.warning(f"[LIVE] {STATE['last_error']}")
            await asyncio.sleep(5)
        finally:
            STATE["market_connected"] = False


async def _sports_loop():
    import websockets
    while True:
        try:
            async with websockets.connect(SPORTS_WS, open_timeout=20) as ws:
                STATE["sports_connected"] = True
                async for raw in ws:
                    try:
                        on_sports(json.loads(raw))
                    except ValueError:
                        continue
        except Exception as e:
            STATE["last_error"] = f"sports: {type(e).__name__}: {e}"[:300]
            logger.warning(f"[LIVE] {STATE['last_error']}")
            await asyncio.sleep(5)
        finally:
            STATE["sports_connected"] = False


def status():
    return {**STATE, "enabled": enabled()}
