#!/usr/bin/env python3
"""
Tests for the "strict balance" 3.0 paper test and the paper-trade wipe (no network).

    python -m unittest test_strict.py
"""

import os
import json
import unittest
from datetime import timedelta
from unittest import mock

os.environ["ENABLE_MONITOR"] = "0"

import match_strategy as ms
import paper_store
import paper_trading as pt
import strict_strategy as st
from test_match import KICKOFF, TZ, book, event, game

SLUG = "epl-che-bou-2026-10-10"


class EliteTests(unittest.TestCase):
    def test_names_match_as_whole_words_without_accents(self):
        self.assertTrue(st.is_elite("Chelsea FC"))
        self.assertTrue(st.is_elite("FC Bayern München"))
        self.assertTrue(st.is_elite("Club Atlético de Madrid"))
        self.assertTrue(st.is_elite("Inter Milan"))
        self.assertTrue(st.is_elite("Atlético Madrid"))
        self.assertTrue(st.is_elite("Al-Hilal Saudi FC"))
        self.assertFalse(st.is_elite("AFC Bournemouth"))
        self.assertFalse(st.is_elite("Internacional"))  # "Inter" is a whole word only

    def test_the_list_can_be_replaced(self):
        with mock.patch.dict(os.environ, {"STRICT_TEAMS": "AFC Bournemouth, Brentford"}):
            self.assertTrue(st.is_elite("AFC Bournemouth"))
            self.assertFalse(st.is_elite("Chelsea FC"))


class StrictTests(unittest.TestCase):
    def setUp(self):
        self.ledger = pt.new_ledger(KICKOFF - timedelta(days=1))
        self.sec = st.section(self.ledger)
        patcher = mock.patch.dict(os.environ, {"STRICT_TEST": "1", "STRICT_STAKE": "25",
                                               "MATCH_TEST": "0", "MATCH_ALERTS": "0"})
        patcher.start()
        self.addCleanup(patcher.stop)
        ms._schedule = {SLUG: game()}
        self.addCleanup(setattr, ms, "_schedule", {})
        ms._settle_checked.clear()

    def enter(self, home_ask=0.62, away_ask=0.15, g=None, minutes=10):
        data = {"games": {SLUG: g or game()}, "candidates": [SLUG], "started": [], "payouts": {}, "error": None,
                "books": {"yH": book(home_ask - 0.01, home_ask), "yA": book(away_ask - 0.01, away_ask)}}
        ms.apply(self.ledger, data, KICKOFF - timedelta(minutes=minutes), TZ)
        return self.sec["open"][0] if self.sec["open"] else None

    def tick(self, minutes, bid, ask, **state):
        data = {"games": {SLUG: game(live=True, **state)}, "candidates": [], "started": [], "payouts": {},
                "error": None, "books": {"yH": book(bid, ask)}}
        return ms.apply(self.ledger, data, KICKOFF + timedelta(minutes=minutes), TZ)

    def settle(self, payout, minutes=200):
        self.sec["open"][0]["ended"] = True
        data = {"games": {}, "candidates": [], "started": [], "error": None, "books": {},
                "payouts": {self.sec["open"][0]["id"]: payout}}
        ms.apply(self.ledger, data, KICKOFF + timedelta(minutes=minutes), TZ)
        return self.sec["closed"][-1]

    def test_buys_25_dollars_of_an_elite_team_priced_55_to_72(self):
        t = self.enter()
        self.assertEqual((t["team"], t["entry_price"], t["shares"]), ("Chelsea FC", 0.62, 40.32))
        self.assertEqual((t["target"], t["stop"]), (0.744, 0.496))
        self.assertEqual(self.ledger["match_test"]["open"], [])  # the hybrid test is off here

    def test_an_entry_is_sent_as_a_buy_signal_once(self):
        data = {"games": {SLUG: game()}, "candidates": [SLUG], "started": [], "payouts": {}, "error": None,
                "books": {"yH": book(0.61, 0.62), "yA": book(0.14, 0.15)}}
        msgs = ms.apply(self.ledger, data, KICKOFF - timedelta(minutes=12), TZ)
        self.assertEqual(len(msgs), 1)
        text = msgs[0]
        self.assertIn("🟢 فرصة شراء: الميزان الصارم 3.0", text)
        self.assertIn("Chelsea FC vs. AFC Bournemouth: تبدأ بعد 12 دقيقة", text)
        self.assertIn("السعر الآن حوالي 62.0¢", text)
        self.assertIn("بـ $25، أي حوالي 40.32 سهم", text)
        self.assertIn("إن نزل السعر إلى 49.6¢ (−20%)", text)
        self.assertIn("عند 74.4¢ (+20%)", text)
        self.assertIn("0 صفقة محسومة، والحكم بعد 30", text)
        self.assertIn("https://polymarket.com/event/" + SLUG, text)
        self.assertEqual(ms.apply(self.ledger, data, KICKOFF - timedelta(minutes=11), TZ), [])

    def test_no_signal_when_signals_are_off_or_nothing_is_bought(self):
        data = {"games": {SLUG: game()}, "candidates": [SLUG], "started": [], "payouts": {}, "error": None,
                "books": {"yH": book(0.75, 0.76), "yA": book(0.14, 0.15)}}
        self.assertEqual(ms.apply(self.ledger, data, KICKOFF - timedelta(minutes=12), TZ), [])  # 76c: out of range
        data["books"]["yH"] = book(0.61, 0.62)
        with mock.patch.dict(os.environ, {"BUY_SIGNALS": "0"}):
            self.assertEqual(ms.apply(self.ledger, data, KICKOFF - timedelta(minutes=11), TZ), [])
        self.assertEqual(len(self.sec["open"]), 1)  # the paper test still bought

    def test_no_entry_above_72_cents_and_the_miss_is_counted_at_kickoff(self):
        self.assertIsNone(self.enter(home_ask=0.74))
        self.assertIsNone(self.enter(home_ask=0.62 + 0.11, minutes=5))
        data = {"games": {}, "candidates": [], "started": [SLUG], "payouts": {}, "error": None, "books": {}}
        ms.apply(self.ledger, data, KICKOFF + timedelta(minutes=1), TZ)
        ms.apply(self.ledger, data, KICKOFF + timedelta(minutes=2), TZ)
        self.assertEqual(self.sec["skipped"], {"price": 1})

    def test_a_late_price_in_range_still_enters(self):
        self.assertIsNone(self.enter(home_ask=0.76, minutes=14))
        self.assertIsNotNone(self.enter(home_ask=0.70, minutes=3))

    def test_no_entry_under_15000_volume(self):
        e = event()
        for m in e["markets"]:
            m["volume"] = 4000  # 12,000 in all
        self.assertIsNone(self.enter(g=ms.parse_game(e, "epl")))
        self.assertEqual(self.sec["skipped"], {"volume": 1})

    def test_no_entry_without_an_elite_team(self):
        with mock.patch.dict(os.environ, {"STRICT_TEAMS": "Arsenal"}):
            self.assertIsNone(self.enter())
            data = {"games": {}, "candidates": [], "started": [SLUG], "payouts": {}, "error": None, "books": {}}
            ms.apply(self.ledger, data, KICKOFF + timedelta(minutes=1), TZ)
        self.assertEqual(self.sec["skipped"], {})  # not counted: the game was never a candidate

    def test_take_profit_fills_at_the_limit_without_a_fee(self):
        self.enter()
        self.tick(20, 0.70, 0.72, score="0-0", elapsed="20", period="1H")
        self.assertNotIn("exit", self.sec["open"][0])
        self.tick(80, 0.75, 0.77, score="0-0", elapsed="66", period="2H")  # no time stop at 65
        ex = self.sec["open"][0]["exit"]
        self.assertEqual((ex["rule"], ex["price"], ex["proceeds"]), ("target", 0.744, round(40.32 * 0.744, 4)))
        t = self.settle(0.0)  # Chelsea lost: the take-profit saved the trade
        self.assertAlmostEqual(t["pnl"], 40.32 * 0.744 - t["cost"] - t["fee"], places=3)
        self.assertLess(t["hold_pnl"], 0)

    def test_stop_loss_at_20_percent_down_the_bids(self):
        self.enter()
        self.tick(30, 0.49, 0.51, score="0-1", elapsed="30", period="1H")  # mid 0.50 > 0.496
        self.assertNotIn("exit", self.sec["open"][0])
        self.tick(31, 0.48, 0.50, score="0-1", elapsed="31", period="1H")  # mid 0.49
        ex = self.sec["open"][0]["exit"]
        self.assertEqual((ex["rule"], ex["sold_shares"]), ("stop", 40.32))
        self.assertAlmostEqual(ex["proceeds"], 40.32 * 0.48 - 40.32 * 0.05 * 0.48 * 0.52, places=3)
        self.tick(40, 0.80, 0.82, score="1-1", elapsed="40", period="1H")
        self.assertEqual(self.sec["open"][0]["exit"]["rule"], "stop")  # one exit only

    def test_stop_without_buyers_keeps_trying(self):
        self.enter()
        data = {"games": {SLUG: game(live=True, score="0-1", elapsed="30", period="1H")}, "candidates": [],
                "started": [], "payouts": {}, "error": None,
                "books": {"yH": {**book(None, 0.60), "last_trade_price": "0.40"}}}  # nobody bids
        ms.apply(self.ledger, data, KICKOFF + timedelta(minutes=30), TZ)
        self.assertTrue(self.sec["open"][0]["stop_pending"])
        self.tick(31, 0.55, 0.60, score="0-1", elapsed="31", period="1H")
        self.assertEqual(self.sec["open"][0]["exit"]["rule"], "stop")

    def test_reports_wins_against_the_66_percent_goal(self):
        self.enter()
        self.settle(1.0)
        lines = "\n".join(st.summary_lines(self.ledger))
        self.assertIn("الربح 1 من 1 (‎100%، والمطلوب 66%)", lines)
        self.assertIn("حتى النهاية 1", lines)
        self.assertIn("الحكم يحتاج 30 على الأقل", lines)
        msgs = ms.apply(self.ledger, {"games": {}, "candidates": [], "started": [], "payouts": {}, "error": None,
                                      "books": {}}, KICKOFF + timedelta(days=1), TZ)
        self.assertIn("🛡️ الميزان الصارم 3.0 (بدون مال حقيقي): 1 صفقة حُسمت", msgs[0])

    def test_both_tests_buy_the_same_game(self):
        with mock.patch.dict(os.environ, {"MATCH_TEST": "1", "MATCH_STAKE": "10"}):
            self.enter()
            self.assertEqual(len(self.ledger["match_test"]["open"]), 1)
            self.assertEqual(len(self.sec["open"]), 1)
            plan = ms.plan(self.ledger, KICKOFF - timedelta(minutes=9))
            self.assertEqual(plan["entered"], {SLUG})
            self.enter(minutes=8)  # a second round adds nothing
            self.assertEqual((len(self.ledger["match_test"]["open"]), len(self.sec["open"])), (1, 1))

    def test_plan_keeps_a_game_a_candidate_until_both_tests_decided(self):
        with mock.patch.dict(os.environ, {"MATCH_TEST": "1"}):
            ms.section(self.ledger)["closed"].append({"slug": SLUG})
            self.assertEqual(ms.plan(self.ledger, KICKOFF)["entered"], set())
        self.assertEqual(ms.plan(self.ledger, KICKOFF)["entered"], set())
        self.enter()
        plan = ms.plan(self.ledger, KICKOFF)
        self.assertEqual((plan["entered"], plan["live"]), ({SLUG}, {SLUG: "epl"}))

    def test_scan_once_announces_the_test_once(self):
        empty = {"games": {}, "books": {}, "payouts": {}, "candidates": [], "started": [], "error": None}
        ledger = pt.new_ledger(KICKOFF)
        with mock.patch.dict(os.environ, {"PAPER_TRADING": "0"}), \
                mock.patch("paper_trading.match_strategy.fetch", return_value=empty):
            msgs, _, _ = pt.scan_once(ledger, KICKOFF)
            msgs2, _, _ = pt.scan_once(ledger, KICKOFF + timedelta(minutes=1))
        self.assertIn("🛡️ بدأ اختبار \"الميزان الصارم 3.0\"", msgs[0])
        self.assertIn("Manchester City", msgs[0])
        self.assertEqual(msgs2, [])


class WipeTests(unittest.TestCase):
    def old_ledger(self):
        ledger = pt.new_ledger(KICKOFF - timedelta(days=10))
        del ledger["reset_id"]
        ledger["closed"] = [{"id": "btc"}]
        ledger["open"] = [{"id": "btc2"}]
        ledger["calibration"] = {"n": 73, "model": 4.1, "market": 3.9}
        ledger["level_alerts"]["closed"] = [{"id": "review"}]
        ledger["match_test"] = {"open": [{"id": "m"}], "closed": [{"id": "m2"}], "skipped": 49,
                                "alerted": {"k": "t"}, "alerts_intro": "x", "digest_day": "d"}
        return ledger

    def run_loop(self, store):
        class Stop(BaseException):
            pass
        pt._ledger = None
        self.addCleanup(setattr, pt, "_ledger", None)
        import stop_review
        self.addCleanup(setattr, stop_review, "ACTIVE", False)
        with mock.patch("paper_trading.paper_store.default_store", return_value=store), \
                mock.patch("paper_trading.time.sleep", side_effect=Stop), \
                mock.patch("paper_trading.scan_once", return_value=([], False, None)), \
                mock.patch("paper_trading.alerts.send_alert") as send:
            with self.assertRaises(Stop):
                pt.run_forever()
        return send

    def test_wipes_paper_trades_once_after_archiving_them(self):
        old = self.old_ledger()
        store = mock.Mock(describe=lambda: "mock")
        store.load.return_value = old
        archived = []
        store.archive.side_effect = lambda ledger, name: archived.extend([json.loads(json.dumps(ledger)), name])
        send = self.run_loop(store)
        self.assertTrue(archived[1].startswith("paper_trades_before_"))
        self.assertEqual(archived[0]["closed"], [{"id": "btc"}])  # archived before the wipe
        saved = store.save.call_args.args[0]
        self.assertEqual((saved["open"], saved["closed"], saved["reset_id"]), ([], [], pt.RESET_ID))
        self.assertEqual(saved["calibration"]["n"], 73)
        self.assertEqual(saved["level_alerts"]["closed"], [{"id": "review"}])
        self.assertEqual(saved["match_test"]["open"] + saved["match_test"]["closed"], [])
        self.assertEqual((saved["match_test"]["alerted"], saved["match_test"]["skipped"]), ({"k": "t"}, 0))
        self.assertIn("🧹 مُسحت الصفقات الورقية", send.call_args.args[0])

    def test_nothing_is_wiped_when_the_archive_fails(self):
        store = mock.Mock(describe=lambda: "mock")
        store.load.return_value = self.old_ledger()
        store.archive.side_effect = paper_store.StoreError("sendDocument: HTTP 502")
        send = self.run_loop(store)
        store.save.assert_not_called()
        send.assert_not_called()
        self.assertIsNone(pt._ledger)  # tried again next round
        self.assertIn("502", pt.STATE["last_error"])

    def test_a_wiped_or_new_ledger_is_left_alone(self):
        store = mock.Mock(describe=lambda: "mock")
        store.load.return_value = pt.new_ledger(KICKOFF)
        self.run_loop(store)
        store.archive.assert_not_called()

    def test_file_store_archive(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            store = paper_store.FileStore(os.path.join(d, "ledger.json"))
            store.archive({"a": 1}, "old.json")
            self.assertTrue(os.path.exists(os.path.join(d, "old.json")))

    def test_telegram_archive_is_a_separate_unpinned_document(self):
        store = paper_store.TelegramStore()
        with mock.patch.object(store, "_call") as call:
            store.archive({"a": 1}, "old.json")
        method, data, files = call.call_args.args
        self.assertEqual((method, files["document"][0]), ("sendDocument", "old.json"))
        self.assertIsNone(store.message_id)  # the pinned ledger message is untouched


if __name__ == "__main__":
    unittest.main()
