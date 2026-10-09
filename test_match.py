#!/usr/bin/env python3
"""
Tests for the football hybrid stop-loss shadow test (no network).

    python -m unittest test_match.py
"""

import os
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

os.environ["ENABLE_MONITOR"] = "0"

import pytz

import match_strategy as ms
import paper_trading as pt

TZ = pytz.timezone("Asia/Riyadh")
KICKOFF = datetime(2026, 10, 10, 14, 0, tzinfo=timezone.utc)


def event(score="", elapsed="", period="", live=False, ended=False):
    def market(mid, title, yes, no):
        return {"id": mid, "groupItemTitle": title, "sportsMarketType": "moneyline",
                "outcomes": '["Yes", "No"]', "clobTokenIds": json.dumps([yes, no]),
                "feesEnabled": True, "feeSchedule": {"rate": 0.05}, "orderMinSize": 5}
    return {"slug": "epl-che-bou-2026-10-10", "title": "Chelsea FC vs. AFC Bournemouth", "gameId": 1,
            "startTime": "2026-10-10T14:00:00Z", "endDate": "2026-10-10T14:00:00Z",
            "score": score, "elapsed": elapsed, "period": period, "live": live, "ended": ended,
            "markets": [market("11", "Chelsea FC", "yH", "nH"),
                        market("12", "Draw (Chelsea FC vs. AFC Bournemouth)", "yD", "nD"),
                        market("13", "AFC Bournemouth", "yA", "nA")]}


def game(**state):
    return ms.parse_game(event(**state), "epl")


def book(bid=None, ask=None, size=1000):
    return {"bids": [{"price": str(bid), "size": str(size)}] if bid else [],
            "asks": [{"price": str(ask), "size": str(size)}] if ask else []}


class ParsingTests(unittest.TestCase):
    def test_parse_game_maps_home_and_away_yes_tokens(self):
        g = game()
        self.assertEqual(g["sides"]["home"]["team"], "Chelsea FC")
        self.assertEqual((g["sides"]["home"]["token_id"], g["sides"]["away"]["token_id"]), ("yH", "yA"))
        self.assertEqual((g["sides"]["home"]["fee_rate"], g["start"]), (0.05, KICKOFF))
        e = event()
        e["markets"] = e["markets"][:2]
        self.assertIsNone(ms.parse_game(e, "epl"))  # not a full match winner event
        self.assertIsNone(ms.parse_game({**event(), "gameId": None}, "epl"))

    def test_minute_and_goals(self):
        self.assertEqual(ms.minute(game(elapsed="72", period="2H")), 72)
        self.assertEqual(ms.minute(game(elapsed="45+2", period="1H")), 45)
        self.assertEqual(ms.minute(game(elapsed="", period="HT")), 45)
        self.assertIsNone(ms.minute(game()))
        self.assertEqual(ms.goals(game(score="2-1")), (2, 1))
        self.assertIsNone(ms.goals(game(score="")))
        self.assertTrue(ms.finished(game(period="VFT")))


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.ledger = pt.new_ledger(KICKOFF - timedelta(days=1))
        self.sec = ms.section(self.ledger)
        ms._counted_skips.clear()
        patcher = mock.patch.dict(os.environ, {"MATCH_STAKE": "10", "MATCH_TEST": "1", "MATCH_ALERTS": "0"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def enter(self, home_ask=0.62, away_ask=0.15):
        now = KICKOFF - timedelta(minutes=10)
        data = {"games": {"epl-che-bou-2026-10-10": game()}, "candidates": ["epl-che-bou-2026-10-10"],
                "started": [], "payouts": {}, "error": None,
                "books": {"yH": book(home_ask - 0.01, home_ask), "yA": book(away_ask - 0.01, away_ask)}}
        ms.apply(self.ledger, data, now, TZ)
        return self.sec["open"][0] if self.sec["open"] else None

    def tick(self, minutes, mid_bid, mid_ask, **state):
        data = {"games": {"epl-che-bou-2026-10-10": game(live=True, **state)}, "candidates": [], "started": [],
                "payouts": {}, "error": None, "books": {"yH": book(mid_bid, mid_ask)}}
        return ms.apply(self.ledger, data, KICKOFF + timedelta(minutes=minutes), TZ)

    def test_enters_the_team_priced_55_to_75_before_kickoff(self):
        t = self.enter()
        self.assertEqual((t["team"], t["side"], t["entry_price"]), ("Chelsea FC", "home", 0.62))
        self.assertEqual(t["shares"], 16.12)
        self.assertAlmostEqual(t["fee"], 16.12 * 0.05 * 0.62 * 0.38, places=4)

    def test_no_entry_without_a_team_in_range_and_the_skip_is_counted(self):
        self.assertIsNone(self.enter(home_ask=0.45, away_ask=0.30))
        data = {"games": {}, "candidates": [], "started": ["epl-che-bou-2026-10-10"], "payouts": {},
                "error": None, "books": {}}
        ms.apply(self.ledger, data, KICKOFF + timedelta(minutes=1), TZ)
        ms.apply(self.ledger, data, KICKOFF + timedelta(minutes=2), TZ)
        self.assertEqual(self.sec["skipped"], 1)

    def test_rule_a_price_drop_of_15_cents(self):
        self.enter()
        self.tick(20, 0.50, 0.52, score="0-0", elapsed="20", period="1H")   # mid 0.51: hold
        self.assertNotIn("exit", self.sec["open"][0])
        self.tick(30, 0.46, 0.48, score="0-1", elapsed="30", period="1H")   # mid 0.47 = 0.62 - 0.15
        ex = self.sec["open"][0]["exit"]
        self.assertEqual((ex["rule"], ex["minute"], ex["score"]), ("price", 30, "0-1"))
        self.assertAlmostEqual(ex["proceeds"], 16.12 * 0.46 * (1 - 0.05 * 0.54), places=4)

    def test_rule_b_minute_65_without_a_goal(self):
        self.enter()
        self.tick(64, 0.52, 0.54, score="0-0", elapsed="64", period="2H")
        self.assertNotIn("exit", self.sec["open"][0])
        self.tick(66, 0.51, 0.53, score="0-0", elapsed="65", period="2H")
        self.assertEqual(self.sec["open"][0]["exit"]["rule"], "time")

    def test_rule_c_goal_takes_the_profit_and_a_away_goal_does_not(self):
        self.enter()
        self.tick(10, 0.55, 0.57, score="0-1", elapsed="10", period="1H")  # the opponent scored, mid 0.56
        self.assertNotIn("exit", self.sec["open"][0])
        self.tick(25, 0.70, 0.72, score="1-1", elapsed="25", period="1H")
        self.assertEqual(self.sec["open"][0]["exit"]["rule"], "goal")

    def test_wide_spread_uses_the_last_trade_not_the_midpoint(self):
        self.assertAlmostEqual(ms.mid_price(book(0.60, 0.62)), 0.61)
        self.assertEqual(ms.mid_price({**book(0.05, 0.90), "last_trade_price": "0.600"}), 0.6)
        self.assertIsNone(ms.mid_price(book(0.05, 0.90)))
        self.enter()
        self.tick(2, 0.05, 0.90, score="0-0", elapsed="2", period="1H")  # thin book at kickoff: no stop
        self.assertNotIn("exit", self.sec["open"][0])

    def test_rules_wait_for_kickoff(self):
        t = self.enter()
        self.assertIsNone(ms.exit_rule(t, game(score="", live=False), 0.40))

    def test_no_buyers_keeps_trying(self):
        self.enter()
        self.tick(66, None, 0.40, score="0-0", elapsed="66", period="2H")
        t = self.sec["open"][0]
        self.assertEqual((t.get("pending"), "exit" in t), ("time", False))
        self.tick(67, 0.30, 0.40, score="1-0", elapsed="67", period="2H")  # sells for the first rule
        self.assertEqual(self.sec["open"][0]["exit"]["rule"], "time")

    def test_settles_against_holding(self):
        self.enter()
        self.tick(30, 0.46, 0.48, score="0-1", elapsed="30", period="1H")
        data = {"games": {"epl-che-bou-2026-10-10": game(score="2-1", period="VFT", ended=True)},
                "candidates": [], "started": [], "payouts": {}, "error": None, "books": {}}
        ms.apply(self.ledger, data, KICKOFF + timedelta(minutes=115), TZ)
        self.assertTrue(self.sec["open"][0]["ended"])
        data["payouts"] = {"epl-che-bou-2026-10-10:home": 1.0}
        ms.apply(self.ledger, data, KICKOFF + timedelta(minutes=130), TZ)
        t = self.sec["closed"][0]
        paid = t["cost"] + t["fee"]
        self.assertAlmostEqual(t["hold_pnl"], 16.12 - paid, places=3)       # Chelsea came back to win
        self.assertAlmostEqual(t["strategy_pnl"], t["exit"]["proceeds"] - paid, places=3)
        lines = ms.summary_lines(self.ledger)
        self.assertIn("1 مباراة حُسمت", lines[0])
        self.assertIn("الاحتفاظ أفضل", lines[3])
        self.assertIn("الخروج: بالسعر 1، بالوقت 0، بالهدف 0، بلا خروج 0", lines[4])

    def test_a_game_without_a_final_whistle_ends_after_4_hours(self):
        self.enter()
        data = {"games": {}, "candidates": [], "started": [], "payouts": {}, "error": None, "books": {}}
        ms.apply(self.ledger, data, KICKOFF + timedelta(hours=5), TZ)
        self.assertTrue(self.sec["open"][0]["ended"])

    def test_morning_digest_once_a_day(self):
        self.enter()
        self.sec["open"][0].update(ended=True)
        data = {"games": {}, "candidates": [], "started": [], "error": None, "books": {},
                "payouts": {"epl-che-bou-2026-10-10:home": 0.0}}
        night = datetime(2026, 10, 10, 20, 0, tzinfo=timezone.utc)   # 23:00 Riyadh
        self.assertEqual(ms.apply(self.ledger, data, night, TZ), [])
        data["payouts"] = {}
        morning = datetime(2026, 10, 11, 6, 30, tzinfo=timezone.utc)  # 09:30 Riyadh
        msgs = ms.apply(self.ledger, data, morning, TZ)
        self.assertIn("⚽ اختبار الوقف المختلط", msgs[0])
        self.assertIn("1 مباراة حُسمت", msgs[0])
        self.assertEqual(ms.apply(self.ledger, data, morning + timedelta(hours=1), TZ), [])


class FetchTests(unittest.TestCase):
    def setUp(self):
        ms._schedule, ms._schedule_at = {}, None
        ms._settle_checked.clear()
        self.addCleanup(setattr, ms, "_schedule", {})
        patcher = mock.patch.dict(os.environ, {"MATCH_TEST": "1", "MATCH_ALERTS": "0"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_fetch_picks_entry_candidates_and_live_games(self):
        g = game()
        now = KICKOFF - timedelta(minutes=5)
        plan = {"live": {}, "settle": [], "entered": set()}
        with mock.patch("match_strategy.fetch_schedule", return_value={g["slug"]: g}) as sched, \
                mock.patch("match_strategy.fetch_books", return_value={"yH": book(0.6, 0.62)}) as books:
            data = ms.fetch(plan, now)
            ms.fetch(plan, now + timedelta(minutes=1))  # the schedule is reused for 10 minutes
        self.assertEqual(data["candidates"], [g["slug"]])
        self.assertEqual(data["started"], [])
        with mock.patch("match_strategy.fetch_schedule", return_value={g["slug"]: g}), \
                mock.patch("match_strategy.fetch_books", return_value={}):
            later = ms.fetch(plan, KICKOFF + timedelta(minutes=5))
            much_later = ms.fetch(plan, KICKOFF + timedelta(hours=2))
        self.assertEqual(later["started"], [g["slug"]])
        self.assertEqual(much_later["started"], [])  # started long before: not counted as skipped
        self.assertEqual(sched.call_count, 1)
        self.assertEqual(set(books.call_args_list[0].args[0]), {"yH", "yA"})

    def test_resolution_checks_are_throttled(self):
        plan = {"live": {}, "settle": [("t1", "11", "yH")], "entered": set()}
        with mock.patch("match_strategy.fetch_schedule", return_value={}), \
                mock.patch("match_strategy.stop_review.fetch_payout", return_value=1.0):
            data = ms.fetch(plan, KICKOFF)
        self.assertEqual(data["payouts"], {"t1": 1.0})
        ledger = pt.new_ledger(KICKOFF)
        ms.section(ledger)["open"].append({"id": "t1", "slug": "s", "league": "epl", "ended": True,
                                           "market_id": "11", "token_id": "yH"})
        self.assertEqual(ms.plan(ledger, KICKOFF + timedelta(minutes=5))["settle"], [])
        self.assertEqual(len(ms.plan(ledger, KICKOFF + timedelta(minutes=11))["settle"]), 1)

    def test_errors_are_reported_not_raised(self):
        with mock.patch("match_strategy.fetch_schedule", side_effect=ConnectionError("gamma down")):
            data = ms.fetch({"live": {}, "settle": [], "entered": set()}, KICKOFF)
        self.assertIn("gamma down", data["error"])

    def test_scan_once_runs_the_match_test_and_announces_it_once(self):
        ledger = pt.new_ledger(KICKOFF)
        empty = {"games": {}, "books": {}, "payouts": {}, "candidates": [], "started": [], "error": None}
        with mock.patch.dict(os.environ, {"MATCH_TEST": "1", "MATCH_ALERTS": "0", "PAPER_TRADING": "0"}), \
                mock.patch("paper_trading.match_strategy.fetch", return_value=empty):
            msgs, changed, error = pt.scan_once(ledger, KICKOFF)
            msgs2, _, _ = pt.scan_once(ledger, KICKOFF + timedelta(minutes=1))
        self.assertIn("⚽ بدأ اختبار استراتيجية الوقف المختلط", msgs[0])
        self.assertTrue(changed)
        self.assertEqual(msgs2, [])
        self.assertIn("match_test", ledger)


# ─── ALERTS ON YOUR POSITIONS ───────────────────────────────────────────────

MAIN = "0x0c4526398bba16e31f23ca818d767cb00b02921c"
BOT = "0xb0b0000000000000000000000000000000000001"


def my_pos(token="yH", wallet=MAIN, outcome="Yes", title="Will Chelsea FC win on 2026-10-10?",
           event="epl-che-bou-2026-10-10", buy=57.0, shares=44.0):
    return {"id": token, "wallet": wallet, "outcome": outcome, "title": title, "event": event,
            "name": f"{title} — {outcome}", "buy_price": buy, "shares": shares, "current_price": buy,
            "url": f"https://polymarket.com/event/{event}", "stop_loss": 40.0, "take_profit": 85.0}


class PositionAlertTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"MATCH_ALERTS": "1", "MATCH_TEST": "0",
                                               "TRADING_WALLET": BOT, "TRADING_ENABLED": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ledger = pt.new_ledger(KICKOFF)
        ms._schedule = {"epl-che-bou-2026-10-10": game()}
        self.addCleanup(setattr, ms, "_schedule", {})
        ms.STATE["alerts_sent"] = 0

    def run_tick(self, pos, minutes, bid, ask, **state):
        g = game(live=True, **state)
        p = {**pos, "_game": g, "_side": "home"}
        data = {"games": {g["slug"]: g}, "books": {"yH": book(bid, ask, size=30)}, "positions": [p],
                "candidates": [], "started": [], "payouts": {}, "error": None}
        return ms.apply(self.ledger, data, KICKOFF + timedelta(minutes=minutes), TZ)

    def test_covers_only_team_win_yes_in_the_chosen_leagues(self):
        self.assertTrue(ms.covers(my_pos()))
        self.assertFalse(ms.covers(my_pos(outcome="No")))
        self.assertFalse(ms.covers(my_pos(title="Will Chelsea FC vs. AFC Bournemouth end in a draw?")))
        self.assertFalse(ms.covers(my_pos(event="mls-lag-sea-2026-10-10")))
        self.assertFalse(ms.covers(my_pos(title="Saudi Arabia military action against Yemen on September 21?",
                                          event="saudi-arabia-military-action-against-yemen-on-20260916")))
        with mock.patch.dict(os.environ, {"MATCH_ALERTS": "0"}):
            self.assertFalse(ms.covers(my_pos()))

    def test_positions_are_read_only_while_a_game_is_under_way(self):
        with mock.patch("match_strategy.positions_module.load_positions",
                        return_value=([my_pos(), my_pos(token="other")], "wallet", None)) as load:
            self.assertEqual(ms._positions_in_play(KICKOFF - timedelta(minutes=5)), [])
            load.assert_not_called()
            found = ms._positions_in_play(KICKOFF + timedelta(minutes=20))
        self.assertEqual([(p["id"], p["_side"], p["_game"]["slug"]) for p in found],
                         [("yH", "home", "epl-che-bou-2026-10-10")])

    def test_intro_once_then_each_rule_once_per_position(self):
        msgs = self.run_tick(my_pos(), 10, 0.55, 0.57, score="0-0", elapsed="10", period="1H")
        self.assertEqual(len(msgs), 1)
        self.assertIn("تنبيهات الوقف المختلط تعمل الآن", msgs[0])
        msgs = self.run_tick(my_pos(), 30, 0.41, 0.43, score="0-1", elapsed="30", period="1H")  # 42 <= 57 - 15
        self.assertEqual(len(msgs), 1)
        text = msgs[0]
        self.assertIn("🔴 الوقف المختلط: السعر نزل 15¢ عن سعر شرائك", text)
        self.assertIn("Chelsea FC vs. AFC Bournemouth: 0-1 (الدقيقة 30)", text)
        self.assertIn("سعر شرائك 57¢، والسعر الآن 42.0¢", text)
        self.assertIn("بيع 30 سهم الآن", text)
        self.assertIn("لا مشترين لباقي الأسهم (14)", text)
        self.assertIn("المحفظة الرئيسية", text)
        self.assertIn("https://polymarket.com/event/epl-che-bou-2026-10-10", text)
        self.assertEqual(self.run_tick(my_pos(), 31, 0.40, 0.42, score="0-1", elapsed="31", period="1H"), [])
        msgs = self.run_tick(my_pos(), 50, 0.75, 0.77, score="1-1", elapsed="50", period="2H")
        self.assertIn("🟢 الوقف المختلط: Chelsea FC سجّل", msgs[0])
        self.assertEqual(ms.STATE["alerts_sent"], 2)

    def test_time_stop_alert(self):
        self.run_tick(my_pos(), 10, 0.55, 0.57, score="0-0", elapsed="10", period="1H")
        msgs = self.run_tick(my_pos(), 80, 0.45, 0.47, score="0-0", elapsed="66", period="2H")
        self.assertIn("⏰ الوقف المختلط: الدقيقة 66 ولم يسجّل Chelsea FC", msgs[0])

    def test_bot_wallet_alert_comes_with_the_sell_button(self):
        self.run_tick(my_pos(), 10, 0.55, 0.57, score="0-0", elapsed="10", period="1H")
        msgs = self.run_tick(my_pos(wallet=BOT), 30, 0.41, 0.43, score="0-1", elapsed="30", period="1H")
        text, markup = msgs[0]
        self.assertIn("محفظة البوت", text)
        self.assertEqual(markup["inline_keyboard"][0][0]["text"], "🔴 بيع الآن")

    def test_monitor_skips_generic_levels_for_covered_positions(self):
        import polymarket_monitor as monitor
        covered = my_pos(buy=72.0)
        covered["current_price"] = 30.0          # far below its 40¢ generic stop
        other = my_pos(token="y2", outcome="No", title="Saudi Arabia military action?", event="saudi-x")
        other.update(current_price=30.0, stop_loss=40.0)
        with mock.patch("polymarket_monitor.load_positions", return_value=([covered, other], "wallet", None)), \
                mock.patch("polymarket_monitor.alerts.send_alert", return_value=True) as send, \
                mock.patch("polymarket_monitor.stop_review.record"), \
                mock.patch("polymarket_monitor.exposure.check"):
            monitor.check_once({})
        self.assertEqual(send.call_count, 1)
        self.assertIn("Saudi Arabia military action?", send.call_args.args[0])

    def test_fetch_reads_the_games_and_books_of_your_positions(self):
        ms._schedule_at = KICKOFF + timedelta(minutes=20)  # fresh: no schedule read
        live = game(live=True, score="0-0", elapsed="20", period="1H")
        with mock.patch("match_strategy.positions_module.load_positions",
                        return_value=([my_pos()], "wallet", None)), \
                mock.patch("match_strategy.fetch_game", return_value=live) as fetch_game, \
                mock.patch("match_strategy.fetch_books", return_value={"yH": book(0.5, 0.52)}) as books:
            data = ms.fetch({"live": {}, "settle": [], "entered": set()}, KICKOFF + timedelta(minutes=20))
        fetch_game.assert_called_once_with("epl-che-bou-2026-10-10", "epl")
        self.assertIn("yH", books.call_args.args[0])
        self.assertEqual(len(data["positions"]), 1)

    def test_run_forever_sends_buttons_with_the_text(self):
        store = mock.Mock(describe=lambda: "mock")
        store.load.return_value = pt.new_ledger(KICKOFF)

        class Stop(BaseException):
            pass
        pt._ledger = None
        self.addCleanup(setattr, pt, "_ledger", None)
        import stop_review
        self.addCleanup(setattr, stop_review, "ACTIVE", False)
        with mock.patch("paper_trading.paper_store.default_store", return_value=store), \
                mock.patch("paper_trading.time.sleep", side_effect=Stop), \
                mock.patch("paper_trading.scan_once", return_value=([("نص", {"k": 1}), "عادي"], False, None)), \
                mock.patch("paper_trading.alerts.send_alert") as send:
            with self.assertRaises(Stop):
                pt.run_forever()
        self.assertEqual(send.call_args_list[0].args, ("نص", {"k": 1}))
        self.assertEqual(send.call_args_list[1].args, ("عادي",))


if __name__ == "__main__":
    unittest.main()
