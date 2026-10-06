#!/usr/bin/env python3
"""
Tests for paper trading on the Bitcoin "above" markets and its ledger storage
(no network: HTTP and Telegram are mocked).

    python -m unittest test_paper.py
"""

import os
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

os.environ["ENABLE_MONITOR"] = "0"

import paper_store
import paper_trading as pt
import telegram_actions

NOW = datetime(2026, 10, 6, 15, 0, tzinfo=timezone.utc)   # a Tuesday
END = datetime(2026, 10, 8, 16, 0, tzinfo=timezone.utc)   # noon ET
TOKEN = "123456:SECRET"


def gamma_market(mid="1", strike="86,000", closed=False, end=END, **extra):
    m = {
        "id": mid, "groupItemTitle": strike, "outcomes": '["Yes", "No"]',
        "clobTokenIds": json.dumps([f"y{mid}", f"n{mid}"]), "endDate": end.isoformat().replace("+00:00", "Z"),
        "closed": closed, "acceptingOrders": not closed, "enableOrderBook": True,
        "feesEnabled": True, "feeSchedule": {"exponent": 1, "rate": 0.07, "takerOnly": True},
        "orderMinSize": 5,
    }
    m.update(extra)
    return m


def market(mid="1", strike=86000.0, end=END, event="bitcoin-above-on-october-8-2026"):
    return {"market_id": mid, "event": event, "strike": strike, "end": end,
            "tokens": {"YES": f"y{mid}", "NO": f"n{mid}"}, "fee_rate": 0.07, "min_size": 5}


def book(asks=(), bids=()):
    return {"asks": [{"price": str(p), "size": str(s)} for p, s in asks],
            "bids": [{"price": str(p), "size": str(s)} for p, s in bids]}


class ModelTests(unittest.TestCase):
    def test_fair_probability(self):
        # At the money the drift term leaves it just under one half
        self.assertAlmostEqual(pt.fair_probability(86000, 86000, 0.3, 2 / 365), 0.4956, places=4)
        self.assertGreater(pt.fair_probability(90000, 80000, 0.3, 2 / 365), 0.999)
        self.assertLess(pt.fair_probability(80000, 90000, 0.3, 2 / 365), 0.001)
        self.assertEqual(pt.fair_probability(86001, 86000, 0.3, 0), 1.0)
        self.assertEqual(pt.fair_probability(85999, 86000, 0.3, 0), 0.0)

    def test_realized_vol_annualizes_hourly_returns(self):
        closes = [100 * (1.01 if i % 2 else 1) for i in range(49)]  # ±1% every hour
        sigma = pt.realized_vol(closes)
        self.assertAlmostEqual(sigma, 0.00995 * (8760 ** 0.5), delta=0.02)
        with self.assertRaises(ValueError):
            pt.realized_vol([100, 101, 102])

    def test_simulate_buy_walks_the_book_and_adds_taker_fee(self):
        fill = pt.simulate_buy([{"price": "0.62", "size": "50"}, {"price": "0.60", "size": "10"}],
                               stake=10, fee_rate=0.07)
        # 10 shares at 0.60 ($6), then $4 at 0.62 → 6.45 shares
        self.assertEqual(fill["shares"], 16.45)
        self.assertAlmostEqual(fill["cost"], 6 + 6.45 * 0.62, places=4)
        expected_fee = 10 * 0.07 * 0.6 * 0.4 + 6.45 * 0.07 * 0.62 * 0.38
        self.assertAlmostEqual(fill["fee"], expected_fee, places=5)

    def test_simulate_buy_refuses_thin_books_and_small_orders(self):
        self.assertIsNone(pt.simulate_buy([{"price": "0.5", "size": "3"}], 10, 0.07))
        self.assertIsNone(pt.simulate_buy([{"price": "0.99", "size": "100"}], 4, 0.07, min_size=5))
        self.assertIsNone(pt.simulate_buy([], 10, 0.07))


class MarketParsingTests(unittest.TestCase):
    def test_parses_open_markets_with_token_sides_and_fees(self):
        events = [{"slug": "bitcoin-above-on-october-8-2026", "endDate": "2026-10-08T16:00:00Z", "markets": [
            gamma_market("1", outcomes='["No", "Yes"]'),
            gamma_market("2", strike="90,000", feesEnabled=False),
            gamma_market("3", closed=True),
            gamma_market("4", strike="n/a"),
        ]}]
        out = pt.parse_markets(events)
        self.assertEqual([m["market_id"] for m in out], ["1", "2"])
        self.assertEqual(out[0]["tokens"], {"YES": "n1", "NO": "y1"})
        self.assertEqual((out[0]["strike"], out[0]["fee_rate"], out[0]["end"]), (86000.0, 0.07, END))
        self.assertEqual((out[1]["strike"], out[1]["fee_rate"]), (90000.0, 0))

    def test_fetch_winner_only_after_a_clean_resolution(self):
        cases = [
            ({"closed": False, "outcomes": '["Yes", "No"]', "outcomePrices": '["0.6", "0.4"]'}, None),
            ({"closed": True, "outcomes": '["Yes", "No"]', "outcomePrices": '["1", "0"]'}, "YES"),
            ({"closed": True, "outcomes": '["Yes", "No"]', "outcomePrices": '["0", "1"]'}, "NO"),
            ({"closed": True, "outcomes": '["Yes", "No"]', "outcomePrices": '["0.5", "0.5"]'}, None),
        ]
        for data, expected in cases:
            with mock.patch("paper_trading._get", return_value=data):
                self.assertEqual(pt.fetch_winner("1"), expected)


class TradingTests(unittest.TestCase):
    def setUp(self):
        patches = [mock.patch.object(pt, "STAKE", 10), mock.patch.object(pt, "MIN_EDGE", 0.05)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.ledger = pt.new_ledger(NOW)

    def books(self, yes_ask, no_ask, mid="1"):
        return {f"y{mid}": book(asks=[(yes_ask, 1000)], bids=[(round(1 - no_ask, 2), 1000)]),
                f"n{mid}": book(asks=[(no_ask, 1000)], bids=[(round(1 - yes_ask, 2), 1000)])}

    def test_buys_the_side_the_model_finds_cheap(self):
        # Spot well above the strike: the model says Yes ≈ 0.75
        fair = pt.fair_probability(87500, 86000, 0.3, (END - NOW).total_seconds() / (365 * 86400))
        msgs = pt.open_trades(self.ledger, [market()], self.books(0.60, 0.41), 87500, 0.3, NOW)
        self.assertEqual(len(self.ledger["open"]), 1)
        t = self.ledger["open"][0]
        self.assertEqual((t["side"], t["price"], t["shares"]), ("YES", 0.6, 16.66))
        self.assertAlmostEqual(t["fair"], fair, places=4)
        self.assertAlmostEqual(t["edge"], fair - 0.6 - 0.07 * 0.6 * 0.4, places=3)
        self.assertIn("صفقة ورقية جديدة (بدون مال حقيقي)", msgs[0])
        self.assertIn("هل البيتكوين فوق $86,000 يوم 8 أكتوبر؟", msgs[0])
        self.assertIn("الشراء: نعم بسعر 60.0¢", msgs[0])

    def test_no_trade_when_the_edge_is_below_the_minimum(self):
        msgs = pt.open_trades(self.ledger, [market()], self.books(0.73, 0.28), 87500, 0.3, NOW)
        self.assertEqual((msgs, self.ledger["open"]), ([], []))
        self.assertIsNotNone(self.ledger["best_edge"])  # still reported in the summary

    def test_one_trade_per_expiry_date_with_the_biggest_edge(self):
        markets = [market("1", 86000.0), market("2", 88000.0)]
        books = {**self.books(0.60, 0.41, "1"), **self.books(0.10, 0.91, "2")}
        pt.open_trades(self.ledger, markets, books, 87500, 0.3, NOW)
        pt.open_trades(self.ledger, markets, books, 87500, 0.3, NOW + timedelta(minutes=5))
        self.assertEqual(len(self.ledger["open"]), 1)
        self.assertEqual(self.ledger["open"][0]["market_id"], "2")  # Yes at 10¢ vs fair ≈ 0.35

    def test_skips_markets_close_to_expiry_and_extreme_prices(self):
        late = NOW.replace(hour=15)
        soon = market(end=late + timedelta(hours=1))
        pt.open_trades(self.ledger, [soon], self.books(0.20, 0.81), 87500, 0.3, late)
        self.assertEqual(self.ledger["open"], [])
        self.assertIsNone(self.ledger["best_edge"])
        # Deep in the money: the model's edge sits at a 97¢ price
        pt.open_trades(self.ledger, [market(strike=70000.0)], self.books(0.97, 0.04), 87500, 0.3, NOW)
        self.assertEqual(self.ledger["open"], [])

    def test_snapshot_only_in_the_24_hour_window(self):
        m = market()
        books = self.books(0.60, 0.41)
        pt.open_trades(self.ledger, [m], books, 87500, 0.3, END - timedelta(hours=30))
        self.assertEqual(self.ledger["snapshots"], {})
        pt.open_trades(self.ledger, [m], books, 87500, 0.3, END - timedelta(hours=23))
        snap = self.ledger["snapshots"]["1"]
        self.assertEqual(snap["market"], 0.595)  # mid of 0.59 bid and 0.60 ask
        later = self.ledger["snapshots"]["1"].copy()
        pt.open_trades(self.ledger, [m], books, 90000, 0.3, END - timedelta(hours=21))
        self.assertEqual(self.ledger["snapshots"]["1"], later)  # first snapshot kept

    def test_settles_wins_and_losses_and_scores_both_forecasts(self):
        pt.open_trades(self.ledger, [market()], self.books(0.60, 0.41), 87500, 0.3, NOW)
        self.ledger["snapshots"]["1"] = {"end": END.isoformat(), "model": 0.8, "market": 0.6}
        self.ledger["snapshots"]["9"] = {"end": (END - timedelta(days=8)).isoformat(), "model": 0.5, "market": 0.5}
        after = END + timedelta(minutes=20)
        self.assertEqual(pt.due_market_ids(self.ledger, after), {"1", "9"})

        msgs = pt.settle(self.ledger, {"1": "YES"}, after)
        t = self.ledger["closed"][0]
        self.assertEqual((t["result"], t["payout"]), ("won", 16.66))
        self.assertAlmostEqual(t["pnl"], 16.66 - t["cost"] - t["fee"], places=4)
        self.assertIn("✅ ربحت الصفقة الورقية", msgs[0])
        cal = self.ledger["calibration"]
        self.assertEqual(cal["n"], 1)
        self.assertAlmostEqual(cal["model"], 0.04)
        self.assertAlmostEqual(cal["market"], 0.16)
        self.assertEqual(self.ledger["snapshots"], {})  # resolved one scored, 8-day-old one dropped

    def test_losing_trade(self):
        pt.open_trades(self.ledger, [market()], self.books(0.60, 0.41), 87500, 0.3, NOW)
        msgs = pt.settle(self.ledger, {"1": "NO"}, END + timedelta(minutes=20))
        t = self.ledger["closed"][0]
        self.assertEqual((t["result"], t["payout"]), ("lost", 0.0))
        self.assertAlmostEqual(t["pnl"], -(t["cost"] + t["fee"]), places=4)
        self.assertIn("❌ خسرت", msgs[0])
        self.assertIn("‎-$", msgs[0])

    def test_summary_reports_results_accuracy_and_the_caveat(self):
        pt.open_trades(self.ledger, [market()], self.books(0.60, 0.41), 87500, 0.3, NOW)
        pt.settle(self.ledger, {"1": "YES"}, END + timedelta(minutes=20))
        self.ledger["calibration"] = {"n": 4, "model": 0.4, "market": 0.2}
        text = pt.summary_text(self.ledger, END + timedelta(hours=1), "ملخص")
        self.assertIn("صفقات حُسمت 1 (ربح 1، خسارة 0)", text)
        self.assertIn("السوق أدق من النموذج", text)
        self.assertIn("4 أسابيع و30 صفقة", text)


class ScheduleTests(unittest.TestCase):
    def test_weekly_summary_is_due_once_after_friday_evening(self):
        ledger = pt.new_ledger(NOW)
        friday_noon = datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc)      # 12:00 Riyadh
        friday_evening = datetime(2026, 10, 9, 15, 30, tzinfo=timezone.utc)  # 18:30 Riyadh
        self.assertFalse(pt.summary_due(ledger, friday_noon))
        self.assertTrue(pt.summary_due(ledger, friday_evening))
        ledger["summary_week"] = pt._week(friday_evening)
        self.assertFalse(pt.summary_due(ledger, friday_evening + timedelta(days=1)))
        self.assertTrue(pt.summary_due(ledger, friday_evening + timedelta(days=7)))

    def test_a_ledger_started_on_saturday_waits_for_next_friday(self):
        saturday = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)
        ledger = pt.new_ledger(saturday)
        self.assertFalse(pt.summary_due(ledger, saturday + timedelta(hours=1)))
        self.assertTrue(pt.summary_due(ledger, saturday + timedelta(days=6, hours=7)))

    def test_scan_once_sends_the_weekly_summary_and_resets_the_week(self):
        ledger = pt.new_ledger(NOW)
        ledger["best_edge"] = {"edge": 0.02, "side": "NO", "name": "x", "price": 0.4, "fair": 0.43}
        friday_evening = datetime(2026, 10, 9, 15, 30, tzinfo=timezone.utc)
        with mock.patch("paper_trading.fetch_spot_and_vol", return_value=(87500, 0.3, "binance")), \
                mock.patch("paper_trading.fetch_markets", return_value=[]), \
                mock.patch("paper_trading.fetch_books", return_value={}):
            msgs, changed = pt.scan_once(ledger, friday_evening)
        self.assertTrue(changed)
        self.assertIn("ملخص الأسبوع", msgs[0])
        self.assertEqual(ledger["summary_week"], pt._week(friday_evening))
        self.assertIsNone(ledger["best_edge"])


def tg_response(result=None, ok=True, description=""):
    r = mock.Mock(ok=ok, status_code=200 if ok else 400)
    r.json.return_value = {"ok": ok, "result": result, "description": description}
    return r


class TelegramStoreTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "42"})
        p.start()
        self.addCleanup(p.stop)
        self.store = paper_store.TelegramStore()

    def test_loads_the_pinned_ledger_file(self):
        pinned = {"message_id": 7, "from": {"is_bot": True},
                  "document": {"file_name": "paper_trades.json", "file_id": "F"}}
        download = mock.Mock()
        download.raise_for_status.return_value = None
        download.json.return_value = {"version": 1}
        with mock.patch("paper_store.requests.post", side_effect=[
                tg_response({"pinned_message": pinned}), tg_response({"file_path": "docs/x.json"})]), \
                mock.patch("paper_store.requests.get", return_value=download) as get:
            self.assertEqual(self.store.load(), {"version": 1})
        self.assertTrue(get.call_args.args[0].endswith("/docs/x.json"))
        self.assertEqual((self.store.message_id, self.store.pinned), (7, True))

    def test_no_ledger_when_something_else_is_pinned(self):
        with mock.patch("paper_store.requests.post", return_value=tg_response(
                {"pinned_message": {"message_id": 3, "from": {"is_bot": False}, "text": "hi"}})):
            self.assertIsNone(self.store.load())
        with mock.patch("paper_store.requests.post", return_value=tg_response({})):
            self.assertIsNone(self.store.load())

    def test_first_save_sends_and_pins_then_edits_in_place(self):
        with mock.patch("paper_store.requests.post", side_effect=[
                tg_response({"message_id": 9}), tg_response(True)]) as post:
            self.store.save({"version": 1})
        self.assertEqual([c.args[0].rsplit("/", 1)[1] for c in post.call_args_list],
                         ["sendDocument", "pinChatMessage"])
        self.assertEqual(post.call_args_list[0].kwargs["data"]["disable_notification"], "true")
        with mock.patch("paper_store.requests.post", return_value=tg_response({})) as post:
            self.store.save({"version": 2})
        self.assertEqual(post.call_args.args[0].rsplit("/", 1)[1], "editMessageMedia")
        self.assertEqual(post.call_args.kwargs["data"]["message_id"], 9)

    def test_unmodified_is_fine_and_a_deleted_message_is_replaced(self):
        self.store.message_id, self.store.pinned = 9, True
        with mock.patch("paper_store.requests.post", return_value=tg_response(
                ok=False, description="Bad Request: message is not modified")):
            self.store.save({"version": 1})
        with mock.patch("paper_store.requests.post", side_effect=[
                tg_response(ok=False, description="Bad Request: message to edit not found"),
                tg_response({"message_id": 11}), tg_response(True)]):
            self.store.save({"version": 1})
        self.assertEqual((self.store.message_id, self.store.pinned), (11, True))

    def test_errors_never_contain_the_token(self):
        import requests as real_requests
        with mock.patch("paper_store.requests.post",
                        side_effect=real_requests.ConnectionError(f"https://api.telegram.org/bot{TOKEN}/getChat")):
            with self.assertRaises(paper_store.StoreError) as ctx:
                self.store.load()
        self.assertNotIn(TOKEN, str(ctx.exception))

    def test_file_store_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            store = paper_store.FileStore(os.path.join(d, "ledger.json"))
            self.assertIsNone(store.load())
            store.save({"version": 1, "name": "هل"})
            self.assertEqual(store.load(), {"version": 1, "name": "هل"})


class Stop(BaseException):
    pass


class RunLoopTests(unittest.TestCase):
    def setUp(self):
        pt._ledger = None
        self.addCleanup(setattr, pt, "_ledger", None)

    def run_once(self, store):
        with mock.patch("paper_trading.paper_store.default_store", return_value=store), \
                mock.patch("paper_trading.time.sleep", side_effect=Stop), \
                mock.patch("paper_trading.scan_once", return_value=(["رسالة"], False)), \
                mock.patch("paper_trading.alerts.send_alert") as send:
            with self.assertRaises(Stop):
                pt.run_forever()
        return send

    def test_new_ledger_is_announced_and_saved(self):
        store = mock.Mock(describe=lambda: "mock")
        store.load.return_value = None
        send = self.run_once(store)
        self.assertIn("بدأ التداول على الورق", send.call_args_list[0].args[0])
        self.assertEqual(send.call_args_list[1].args[0], "رسالة")
        store.save.assert_called_once()

    def test_an_unreadable_ledger_is_never_overwritten(self):
        store = mock.Mock(describe=lambda: "mock")
        store.load.side_effect = paper_store.StoreError("getChat: HTTP 502")
        send = self.run_once(store)
        store.save.assert_not_called()
        send.assert_not_called()
        self.assertIsNone(pt._ledger)
        self.assertIn("502", pt.STATE["last_error"])


class TelegramCommandTests(unittest.TestCase):
    def test_paper_command_replies_with_results(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "42"}), \
                mock.patch("telegram_actions.alerts.telegram_api", return_value=({}, None)) as api:
            pt._ledger = pt.new_ledger(NOW)
            self.addCleanup(setattr, pt, "_ledger", None)
            telegram_actions.handle_command("/paper")
        self.assertIn("التداول على الورق حتى الآن", api.call_args.args[1]["text"])

    def test_paper_command_when_turned_off(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "42",
                                          "PAPER_TRADING": "0"}):
            self.assertIn("متوقف", pt.status_text())


if __name__ == "__main__":
    unittest.main()
