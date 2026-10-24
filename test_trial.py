#!/usr/bin/env python3
"""
Tests for the 70-match trial and the bookmaker odds (no network).

    python -m unittest test_trial.py
"""

import os
import unittest
from datetime import timedelta
from unittest import mock

os.environ["ENABLE_MONITOR"] = "0"
os.environ["JOURNAL"] = "0"

import match_strategy as ms
import odds
import paper_trading as pt
import strict_strategy as st
import trial
from test_match import KICKOFF, TZ, book, game

SLUG = "epl-che-bou-2026-10-10"


class OddsTests(unittest.TestCase):
    def test_team_names_match_loosely(self):
        self.assertTrue(odds.same_team("Club Atlético de Madrid", "Atletico Madrid"))
        self.assertTrue(odds.same_team("Chelsea FC", "Chelsea"))
        self.assertTrue(odds.same_team("Al Hilal SFC", "Al Hilal"))
        self.assertTrue(odds.same_team("FC Internazionale Milano", "Inter Milan"))
        self.assertFalse(odds.same_team("Real Madrid CF", "Real Sociedad"))
        self.assertFalse(odds.same_team("Manchester City FC", "Manchester United"))

    def test_no_vig_and_pinnacle_first(self):
        p = odds.no_vig([{"name": "A", "price": 1.6}, {"name": "B", "price": 5.5}, {"name": "Draw", "price": 4.0}])
        self.assertAlmostEqual(sum(p.values()), 1.0)
        self.assertAlmostEqual(p["A"], (1 / 1.6) / (1 / 1.6 + 1 / 5.5 + 1 / 4.0), places=6)
        event = {"bookmakers": [
            {"key": "unibet", "markets": [{"key": "h2h", "outcomes": [
                {"name": "A", "price": 1.5}, {"name": "B", "price": 6}, {"name": "Draw", "price": 4}]}]},
            {"key": "pinnacle", "markets": [{"key": "h2h", "outcomes": [
                {"name": "A", "price": 1.6}, {"name": "B", "price": 5.5}, {"name": "Draw", "price": 4}]}]}]}
        probs, source = odds.probabilities(event)
        self.assertEqual(source, "pinnacle")
        self.assertAlmostEqual(probs["A"], p["A"])

    def test_lookup_finds_the_game(self):
        g = game()
        event = {"commence_time": "2026-10-10T14:00:00Z", "home_team": "Chelsea", "away_team": "Bournemouth",
                 "bookmakers": [{"key": "pinnacle", "markets": [{"key": "h2h", "outcomes": [
                     {"name": "Chelsea", "price": 1.55}, {"name": "Bournemouth", "price": 6.0},
                     {"name": "Draw", "price": 4.2}]}]}]}
        with mock.patch.dict(os.environ, {"ODDS_API_KEY": "k"}), mock.patch("odds.fetch_league", return_value=[event]):
            chances, source = odds.lookup(g)
        self.assertEqual(source, "pinnacle")
        self.assertGreater(chances["home"], 0.6)
        with mock.patch.dict(os.environ, {"ODDS_API_KEY": "k"}), mock.patch("odds.fetch_league", return_value=[]):
            self.assertEqual(odds.lookup(g), (None, None))

    def test_errors_never_show_the_key(self):
        with mock.patch.dict(os.environ, {"ODDS_API_KEY": "s3cretkey"}), \
                mock.patch("odds.fetch_league", side_effect=RuntimeError("bad s3cretkey")):
            self.assertEqual(odds.lookup(game()), (None, None))
        self.assertNotIn("s3cretkey", odds.STATE["last_error"])


class TrialTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"TRIAL": "1", "STRICT_TEST": "0", "MATCH_TEST": "0",
                                               "MATCH_ALERTS": "0"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ledger = pt.new_ledger(KICKOFF - timedelta(days=1))
        self.sec = trial.section(self.ledger)
        ms._schedule = {SLUG: game()}
        self.addCleanup(setattr, ms, "_schedule", {})
        ms._settle_checked.clear()
        trial.STATE["done"] = False

    def enter(self, ask=0.62, chance=None, minutes=10):
        data = {"games": {SLUG: game()}, "candidates": [SLUG], "started": [], "payouts": {}, "error": None,
                "books": {"yH": book(ask - 0.01, ask), "yA": book(0.14, 0.15)},
                "odds": {SLUG: ({"home": chance, "away": 0.1}, "pinnacle") if chance else (None, None)}}
        return ms.apply(self.ledger, data, KICKOFF - timedelta(minutes=minutes), TZ)

    def tick(self, minutes, bid, ask):
        data = {"games": {SLUG: game(live=True, score="0-1", elapsed=str(minutes), period="1H")}, "candidates": [],
                "started": [], "payouts": {}, "error": None, "books": {"yH": book(bid, ask)}}
        ms.apply(self.ledger, data, KICKOFF + timedelta(minutes=minutes), TZ)

    def settle(self, payout):
        self.sec["open"][0]["ended"] = True
        data = {"games": {}, "candidates": [], "started": [], "error": None, "books": {},
                "payouts": {self.sec["open"][0]["id"]: payout}}
        return ms.apply(self.ledger, data, KICKOFF + timedelta(hours=3), TZ)

    def test_enters_the_team_in_range_with_its_bid_and_edge(self):
        self.enter(chance=0.70)
        t = self.sec["open"][0]
        self.assertEqual((t["team"], t["entry_price"], t["bid"]), ("Chelsea FC", 0.62, 0.61))
        cost = (t["cost"] + t["fee"]) / t["shares"]
        self.assertAlmostEqual(t["edge"], round(0.70 - cost, 4))

    def test_every_variant_is_scored_on_the_same_match(self):
        self.enter(chance=0.70)
        self.tick(30, 0.48, 0.50)  # under the -20% stop: pm20 sells
        self.settle(1.0)           # and the team wins
        r = self.sec["closed"][0]["results"]
        t = self.sec["closed"][0]
        self.assertAlmostEqual(r["hold"], t["shares"] - t["cost"] - t["fee"], places=3)
        self.assertAlmostEqual(r["maker"], 25 * (1 / 0.61 - 1), places=3)
        self.assertLess(r["pm20"], 0)
        self.assertEqual(r["edge"], r["hold"])
        self.assertIsNone(r["no_edge"])

    def test_no_odds_means_neither_edge_group(self):
        self.enter()
        self.settle(0.0)
        r = self.sec["closed"][0]["results"]
        self.assertIsNone(r["edge"])
        self.assertIsNone(r["no_edge"])

    def test_out_of_range_or_thin_games_are_not_entered(self):
        self.enter(ask=0.76)
        self.assertEqual(self.sec["open"], [])
        e = game()
        e["volume"] = 9000
        trial.enter(self.sec, e, {"yH": book(0.61, 0.62)}, {}, KICKOFF)
        self.assertEqual(self.sec["open"], [])

    def test_stops_entering_at_70_and_reports_when_all_are_settled(self):
        self.sec["closed"] = [{"results": {"hold": 5.0, "maker": 6.0, "pm20": -2.0, "edge": None, "no_edge": None}}
                              for _ in range(trial.TARGET - 1)]
        self.enter()
        self.assertEqual(len(self.sec["open"]), 1)
        self.assertTrue(trial.full(self.sec))
        self.assertEqual(trial.plan(self.ledger, KICKOFF)["entered"], {SLUG})
        msgs = self.settle(1.0)
        self.assertIn("🏁 انتهت تجربة 70 مباراة", msgs[-1])
        self.assertIn("أمر محدد بلا رسوم + احتفاظ: 70 مباراة", msgs[-1])
        self.assertTrue(self.sec["final_sent"])
        self.assertEqual(self.enter(minutes=5), [])

    def test_buy_signals_are_off_while_the_trial_runs(self):
        with mock.patch.dict(os.environ, {"BUY_SIGNALS": ""}):
            self.assertFalse(st.signals_enabled())
            trial.STATE["done"] = True
            self.assertTrue(st.signals_enabled())
            trial.STATE["done"] = False
        with mock.patch.dict(os.environ, {"BUY_SIGNALS": "1"}):
            self.assertTrue(st.signals_enabled())

    def test_morning_progress_line(self):
        self.enter()
        msgs = ms.apply(self.ledger, {"games": {}, "candidates": [], "started": [], "payouts": {}, "error": None,
                                      "books": {}}, KICKOFF.replace(hour=6) + timedelta(days=1), TZ)
        self.assertTrue(any("🧪 تجربة 70 مباراة: دخلت 1، حُسمت 0" in m for m in msgs))


    def test_the_page_shows_the_trial(self):
        import polymarket_bot
        self.enter()
        self.settle(1.0)
        pt._ledger = self.ledger
        self.addCleanup(setattr, pt, "_ledger", None)
        with mock.patch("polymarket_bot.load_positions", return_value=([], "wallet", None)):
            html = polymarket_bot.app.test_client().get("/").get_data(as_text=True)
        self.assertIn("🧪 تجربة 70 مباراة", html)
        self.assertIn("1 / 70", html)
        self.assertIn("الاحتفاظ حتى النهاية (3.1)", html)
        self.assertIn("أضف ODDS_API_KEY", html)


if __name__ == "__main__":
    unittest.main()
