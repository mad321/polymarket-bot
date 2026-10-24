#!/usr/bin/env python3
"""
Tests for the automatic stop-loss sale (no network, no orders).

    python -m unittest test_auto_stop.py
"""

import os
import unittest
from decimal import Decimal
from datetime import timedelta
from unittest import mock

os.environ["ENABLE_MONITOR"] = "0"
os.environ["JOURNAL"] = "0"  # the trade journal reads the network; its tests are in test_journal.py

import auto_stop
import match_strategy as ms
import paper_trading as pt
import trading
from test_match import BOT, KICKOFF, MAIN, TZ, book, game, my_pos

ON = {"AUTO_STOP": "1", "TRADING_ENABLED": "1", "TRADING_WALLET": BOT,
      "MATCH_ALERTS": "1", "MATCH_TEST": "0", "STRICT_TEST": "0"}


def reset():
    for d in (auto_stop._tries, auto_stop._last_try):
        d.clear()
    auto_stop._busy.clear()
    auto_stop._done.clear()


def quote(price, current=0.45, shares="44"):
    return {"key": "k", "asset_id": "yH", "name": "Chelsea FC — Yes", "shares": Decimal(shares),
            "current_price": Decimal(str(current)), "price": Decimal(str(price)), "second": False}


class AppliesTests(unittest.TestCase):
    def test_off_unless_turned_on_with_selling(self):
        with mock.patch.dict(os.environ, {"TRADING_ENABLED": "1", "TRADING_WALLET": BOT}):
            os.environ.pop("AUTO_STOP", None)
            self.assertFalse(auto_stop.applies(my_pos(wallet=BOT)))
        with mock.patch.dict(os.environ, {**ON, "TRADING_ENABLED": "0"}):
            self.assertFalse(auto_stop.applies(my_pos(wallet=BOT)))
        with mock.patch.dict(os.environ, ON):
            self.assertTrue(auto_stop.applies(my_pos(wallet=BOT)))
            self.assertFalse(auto_stop.applies(my_pos(wallet=MAIN)))  # no key for this wallet


class AttemptTests(unittest.TestCase):
    def setUp(self):
        reset()
        self.addCleanup(reset)
        patcher = mock.patch.dict(os.environ, ON)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_sells_every_share_at_the_book_price(self):
        sold = {"ok": True, "status": "matched", "name": "Chelsea FC — Yes", "shares": "44",
                "order_id": "0xabc", "sold": "44", "received": "18.92"}
        with mock.patch("trading.quote", return_value=quote(0.43)), \
                mock.patch("trading.sell", return_value=sold) as sell:
            text = auto_stop.attempt("k", "Chelsea", 0.45)
        sell.assert_called_once_with("k", Decimal("44"), Decimal("0.40"))  # 3¢ of room for the delay
        self.assertIn("🤖 بيع تلقائي عند وقف الخسارة", text)
        self.assertIn("✅ تم البيع", text)
        self.assertIn("k", auto_stop._done)

    def test_thin_book_waits_says_so_once_then_gives_up(self):
        with mock.patch("trading.quote", return_value=quote(0.20)), mock.patch("trading.sell") as sell:
            first = auto_stop.attempt("k", "Chelsea", 0.45)   # 20c < 80% of 45c
            quiet = [auto_stop.attempt("k", "Chelsea", 0.45) for _ in range(auto_stop.MAX_TRIES - 2)]
            last = auto_stop.attempt("k", "Chelsea", 0.45)
        sell.assert_not_called()
        self.assertIn("المشترون قليلون", first)
        self.assertIn("سأحاول كل دقيقة", first)
        self.assertEqual(set(quiet), {None})
        self.assertIn("توقف البيع التلقائي", last)
        self.assertIn("k", auto_stop._done)

    def test_unknown_outcome_is_settled_by_the_shares_still_held(self):
        # Oct 24, Como: delayed order, no status within a minute, all 16 shares still held
        delayed = {"ok": True, "status": "delayed", "order_id": "0x5073", "asset_id": "yH",
                   "name": "Will Como 1907 win on 2026-10-24? — Yes", "min_price": "0.50", "second": True}
        with mock.patch("trading.quote", return_value=quote(0.53, current=0.525, shares="16")), \
                mock.patch("trading.sell", return_value=delayed), \
                mock.patch("trading.await_delayed_fill", return_value=None), \
                mock.patch("trading._find", return_value={"shares": Decimal("16")}):
            text = auto_stop.attempt("k", "Como", 0.525)
        self.assertIn("السعر نزل أثناء التنفيذ ولم يُبع شيء", text)
        self.assertNotIn("k", auto_stop._done)  # tried again while under the stop
        auto_stop._tries.clear()
        with mock.patch("trading.quote", return_value=quote(0.53, current=0.525, shares="16")), \
                mock.patch("trading.sell", return_value=delayed), \
                mock.patch("trading.await_delayed_fill", return_value=None), \
                mock.patch("trading._find", side_effect=trading.TradingError("لم أجد هذه الصفقة")):
            text = auto_stop.attempt("k", "Como", 0.525)
        self.assertIn("✅ تم البيع", text)
        self.assertIn("بِيع 16 سهم", text)
        self.assertIn("k", auto_stop._done)

    def test_a_position_already_gone_ends_quietly(self):
        gone = trading.TradingError("لم أجد هذه الصفقة في المحافظ التي يبيع منها البوت.")
        with mock.patch("trading.quote", side_effect=gone):
            self.assertIsNone(auto_stop.attempt("k", "Chelsea", 0.45))
        self.assertIn("k", auto_stop._done)

    def test_delayed_fill_is_followed(self):
        delayed = {"ok": True, "status": "delayed", "order_id": "0xabc", "asset_id": "yH",
                   "name": "Chelsea FC — Yes", "min_price": "0.43", "second": False}
        with mock.patch("trading.quote", return_value=quote(0.43)), \
                mock.patch("trading.sell", return_value=delayed), \
                mock.patch("trading.await_delayed_fill",
                           return_value={"status": "matched", "sold": Decimal("44"),
                                         "received": Decimal("18.9")}):
            text = auto_stop.attempt("k", "Chelsea", 0.45)
        self.assertIn("✅ تم البيع", text)
        self.assertIn("k", auto_stop._done)

    def test_request_does_not_repeat_within_15_seconds_or_after_the_sale(self):
        with mock.patch("auto_stop._start"):
            self.assertTrue(auto_stop.request(my_pos(wallet=BOT), 0.45, now=1000))
            self.assertFalse(auto_stop.request(my_pos(wallet=BOT), 0.45, now=1005))  # queued already
            auto_stop._busy.clear()
            self.assertFalse(auto_stop.request(my_pos(wallet=BOT), 0.45, now=1010))  # too soon
            self.assertTrue(auto_stop.request(my_pos(wallet=BOT), 0.45, now=1016))
            auto_stop._busy.clear()
            auto_stop._done.add(trading.position_key("yH", BOT))
            self.assertFalse(auto_stop.request(my_pos(wallet=BOT), 0.45, now=2000))
        while not auto_stop._queue.empty():
            auto_stop._queue.get()


class AlertTests(unittest.TestCase):
    def setUp(self):
        reset()
        self.addCleanup(reset)
        patcher = mock.patch.dict(os.environ, ON)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ledger = pt.new_ledger(KICKOFF)
        ms.section(self.ledger)["alerts_intro_v3"] = "x"
        ms._schedule = {"epl-che-bou-2026-10-10": game()}
        self.addCleanup(setattr, ms, "_schedule", {})

    def tick(self, pos, minutes, bid, ask):
        g = game(live=True, score="0-1", elapsed=str(minutes), period="1H")
        data = {"games": {g["slug"]: g}, "books": {"yH": book(bid, ask, size=50)},
                "positions": [{**pos, "_game": g, "_side": "home"}],
                "candidates": [], "started": [], "payouts": {}, "error": None}
        return ms.apply(self.ledger, data, KICKOFF + timedelta(minutes=minutes), TZ)

    def test_stop_on_a_sellable_wallet_sells_by_itself_and_says_so(self):
        with mock.patch("auto_stop.request") as request:
            msgs = self.tick(my_pos(wallet=BOT), 30, 0.41, 0.43)   # 42c <= 57c × 0.8
            self.tick(my_pos(wallet=BOT), 31, 0.40, 0.42)          # still below: asked again
        self.assertEqual(request.call_count, 2)
        self.assertIsInstance(msgs[0], str)  # no button: the bot is already selling
        self.assertIn("🤖 البوت يبيع كل الأسهم الآن تلقائياً", msgs[0])

    def test_other_wallets_and_the_target_keep_the_manual_flow(self):
        with mock.patch("auto_stop.request") as request:
            msgs = self.tick(my_pos(wallet=MAIN), 30, 0.41, 0.43)
            self.assertIn("القرار لك", msgs[0])
            msgs = self.tick(my_pos(wallet=BOT, token="yH"), 40, 0.75, 0.77)  # +20%: target
        request.assert_not_called()
        text, markup = msgs[0]
        self.assertIn("🟢", text)
        self.assertEqual(markup["inline_keyboard"][0][0]["text"], "🔴 بيع الآن")


if __name__ == "__main__":
    unittest.main()
