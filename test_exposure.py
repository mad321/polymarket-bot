#!/usr/bin/env python3
"""
Tests for the position size alert (no network: the Polygon RPC is mocked).

    python -m unittest test_exposure.py
"""

import os
import unittest
from unittest import mock

os.environ["ENABLE_MONITOR"] = "0"

import exposure
import polymarket_monitor as monitor

MAIN = "0x0c4526398bba16e31f23ca818d767cb00b02921c"
BOT = "0xb0b0000000000000000000000000000000000001"


def pos(event, shares, cents, title="Yemen Sep 21? — No", wallet=MAIN):
    return {"id": "1", "event": event, "shares": shares, "current_price": cents,
            "title": title, "name": title, "wallet": wallet}


YEMEN = [pos("yemen", 77.2, 45.5), pos("yemen", 55, 63.5, "Yemen Sep 23? — No"),
         pos("yemen", 60, 34.5), pos("yemen", 53.75, 27.0)]
ICELAND = pos("iceland", 41, 0.1, "Will Iceland win? — Yes")
T0 = 1_800_000_000  # a real epoch time


def rpc(balance_dollars):
    r = mock.Mock()
    r.raise_for_status.return_value = None
    r.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": hex(int(balance_dollars * 1e6))}
    return r


class ExposureTests(unittest.TestCase):
    def setUp(self):
        exposure.ACTIVE = True
        exposure._last_check = 0
        exposure._last_alert.clear()
        self.addCleanup(setattr, exposure, "ACTIVE", False)
        env = mock.patch.dict(os.environ, {"WALLET_ADDRESS": MAIN, "TRADING_WALLET": BOT})
        env.start()
        self.addCleanup(env.stop)

    def test_wallet_cash_reads_pusd_balance_of(self):
        with mock.patch("exposure.requests.post", return_value=rpc(469.326558)) as post:
            self.assertAlmostEqual(exposure.wallet_cash(MAIN), 469.326558)
        call = post.call_args.kwargs["json"]["params"][0]
        self.assertEqual(call["to"], exposure.PUSD)
        self.assertEqual(call["data"], "0x70a08231" + MAIN[2:].rjust(64, "0"))

    def test_markets_of_one_event_count_together(self):
        capital, items = exposure.over_limit(YEMEN + [ICELAND], 469.33, 5)
        self.assertAlmostEqual(capital, 469.33 + 105.26, places=1)
        self.assertEqual(len(items), 1)
        event, val, share, names = items[0]
        self.assertEqual((event, len(names)), ("yemen", 4))
        self.assertAlmostEqual(share, 18.3, places=1)

    def test_alert_text(self):
        capital, items = exposure.over_limit(YEMEN, 469.33, 5)
        text = exposure.format_alert(items, capital, 469.33, 5)
        self.assertIn("⚖️ تنبيه حجم الصفقة", text)
        self.assertIn("الحد: 5% = $28.73", text)
        self.assertIn("Yemen Sep 21? — No و3 أسواق أخرى في نفس الحدث: $105.26 (18.3%)", text)
        self.assertIn("البوت لا يبيع شيئاً", text)

    def test_checks_every_10_minutes_and_alerts_once_a_day(self):
        send = mock.Mock(return_value=True)
        with mock.patch("exposure.requests.post", return_value=rpc(234.66)) as post:  # per wallet
            self.assertTrue(exposure.check(YEMEN, send, now=T0))
            self.assertFalse(exposure.check(YEMEN, send, now=T0 + 300))           # too soon: no RPC
            self.assertFalse(exposure.check(YEMEN, send, now=T0 + 700))     # checked, already alerted
            self.assertTrue(exposure.check(YEMEN, send, now=T0 + 86400))    # a day later
        self.assertEqual(send.call_count, 2)
        self.assertEqual(post.call_count, 6)  # two wallets per check
        self.assertEqual(exposure.STATE["events_over_limit"], 1)

    def test_a_failed_send_is_retried_at_the_next_check(self):
        with mock.patch("exposure.requests.post", return_value=rpc(200)):
            self.assertFalse(exposure.check(YEMEN, mock.Mock(return_value=False), now=T0))
            self.assertTrue(exposure.check(YEMEN, mock.Mock(return_value=True), now=T0 + 700))

    def test_nothing_when_within_limit_off_or_inactive(self):
        send = mock.Mock(return_value=True)
        with mock.patch("exposure.requests.post", return_value=rpc(5000)) as post:
            self.assertFalse(exposure.check(YEMEN, send, now=T0))       # 2% of $5105
            with mock.patch.dict(os.environ, {"EXPOSURE_ALERT_PCT": "0"}):
                self.assertFalse(exposure.check(YEMEN, send, now=T0 + 99999))
            exposure.ACTIVE = False
            self.assertFalse(exposure.check(YEMEN, send, now=T0 + 999999))
        send.assert_not_called()
        self.assertEqual(post.call_count, 2)

    def test_rpc_failure_is_reported_not_raised(self):
        with mock.patch("exposure.requests.post", side_effect=ConnectionError("rpc down")):
            self.assertFalse(exposure.check(YEMEN, mock.Mock(), now=T0))
        self.assertIn("rpc down", exposure.STATE["error"])

    def test_monitor_runs_it_for_wallet_positions_only(self):
        with mock.patch("polymarket_monitor.exposure.check") as check, \
                mock.patch("polymarket_monitor.alerts.send_alert", return_value=True):
            with mock.patch("polymarket_monitor.load_positions", return_value=(YEMEN, "wallet", None)):
                monitor.check_once({})
            with mock.patch("polymarket_monitor.load_positions", return_value=(YEMEN, "config", None)):
                monitor.check_once({})
        self.assertEqual(check.call_count, 1)
        self.assertIs(check.call_args.args[0], YEMEN)


if __name__ == "__main__":
    unittest.main()
