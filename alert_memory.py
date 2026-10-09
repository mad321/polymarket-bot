"""
Alert times that survive restarts
=================================
The monitor repeats a stop-loss / take-profit alert at most once per
ALERT_COOLDOWN, and the position-size alert once a day. Those times used to
live in memory only, so every restart (each deploy, each settings change in
Render) sent all of them again at once.

They are now kept in the pinned Telegram ledger: the ledger loop
(paper_trading.py) restores them when it loads the ledger and saves them with
it. The monitor waits briefly for that restore before its first check.
"""

import threading
import time

next_alert_at = {}   # polymarket_monitor: position -> earliest next alert (epoch seconds)
exposure_sent = {}   # exposure: event -> last position-size alert (epoch seconds)

_ready = threading.Event()
KEEP_FOR = 3 * 24 * 3600  # forget entries older than this


def ready():
    return _ready.is_set()


def wait(timeout):
    """Blocks until the saved times are restored, at most `timeout` seconds."""
    return _ready.wait(timeout)


def restore(saved):
    """Loads the times saved in the ledger (keeps any later one already set)."""
    for name, target in (("next_alert_at", next_alert_at), ("exposure_sent", exposure_sent)):
        for key, value in ((saved or {}).get(name) or {}).items():
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            if value > target.get(key, 0):
                target[key] = value
    _ready.set()


def snapshot(now=None):
    """The times to save, without stale entries."""
    now = now or time.time()
    return {
        "next_alert_at": {k: round(v) for k, v in dict(next_alert_at).items() if v > now - KEEP_FOR},
        "exposure_sent": {k: round(v) for k, v in dict(exposure_sent).items() if v > now - KEEP_FOR},
    }
