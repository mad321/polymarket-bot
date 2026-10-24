#!/usr/bin/env python3
"""
Tests for the live price and score feed (no network: messages are fed by hand).

    python -m unittest test_live.py
"""

import os
import unittest
from datetime import timedelta
from unittest import mock

os.environ["ENABLE_MONITOR"] = "0"
os.environ["JOURNAL"] = "0"  # the trade journal reads the network; its tests are in test_journal.py
os.environ["TRIAL"] = "0"  # the 70-match trial has its own tests (test_trial.py)

import live_feed as lf
import paper_trading as pt
from test_match import BOT, KICKOFF, game, my_pos

T0 = 1_800_000_000.0


def reset():
    for d in (lf._watch, lf._games, lf._quotes, lf._history):
        d.clear()
    lf._pending.clear()
    lf._done.clear()
    for k in ("price_updates", "score_updates", "goals", "stops_asked"):
        lf.STATE[k] = 0


def bba(token, bid, ask):
    return {"event_type": "best_bid_ask", "asset_id": token, "best_bid": str(bid), "best_ask": str(ask)}


class Base(unittest.TestCase):
    def setUp(self):
        reset()
        self.addCleanup(reset)
        g = game(live=True)
        g["game_id"] = 77
        self.game = g
        lf.watch([g], [{**my_pos(wallet=BOT, buy=60.0), "_game": g, "_side": "home"}])


class PriceTests(Base):
    def test_mid_follows_the_bot_rule(self):
        self.assertEqual(lf.mid({"bid": 0.50, "ask": 0.52}), 0.51)
        self.assertEqual(lf.mid({"bid": 0.30, "ask": 0.60, "last": 0.45}), 0.45)  # wide spread: last trade
        self.assertIsNone(lf.mid({}))

    def test_all_message_shapes_update_the_quote(self):
        lf.on_market({"event_type": "book", "asset_id": "yA", "bids": [{"price": "0.30", "size": "5"}],
                      "asks": [{"price": "0.32", "size": "5"}]}, now=T0)
        lf.on_market([{"event_type": "price_change", "price_changes": [
            {"asset_id": "yH", "best_bid": "0.61", "best_ask": "0.63"}]}], now=T0)
        self.assertEqual(round(lf.mid(lf._quotes["yA"]), 4), 0.31)
        self.assertEqual(round(lf.mid(lf._quotes["yH"]), 4), 0.62)
        self.assertEqual(lf.STATE["price_updates"], 2)

    def test_a_stop_is_asked_the_moment_the_price_crosses_it(self):
        with mock.patch("auto_stop.applies", return_value=True), \
                mock.patch("auto_stop.request", return_value=True) as request:
            lf.on_market(bba("yH", 0.49, 0.50), now=T0)      # 49.5c > 48c (60c × 0.8)
            request.assert_not_called()
            lf.on_market(bba("yH", 0.46, 0.48), now=T0 + 2)  # 47c
        request.assert_called_once()
        self.assertEqual(request.call_args.args[1], 0.47)
        self.assertEqual(lf.STATE["stops_asked"], 1)

    def test_no_stop_before_kickoff_or_after_the_final_whistle(self):
        lf._games[77] = {"score": "0-0", "live": False, "ended": False}
        with mock.patch("auto_stop.applies", return_value=True), mock.patch("auto_stop.request") as request:
            lf.on_market(bba("yH", 0.40, 0.42), now=T0)
        request.assert_not_called()

    def test_tokens_of_other_games_are_ignored(self):
        lf.on_market(bba("other", 0.40, 0.42), now=T0)
        self.assertEqual(lf.STATE["price_updates"], 0)


class GoalTests(Base):
    def test_a_goal_keeps_the_price_90_seconds_each_side(self):
        lf.on_sports({"gameId": 77, "score": "0-0", "live": True, "ended": False}, now=T0 - 200)
        lf.on_market(bba("yH", 0.61, 0.63), now=T0 - 120)   # before the window: the starting price
        lf.on_market(bba("yH", 0.59, 0.61), now=T0 - 20)
        lf.on_market(bba("yH", 0.44, 0.46), now=T0 - 4)     # the price moved before the score did
        lf.on_sports({"gameId": 77, "score": "0-1", "live": True, "ended": False}, now=T0)
        lf.on_market(bba("yH", 0.41, 0.43), now=T0 + 30)
        lf.finish(now=T0 + 60)
        self.assertEqual(lf.drain(), [])  # not 90 seconds yet
        lf.finish(now=T0 + 91)
        [record] = lf.drain()
        self.assertEqual((record["game"], record["prev"], record["score"]), (game()["slug"], "0-0", "0-1"))
        self.assertEqual(record["prices"]["Chelsea FC"], [[-120.0, 0.62], [-20.0, 0.6], [-4.0, 0.45], [30.0, 0.42]])
        self.assertEqual(lf.STATE["goals"], 1)

    def test_score_updates_without_a_new_goal_are_not_recorded(self):
        lf.on_sports({"gameId": 77, "score": "1-0", "live": True, "ended": False}, now=T0)
        lf.on_sports({"gameId": 77, "score": "1-0", "live": True, "ended": False}, now=T0 + 10)
        lf.on_sports({"gameId": 99, "score": "2-0", "live": True, "ended": False}, now=T0 + 10)  # not watched
        lf.finish(now=T0 + 200)
        self.assertEqual(lf.drain(), [])

    def test_watch_flags_a_resubscribe_only_when_tokens_change(self):
        lf._resubscribe.clear()
        lf.watch([self.game], [])
        self.assertFalse(lf._resubscribe.is_set())
        lf.watch([], [])
        self.assertTrue(lf._resubscribe.is_set())


class LedgerTests(unittest.TestCase):
    def test_scan_once_keeps_the_records_in_the_ledger(self):
        reset()
        self.addCleanup(reset)
        lf._done.append({"game": "g", "prices": {}})
        ledger = pt.new_ledger(KICKOFF)
        empty = {"games": {}, "books": {}, "payouts": {}, "candidates": [], "started": [], "error": None}
        with mock.patch.dict(os.environ, {"PAPER_TRADING": "0"}), \
                mock.patch("paper_trading.match_strategy.fetch", return_value=empty):
            pt.scan_once(ledger, KICKOFF + timedelta(minutes=1))
        self.assertEqual(ledger["latency"], [{"game": "g", "prices": {}}])


if __name__ == "__main__":
    unittest.main()
