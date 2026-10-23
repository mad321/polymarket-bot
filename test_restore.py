#!/usr/bin/env python3
"""
Tests for the ledger restore of 2026-10-23 and the missing-ledger guard (no network).

    python -m unittest test_restore.py
"""

import os
import json
import unittest
from datetime import datetime, timezone
from unittest import mock

os.environ["ENABLE_MONITOR"] = "0"

import paper_store
import paper_trading as pt

NOW = datetime(2026, 10, 23, 21, 0, tzinfo=timezone.utc)


def saved():
    with open(pt.RESTORE_FILE, encoding="utf-8") as f:
        return json.load(f)


class Stop(BaseException):
    pass


class RestoreTests(unittest.TestCase):
    def empty(self):
        ledger = pt.new_ledger(NOW)
        del ledger["restored_id"]  # like the empty ledger started at 20:53
        ledger["match_test"] = {"open": [], "closed": [], "skipped": 0, "alerts_intro_v3": "x", "alerted": {"k": "t"}}
        ledger["strict_test"] = {"open": [], "closed": [], "skipped": {}, "digest_day": None, "last_digest_at": None}
        return ledger

    def test_the_saved_copy_has_the_lost_results(self):
        s = saved()
        self.assertEqual(len(s["strict_test"]["closed"]), 4)
        self.assertEqual(s["calibration"]["n"], 128)

    def test_merge_brings_back_trades_tests_review_and_accuracy(self):
        ledger = self.empty()
        pt.restore(ledger, saved())
        s = saved()
        self.assertEqual(len(ledger["strict_test"]["closed"]), 4)
        self.assertEqual(ledger["strict_test"]["skipped"], s["strict_test"]["skipped"])
        self.assertEqual(len(ledger["match_test"]["closed"]), len(s["match_test"]["closed"]))
        self.assertEqual(len(ledger["match_test"]["open"]), len(s["match_test"]["open"]))
        self.assertEqual(ledger["match_test"]["alerted"], {"k": "t"})  # kept
        self.assertEqual(ledger["calibration"]["n"], 128)
        self.assertEqual(ledger["started_at"], s["started_at"])
        self.assertTrue(all(e["key"] for e in ledger["level_alerts"]["open"] + ledger["level_alerts"]["closed"]))
        self.assertEqual(ledger["restored_id"], pt.RESTORE_ID)
        import stop_review
        stop_review.merge(ledger)  # entries need a key
        import strict_strategy
        self.assertIn("الربح 2 من 4", "\n".join(strict_strategy.summary_lines(ledger)))

    def test_trades_already_in_the_ledger_are_not_doubled(self):
        ledger = self.empty()
        s = saved()
        ledger["strict_test"]["closed"].append(s["strict_test"]["closed"][0])
        pt.restore(ledger, s)
        self.assertEqual(len(ledger["strict_test"]["closed"]), 4)

    def run_loop(self, store):
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

    def test_the_loop_restores_once_and_says_so(self):
        store = mock.Mock(describe=lambda: "mock")
        store.load.return_value = self.empty()
        send = self.run_loop(store)
        self.assertIn("♻️ استرجعت نتائج التداول على الورق", send.call_args.args[0])
        self.assertIn("4 صفقة للميزان الصارم", send.call_args.args[0])
        restored = store.save.call_args.args[0]
        self.assertEqual(restored["restored_id"], pt.RESTORE_ID)
        store.load.return_value = restored
        send = self.run_loop(store)
        send.assert_not_called()


class OriginalLedgerTests(unittest.TestCase):
    def test_the_original_ledger_is_not_merged_twice(self):
        ledger = pt.new_ledger(datetime(2026, 10, 19, 14, 55, 25, tzinfo=timezone.utc))
        del ledger["restored_id"]
        ledger["calibration"] = {"n": 128, "model": 7.1, "market": 6.9}
        store = mock.Mock(describe=lambda: "mock")
        store.load.return_value = ledger
        send = RestoreTests.run_loop(self, store)
        send.assert_not_called()
        saved_ledger = store.save.call_args.args[0]
        self.assertEqual((saved_ledger["calibration"]["n"], saved_ledger["restored_id"]), (128, pt.RESTORE_ID))


class CalibrationResetTests(unittest.TestCase):
    def test_accuracy_is_cleared_once_and_reported(self):
        ledger = pt.new_ledger(NOW)
        del ledger["calibration_reset"]
        ledger["calibration"] = {"n": 128, "model": 7.143, "market": 6.871}
        ledger["closed"] = [{"id": "btc"}]
        store = mock.Mock(describe=lambda: "mock")
        store.load.return_value = ledger
        send = RestoreTests.run_loop(self, store)
        self.assertIn("🧹 مُسح قياس دقة نموذج البيتكوين: كان على 128 سوق، النموذج 0.0558 والسوق 0.0537",
                      send.call_args.args[0])
        saved_ledger = store.save.call_args.args[0]
        self.assertEqual(saved_ledger["calibration"], {"n": 0, "model": 0.0, "market": 0.0})
        self.assertEqual(saved_ledger["closed"], [{"id": "btc"}])  # nothing else is touched
        store.load.return_value = saved_ledger
        RestoreTests.run_loop(self, store).assert_not_called()


class MissingLedgerTests(unittest.TestCase):
    def store_with_pinned(self, pinned):
        store = paper_store.TelegramStore()
        store._call = mock.Mock(side_effect=lambda method, *a, **k:
                                {"getChat": {"pinned_message": pinned} if pinned else {},
                                 "sendDocument": {"message_id": 99}}.get(method))
        return store

    def test_a_missing_ledger_is_replaced_by_one_that_is_not_pinned(self):
        store = self.store_with_pinned({"message_id": 5, "text": "hi", "from": {"is_bot": False}})
        self.assertIsNone(store.load())
        self.assertIn("ليست ملف السجل", store.missing)
        store.save({"a": 1})
        methods = [c.args[0] for c in store._call.call_args_list]
        self.assertIn("sendDocument", methods)
        self.assertNotIn("pinChatMessage", methods)  # the old ledger stays the newest pinned file

    def test_the_loop_warns_instead_of_announcing_a_new_start(self):
        store = mock.Mock(describe=lambda: "mock", missing="لا توجد رسالة مثبّتة")
        store.load.return_value = None
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
        self.assertIn("⚠️ لم أجد ملف سجل التداول", send.call_args_list[0].args[0])
        self.assertEqual(len(send.call_args_list), 1)  # a new ledger is not restored into

    def test_a_found_ledger_is_still_pinned_when_reposted(self):
        doc = {"message_id": 7, "from": {"is_bot": True}, "document": {"file_name": paper_store.FILE_NAME, "file_id": "f"}}
        store = self.store_with_pinned(doc)
        with mock.patch.object(store, "_call", side_effect=lambda m, *a, **k:
                               {"getChat": {"pinned_message": doc}, "getFile": {"file_path": "p"}}.get(m)), \
                mock.patch("paper_store.requests.get") as get:
            get.return_value.json.return_value = {"x": 1}
            self.assertEqual(store.load(), {"x": 1})
        self.assertTrue(store.may_pin)


if __name__ == "__main__":
    unittest.main()
