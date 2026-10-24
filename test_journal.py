#!/usr/bin/env python3
"""
Tests for the trade journal and the private part of the dashboard (no network).

    python -m unittest test_journal.py
"""

import os
import unittest
from datetime import datetime, timezone
from unittest import mock

os.environ["ENABLE_MONITOR"] = "0"
os.environ["JOURNAL"] = "0"
os.environ["TRIAL"] = "0"  # the 70-match trial has its own tests (test_trial.py)

import paper_trading as pt
import trade_journal as tj

W = "0x0c4526398bba16e31f23ca818d767cb00b02921c"
T = int(datetime(2026, 10, 20, tzinfo=timezone.utc).timestamp())


def row(kind, side, title, asset, size, usd, ts, event="lal-ala-mala-2026-10-23"):
    return {"type": kind, "side": side, "title": title, "asset": asset, "size": size, "usdcSize": usd,
            "timestamp": ts, "outcome": "Yes", "eventSlug": event}


ALAVES = "Will Deportivo Alavés win on 2026-10-23?"
NASSR = "Will Al Nassr Saudi Club win on 2026-10-20?"
ROWS = [  # from the owner's history (Oct 2026)
    row("TRADE", "BUY", ALAVES, "a1", 42, 25.704, T),
    row("TRADE", "SELL", ALAVES, "a1", 42, 1.59936, T + 7000),
    row("TRADE", "BUY", NASSR, "n1", 34, 23.82, T, event="spl-fai-nsr-2026-10-20"),
    row("TRADE", "SELL", NASSR, "n1", 34, 27.98, T + 5000, event="spl-fai-nsr-2026-10-20"),
    row("TRADE", "BUY", "Will NEOM SC win on 2026-10-24?", "o1", 38, 24.38, T, event="spl-neo-abh-2026-10-24"),
    row("TRADE", "BUY", "Will Iceland win on 2026-10-06?", "i1", 41, 25.5, T, event="unl-isl-x-2026-10-06"),
    row("REDEEM", None, "Will Iceland win on 2026-10-06?", "i1", 41, 0, T + 9000, event="unl-isl-x-2026-10-06"),
    row("TRADE", "BUY", "Saudi Arabia military action?", "y1", 50, 20, T),  # not football
]


class PositionTests(unittest.TestCase):
    def test_positions_and_which_are_closed(self):
        ps = tj.positions_from(ROWS, W)
        self.assertEqual(len(ps), 4)
        self.assertTrue(tj.closed(ps[f"{W}:a1"]))
        self.assertFalse(tj.closed(ps[f"{W}:o1"]))  # NEOM still open
        self.assertTrue(tj.closed(ps[f"{W}:i1"]))   # redeemed for nothing: lost

    def test_records_say_how_each_trade_ended(self):
        ps = tj.positions_from(ROWS, W)
        alaves = tj.record(ps[f"{W}:a1"], 0.0)
        self.assertEqual((alaves["team"], alaves["league"], alaves["ending"]), ("Deportivo Alavés", "lal", "deep"))
        self.assertAlmostEqual(alaves["pnl"], 1.59936 - 25.704, places=4)
        self.assertAlmostEqual(alaves["hold_pnl"], -25.704, places=4)
        nassr = tj.record(ps[f"{W}:n1"], 1.0)
        self.assertEqual((nassr["ending"], nassr["elite"]), ("profit", True))
        self.assertAlmostEqual(nassr["hold_pnl"], 34 - 23.82, places=4)
        iceland = tj.record(ps[f"{W}:i1"], 0.0)
        self.assertEqual(iceland["ending"], "held")

    def test_wilson_range(self):
        low, high = tj.wilson(18, 30)
        self.assertAlmostEqual(low, 0.423, places=2)
        self.assertAlmostEqual(high, 0.754, places=2)
        self.assertEqual(tj.wilson(0, 0), (0.0, 1.0))

    def test_groups_need_30_trades_to_be_judged(self):
        win = {"entry": 0.6, "elite": True, "league": "epl", "ending": "held", "pnl": 10, "cost": 25, "hold_pnl": 10}
        lose = {**win, "pnl": -25, "hold_pnl": -25}
        table = {(g["dim"], g["name"]): g for g in tj.stats([win] * 5 + [lose] * 5)}
        self.assertEqual(table[("السعر", "55–62¢")]["verdict"], "فرضية")
        table = {(g["dim"], g["name"]): g for g in tj.stats([win] * 28 + [lose] * 2)}
        self.assertEqual(table[("السعر", "55–62¢")]["verdict"], "يربح")
        table = {(g["dim"], g["name"]): g for g in tj.stats([win] * 5 + [lose] * 25)}
        self.assertEqual(table[("الفريق", "من قائمة النخبة")]["verdict"], "يخسر")


class IndicatorTests(unittest.TestCase):
    def test_verdicts(self):
        self.assertEqual(tj.indicator(4, 2, -5.65, 101)["status"], "مبكر للحكم")
        self.assertEqual(tj.indicator(4, 2, -5.65, 101)["progress"], 13)
        self.assertEqual(tj.indicator(40, 32, 90, 1000)["status"], "ناجحة")   # 80%, range above 57%
        self.assertEqual(tj.indicator(40, 12, -90, 1000)["status"], "خاسرة")  # 30%, range below
        self.assertEqual(tj.indicator(40, 24, 10, 1000)["status"], "غير محسومة")
        self.assertIsNone(tj.indicator(0, 0, 0, 0)["rate"])

    def test_real_indicators_count_from_strategy_3(self):
        old = {"closed_at": "2026-10-10T00:00:00+00:00", "pnl": -10, "cost": 25, "hold_pnl": 15}
        new = {"closed_at": "2026-10-20T00:00:00+00:00", "pnl": 5, "cost": 25, "hold_pnl": 12}
        ind = tj.real_indicators([old, new, {**new, "hold_pnl": None, "pnl": -3}])
        self.assertEqual((ind["actual"]["n"], ind["actual"]["wins"], ind["actual"]["pnl"]), (2, 1, 2))
        self.assertEqual((ind["hold"]["n"], ind["hold"]["pnl"]), (1, 12))


class ApplyTests(unittest.TestCase):
    def fetched(self, rows=ROWS):
        ps = tj.positions_from(rows, W)
        return {"positions": ps, "payouts": {f"{W}:a1": 0.0, f"{W}:i1": 0.0}, "error": None}

    def test_first_fill_is_silent_then_each_new_trade_teaches(self):
        ledger = pt.new_ledger(datetime.now(timezone.utc))
        self.assertEqual(tj.apply(ledger, self.fetched(ROWS[:4]), None), [])
        self.assertEqual(len(ledger["journal"]["trades"]), 2)
        msgs = tj.apply(ledger, self.fetched(), None)
        self.assertEqual(len(msgs), 1)  # Iceland closed since; NEOM is still open
        self.assertIn("📘 صفقة أُغلقت: Iceland (unl)", msgs[0])
        self.assertIn("حتى النهاية", msgs[0])
        self.assertIn("فرضية", msgs[0])
        self.assertEqual(tj.apply(ledger, self.fetched(), None), [])

    def test_hold_comparison_in_the_message(self):
        ledger = pt.new_ledger(datetime.now(timezone.utc))
        tj.apply(ledger, {"positions": {}, "payouts": {}, "error": None}, None)  # first fill: nothing yet
        msgs = tj.apply(ledger, self.fetched(ROWS[:2]), None)
        self.assertIn("لو احتفظت حتى النهاية: ‎-$25.70 → البيع كان أفضل بـ $1.60", msgs[0])

    def test_a_payout_found_later_completes_the_record(self):
        ledger = pt.new_ledger(datetime.now(timezone.utc))
        f = self.fetched(ROWS[2:4])
        tj.apply(ledger, f, None)
        self.assertNotIn("hold_pnl", ledger["journal"]["trades"][f"{W}:n1"])
        f["payouts"][f"{W}:n1"] = 1.0
        tj.apply(ledger, f, None)
        self.assertAlmostEqual(ledger["journal"]["trades"][f"{W}:n1"]["hold_pnl"], 10.18, places=2)

    def test_fetch_reads_payouts_only_for_trades_sold_before_the_end(self):
        tj._outcome_checked.clear()
        with mock.patch("trade_journal.positions_module.watched_wallets", return_value=[W]), \
                mock.patch("trade_journal.fetch_activity", return_value=ROWS), \
                mock.patch("trade_journal.fetch_payout", return_value=1.0) as payout:
            out = tj.fetch({"trades": {}}, 1_800_000_000.0)
        self.assertEqual(out["payouts"][f"{W}:i1"], 0.0)  # from the redeem, no request
        self.assertEqual({c.args[0] for c in payout.call_args_list}, {"a1", "n1"})

    def test_the_journal_is_never_public(self):
        pt._ledger = pt.new_ledger(datetime.now(timezone.utc))
        self.addCleanup(setattr, pt, "_ledger", None)
        tj.apply(pt._ledger, self.fetched(), None)
        self.assertNotIn("journal", pt.public_ledger())
        self.assertEqual(pt.journal_figures()["n"], 3)


class PrivatePageTests(unittest.TestCase):
    def get(self, url, env, cookie=None):
        import polymarket_bot
        client = polymarket_bot.app.test_client()
        if cookie:
            client.set_cookie("dashboard_key", cookie)
        with mock.patch.dict(os.environ, env), \
                mock.patch("polymarket_bot.load_positions", return_value=([], "wallet", None)), \
                mock.patch("exposure.cash", return_value=812.5):
            return client.get(url)

    def test_hidden_without_the_key(self):
        html = self.get("/", {"DASHBOARD_KEY": "s3cret"}).get_data(as_text=True)
        self.assertNotIn("812.50", html)
        self.assertNotIn("قيمة المحفظة الآن", html)
        html = self.get("/?key=wrong", {"DASHBOARD_KEY": "s3cret"}).get_data(as_text=True)
        self.assertNotIn("812.50", html)
        self.assertIn("الكلمة في الرابط لا تطابق DASHBOARD_KEY", html)
        self.assertNotIn("s3cret", html)

    def test_spaces_and_invisible_marks_around_the_key_are_ignored(self):
        html = self.get("/?key=%20s3cret%E2%80%8E", {"DASHBOARD_KEY": " s3cret\n"}).get_data(as_text=True)
        self.assertIn("$812.50", html)

    def test_says_how_when_no_key_is_set(self):
        os.environ.pop("DASHBOARD_KEY", None)
        html = self.get("/", {}).get_data(as_text=True)
        self.assertIn("أضف DASHBOARD_KEY في Render", html)

    def test_the_owner_link_shows_value_and_cash_and_sets_a_cookie(self):
        r = self.get("/?key=s3cret", {"DASHBOARD_KEY": "s3cret"})
        html = r.get_data(as_text=True)
        self.assertIn("قيمة المحفظة الآن", html)
        self.assertIn("$812.50", html)
        self.assertIn("dashboard_key=s3cret", r.headers.get("Set-Cookie", ""))
        html = self.get("/", {"DASHBOARD_KEY": "s3cret"}, cookie="s3cret").get_data(as_text=True)
        self.assertIn("$812.50", html)

    def test_the_page_shows_both_strategy_indicators(self):
        pt._ledger = pt.new_ledger(datetime.now(timezone.utc))
        self.addCleanup(setattr, pt, "_ledger", None)
        tj.apply(pt._ledger, ApplyTests.fetched(None), None)
        html = self.get("/?key=s3cret", {"DASHBOARD_KEY": "s3cret"}).get_data(as_text=True)
        self.assertIn("مؤشر 3.0 كما هي", html)
        self.assertIn("مؤشر 3.1: نفس الدخول، احتفاظ حتى النهاية", html)
        self.assertIn("مؤشر صفقاتك الحقيقية منذ 3.0", html)
        self.assertIn("مبكر للحكم", html)
        self.assertNotIn("دوري أمم أوروبا", html)


if __name__ == "__main__":
    unittest.main()
