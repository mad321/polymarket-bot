#!/usr/bin/env python3
"""
Tests for alert times that survive restarts (no network).

    python -m unittest test_alert_memory.py
"""

import os
import time
import unittest
from datetime import datetime, timezone
from unittest import mock

os.environ["ENABLE_MONITOR"] = "0"

import alert_memory
import exposure
import paper_trading as pt
import polymarket_monitor as monitor


class AlertMemoryTests(unittest.TestCase):
    def setUp(self):
        alert_memory.next_alert_at.clear()
        alert_memory.exposure_sent.clear()
        alert_memory._ready.clear()
        self.addCleanup(alert_memory.next_alert_at.clear)
        self.addCleanup(alert_memory.exposure_sent.clear)
        self.addCleanup(alert_memory._ready.clear)

    def test_restore_keeps_the_later_time_and_marks_ready(self):
        alert_memory.next_alert_at["a"] = 200
        alert_memory.restore({"next_alert_at": {"a": 100, "b": 300}, "exposure_sent": {"yemen": "50"}})
        self.assertEqual(alert_memory.next_alert_at, {"a": 200, "b": 300.0})
        self.assertEqual(alert_memory.exposure_sent, {"yemen": 50.0})
        self.assertTrue(alert_memory.ready())
        alert_memory.restore(None)  # an old ledger without saved times

    def test_snapshot_drops_stale_entries(self):
        now = 10_000_000
        alert_memory.next_alert_at.update(old=now - 4 * 24 * 3600, fresh=now + 3600)
        alert_memory.exposure_sent.update(yemen=now - 100)
        self.assertEqual(alert_memory.snapshot(now),
                         {"next_alert_at": {"fresh": now + 3600}, "exposure_sent": {"yemen": now - 100}})

    def test_exposure_uses_the_kept_times(self):
        self.assertIs(exposure._last_alert, alert_memory.exposure_sent)

    def test_a_restart_does_not_repeat_an_alert_within_the_cooldown(self):
        pos = dict(id="1", wallet="0xa", name="Yemen Sep 24", shares=60, current_price=30.0,
                   stop_loss=32.2, take_profit=69.0, pnl_usd=-9.6, url="u")
        with mock.patch.object(monitor, "load_positions", return_value=([pos], "wallet", None)), \
                mock.patch.object(monitor.alerts, "send_alert", return_value=True) as send, \
                mock.patch.object(monitor.stop_review, "record"), mock.patch.object(monitor.exposure, "check"):
            monitor.check_once(alert_memory.next_alert_at)
            saved = alert_memory.snapshot()
            # Restart: memory is empty again until the ledger restores it.
            alert_memory.next_alert_at.clear()
            alert_memory.restore(saved)
            monitor.check_once(alert_memory.next_alert_at)
        self.assertEqual(send.call_count, 1)

    def test_scan_saves_the_times_only_after_they_were_restored(self):
        ledger = pt.new_ledger(datetime(2026, 10, 9, tzinfo=timezone.utc))
        ledger["alert_memory"] = {"next_alert_at": {"x": time.time() + 3600}, "exposure_sent": {}}
        alert_memory.next_alert_at["y"] = time.time() + 60
        env = {"PAPER_TRADING": "0", "MATCH_TEST": "0", "MATCH_ALERTS": "0"}
        with mock.patch.dict(os.environ, env):
            pt.scan_once(ledger)
            self.assertIn("x", ledger["alert_memory"]["next_alert_at"])  # not ready: left as saved
            alert_memory.restore(ledger["alert_memory"])
            pt.scan_once(ledger)
        self.assertEqual(set(ledger["alert_memory"]["next_alert_at"]), {"x", "y"})


if __name__ == "__main__":
    unittest.main()
