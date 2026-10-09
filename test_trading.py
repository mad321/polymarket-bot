#!/usr/bin/env python3
"""
Tests for Data API v2 positions, selling and the Telegram sell flow
(no network: HTTP, Telegram and the Polymarket SDK client are mocked).

    python -m unittest test_trading.py
"""

import os
import time
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

os.environ["ENABLE_MONITOR"] = "0"

import positions
import trading
import telegram_actions
import polymarket_monitor as monitor
from polymarket import InsufficientLiquidityError

BOT_WALLET = "0xb0b0000000000000000000000000000000000001"
MAIN_WALLET = "0xa1a1000000000000000000000000000000000002"
ASSET = "75352308982559360810664047376087173948352198121226374582720762265018774664169"
KEY = trading.position_key(ASSET)
SETTINGS = ("WALLET_ADDRESS", "TRADING_WALLET", "TRADING_PRIVATE_KEY", "TRADING_ENABLED",
            "TRADING_DRY_RUN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
            "TRADING_WALLET_2", "TRADING_PRIVATE_KEY_2")


def env(**values):
    patched = {k: v for k, v in os.environ.items() if k not in SETTINGS}
    patched.update(values)
    return mock.patch.dict(os.environ, patched, clear=True)


def v2_row(token_id=ASSET, size=60.0, redeemable=False, **extra):
    row = {
        "token_id": token_id, "current_size": size, "avg_price": 0.46, "current_price": 0.25,
        "unrealized_pnl": -12.6, "percent_pnl": -45.66, "end_date": "2026-09-24",
        "slug": "saudi-sep-24", "event_slug": "saudi-event", "title": "Saudi Arabia action Sep 24?",
        "outcome": "No", "redeemable": redeemable, "status": "OPEN",
    }
    row.update(extra)
    return row


def page(rows, next_cursor=None):
    r = mock.Mock(ok=True)
    r.raise_for_status.return_value = None
    r.json.return_value = {"data": rows, "pagination": {"next_cursor": next_cursor}}
    return r


class PositionsV2Tests(unittest.TestCase):
    def test_maps_v2_fields_and_tags_the_wallet(self):
        with env(WALLET_ADDRESS=MAIN_WALLET), \
                mock.patch("positions.requests.get", return_value=page([v2_row()])) as get:
            rows, source, error = positions.load_positions()
        self.assertEqual(get.call_args.args[0], "https://data-api.polymarket.com/v2/positions")
        self.assertEqual((source, error), ("wallet", None))
        p = rows[0]
        self.assertEqual(p["id"], ASSET)
        self.assertEqual(p["wallet"], MAIN_WALLET)
        self.assertEqual((p["shares"], p["buy_price"], p["current_price"]), (60.0, 46.0, 25.0))
        self.assertEqual((p["pnl"], p["pnl_usd"], p["end_date"]), (-45.7, -12.6, "2026-09-24"))
        self.assertEqual(p["url"], "https://polymarket.com/event/saudi-event")

    def test_follows_pagination_and_skips_resolved_and_dust(self):
        pages = [page([v2_row(token_id="1")], next_cursor="abc"),
                 page([v2_row(token_id="2", redeemable=True), v2_row(token_id="3", size=0.2)])]
        with env(WALLET_ADDRESS=MAIN_WALLET), \
                mock.patch("positions.requests.get", side_effect=pages) as get:
            rows, _, _ = positions.load_positions()
        self.assertEqual(get.call_args_list[1].kwargs["params"]["cursor"], "abc")
        self.assertEqual([p["id"] for p in rows], ["1"])

    def test_watches_main_and_bot_wallets_once_each(self):
        with env(WALLET_ADDRESS=f"{MAIN_WALLET}, {BOT_WALLET.upper()}", TRADING_WALLET=BOT_WALLET):
            self.assertEqual(positions.watched_wallets(), [MAIN_WALLET, BOT_WALLET])

    def test_old_config_levels_skip_the_bot_wallet(self):
        # An old main-account entry (bought at 52¢, stop 30¢) must not turn a
        # new bot trade bought at 23¢ into an instant stop-loss alert.
        config = [{"slug": "saudi-sep-24", "name": "old trade", "stop_loss": 30, "take_profit": 85}]
        row = v2_row(avg_price=0.23, current_price=0.205)

        def fake_get(url, params, timeout):
            return page([row])
        with env(WALLET_ADDRESS=MAIN_WALLET, TRADING_WALLET=BOT_WALLET), \
                mock.patch("positions.load_config", return_value=config), \
                mock.patch("positions.requests.get", side_effect=fake_get):
            rows, _, _ = positions.load_positions()
        by_wallet = {p["wallet"]: p for p in rows}
        self.assertEqual((by_wallet[MAIN_WALLET]["stop_loss"], by_wallet[MAIN_WALLET]["name"]), (30, "old trade"))
        bot = by_wallet[BOT_WALLET]
        self.assertEqual((bot["stop_loss"], bot["take_profit"]), (16.1, 34.5))  # from its own 23¢
        self.assertNotEqual(bot["name"], "old trade")
        self.assertIsNone(monitor.level_hit(bot, 20.5))

    def test_config_entry_can_target_the_bot_wallet(self):
        config = [{"slug": "saudi-sep-24", "wallet": BOT_WALLET.upper(), "stop_loss": 20}]
        with env(TRADING_WALLET=BOT_WALLET):
            self.assertEqual(positions.overrides_for(config, BOT_WALLET)["saudi-sep-24"]["stop_loss"], 20)
            self.assertEqual(positions.overrides_for(config, MAIN_WALLET), {})

    def test_one_failing_wallet_keeps_the_other(self):
        def fake_get(url, params, timeout):
            if params["user"] == BOT_WALLET:
                raise ConnectionError("boom")
            return page([v2_row()])
        with env(WALLET_ADDRESS=MAIN_WALLET, TRADING_WALLET=BOT_WALLET), \
                mock.patch("positions.requests.get", side_effect=fake_get):
            rows, source, error = positions.load_positions()
        self.assertEqual((len(rows), source), (1, "wallet"))
        self.assertIn("boom", error)

    def test_every_wallet_failing_falls_back_to_config(self):
        with env(WALLET_ADDRESS=MAIN_WALLET), \
                mock.patch("positions.requests.get", side_effect=ConnectionError("down")), \
                mock.patch("positions.load_config", return_value=[]):
            rows, source, error = positions.load_positions()
        self.assertEqual((rows, source), ([], "config"))
        self.assertIn("down", error)


class FakeClient:
    """Stands in for polymarket.SecureClient."""

    def __init__(self, size="60.4567", price="0.24", min_size="5", order=None):
        self.wallet = BOT_WALLET
        self.wallet_type = "DEPOSIT_WALLET"
        self.size, self.price, self.min_size = Decimal(size), price, Decimal(min_size)
        self.order = order or SimpleNamespace(ok=True, status="matched", order_id="0xabc",
                                              making_amount=Decimal("60.45"),
                                              taking_amount=Decimal("14.51"))
        self.placed = []

    def list_positions(self, user, status):
        items = [SimpleNamespace(asset_id=ASSET, current_size=self.size, redeemable=False,
                                 current_price=Decimal("0.25"), title="Saudi Arabia action Sep 24?",
                                 slug="s", outcome="No")]
        return SimpleNamespace(iter_items=lambda: iter(items))

    def get_order_book(self, asset_id):
        return SimpleNamespace(min_order_size=self.min_size)

    def estimate_market_price(self, **kwargs):
        if self.price is None:
            raise InsufficientLiquidityError("no bids")
        return Decimal(self.price)

    def place_market_order(self, **kwargs):
        self.placed.append(kwargs)
        return self.order

    fills = ()
    order_status = SimpleNamespace(status="DELAYED", size_matched=Decimal(0))

    def list_account_trades(self, **kwargs):
        return SimpleNamespace(iter_items=lambda: iter(self.fills))

    def get_order(self, order_id):
        return self.order_status


class TradingTests(unittest.TestCase):
    def setUp(self):
        trading._client = FakeClient()
        trading.STATUS.update(last_order=None, client_error=None)

    def tearDown(self):
        trading._client = None

    def test_off_and_simulated_by_default(self):
        with env():
            self.assertFalse(trading.enabled())
            self.assertTrue(trading.dry_run())

    def test_quote_prices_the_whole_position(self):
        q = trading.quote(KEY)
        self.assertEqual(q["shares"], Decimal("60.45"))  # rounded down, never above holdings
        self.assertEqual(q["price"], Decimal("0.24"))
        self.assertEqual(q["proceeds"], Decimal("60.45") * Decimal("0.24"))

    def test_quote_refuses_below_the_market_minimum(self):
        trading._client = FakeClient(size="3")
        with self.assertRaisesRegex(trading.TradingError, "أقل كمية"):
            trading.quote(KEY)

    def test_quote_reports_no_buyers(self):
        trading._client = FakeClient(price=None)
        with self.assertRaisesRegex(trading.TradingError, "مشترون"):
            trading.quote(KEY)

    def test_unknown_position(self):
        with self.assertRaisesRegex(trading.TradingError, "لم أجد"):
            trading.quote("0000000000")

    def test_dry_run_places_nothing(self):
        with env():
            result = trading.sell(KEY, "60.45", "0.24")
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(trading._client.placed, [])
        self.assertEqual(trading.STATUS["last_order"], result)

    def test_live_sell_is_a_capped_fak_with_a_minimum_price(self):
        with env(TRADING_DRY_RUN="0"):
            result = trading.sell(KEY, "999", "0.24")
        order = trading._client.placed[0]
        self.assertEqual(order, {"asset_id": ASSET, "side": "SELL", "shares": "60.45",
                                 "min_price": "0.24", "order_type": "FAK"})
        self.assertTrue(result["ok"])
        self.assertEqual((result["sold"], result["received"]), ("60.45", "14.51"))

    def test_unfilled_sale_explains_in_arabic(self):
        trading._client = FakeClient(order=SimpleNamespace(ok=False, code="fak_not_filled", message="x"))
        with env(TRADING_DRY_RUN="0"):
            result = trading.sell(KEY, "60", "0.24")
        self.assertFalse(result["ok"])
        self.assertIn("السعر نزل", result["message"])

    def test_delayed_sale_reads_its_fills(self):
        trading._client.fills = (
            SimpleNamespace(taker_order_id="0xabc", size=Decimal("5"), price=Decimal("0.14")),
            SimpleNamespace(taker_order_id="0xother", size=Decimal("9"), price=Decimal("0.5")),
        )
        trading.STATUS["last_order"] = {"order_id": "0xabc", "status": "delayed"}
        outcome = trading.await_delayed_fill("0xabc", ASSET, time.time(), timeout=1, poll=0)
        self.assertEqual((outcome["status"], outcome["sold"], outcome["received"]),
                         ("matched", Decimal("5"), Decimal("0.70")))
        self.assertEqual(trading.STATUS["last_order"]["status"], "matched")

    def test_delayed_sale_that_ends_unfilled(self):
        trading._client.order_status = SimpleNamespace(status="CANCELED", size_matched=Decimal(0))
        outcome = trading.await_delayed_fill("0xabc", ASSET, time.time(), timeout=1, poll=0)
        self.assertEqual(outcome, {"status": "unfilled"})

    def test_delayed_sale_still_unknown_at_the_timeout(self):
        self.assertIsNone(trading.await_delayed_fill("0xabc", ASSET, time.time(), timeout=0.05, poll=0))

    def test_one_sale_at_a_time(self):
        with trading._sell_lock, self.assertRaisesRegex(trading.TradingError, "عملية بيع أخرى"):
            trading.sell(KEY, "60", "0.24")

    def test_refuses_a_key_that_does_not_own_the_wallet(self):
        trading._client = None
        throwaway = "0x" + "11" * 32
        with env(TRADING_PRIVATE_KEY=throwaway, TRADING_WALLET=BOT_WALLET), \
                mock.patch("polymarket.SecureClient.create") as create:
            with self.assertRaisesRegex(trading.TradingError, "لا يملك هذه المحفظة"):
                trading.list_positions()
        create.assert_not_called()

    def test_private_key_never_reaches_the_status(self):
        trading._client = None
        throwaway = "0x" + "22" * 32
        with env(TRADING_PRIVATE_KEY=throwaway, TRADING_WALLET=BOT_WALLET), \
                mock.patch("polymarket._internal.wallet.try_classify_wallet_type",
                           return_value="DEPOSIT_WALLET"), \
                mock.patch("polymarket.SecureClient.create",
                           side_effect=RuntimeError(f"bad key {throwaway}")):
            with self.assertRaises(trading.TradingError):
                trading.list_positions()
        self.assertNotIn("22" * 32, str(trading.status()))


class TelegramFlowTests(unittest.TestCase):
    def setUp(self):
        trading._client = FakeClient()
        self.calls = []
        patcher = mock.patch("telegram_actions.alerts.telegram_api",
                             side_effect=lambda method, payload, **kw: self.calls.append((method, payload)) or ({}, None))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        trading._client = None

    def settings(self, **extra):
        return env(TELEGRAM_CHAT_ID="42", TRADING_ENABLED="1", TRADING_WALLET=BOT_WALLET,
                   TRADING_PRIVATE_KEY="0x" + "33" * 32, **extra)

    def tap(self, data, chat="42"):
        return {"update_id": 1, "callback_query": {
            "id": "cb", "data": data,
            "message": {"message_id": 7, "chat": {"id": int(chat)}, "text": "tap"}}}

    def sent(self, method="sendMessage"):
        return [p for m, p in self.calls if m == method]

    def test_ignores_other_chats(self):
        before = telegram_actions.STATE["ignored_other_chat"]
        with self.settings():
            telegram_actions.handle_update(self.tap(f"s:{KEY}", chat="999"))
        self.assertEqual(self.calls, [])
        self.assertEqual(telegram_actions.STATE["ignored_other_chat"], before + 1)
        self.assertEqual(telegram_actions.STATE["last_ignored_chat_ends_with"], "999")

    def test_hidden_direction_marks_do_not_block_commands(self):
        # RTL keyboards and copy-paste can add marks to the text and to the id.
        with env(TELEGRAM_CHAT_ID="‏42‎"):
            telegram_actions.handle_update(
                {"update_id": 4, "message": {"chat": {"id": 42}, "text": "‏/start"}})
        self.assertIn("/positions", self.sent()[-1]["text"])
        self.assertEqual(self.sent()[-1]["chat_id"], "42")

    def test_plain_text_gets_the_help(self):
        with self.settings():
            telegram_actions.handle_update(
                {"update_id": 5, "message": {"chat": {"id": 42}, "text": "مرحبا"}})
        self.assertIn("/positions", self.sent()[-1]["text"])

    def test_sell_tap_asks_for_confirmation(self):
        with self.settings():
            telegram_actions.handle_update(self.tap(f"s:{KEY}"))
        message = self.sent()[-1]
        self.assertIn("وضع التجربة", message["text"])
        self.assertIn("24¢", message["text"])
        confirm = message["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        self.assertLessEqual(len(confirm.encode()), 64)
        self.assertTrue(confirm.startswith(f"c:{KEY}:0.24:60.45:"))

    def test_confirm_removes_buttons_then_sells(self):
        with self.settings(TRADING_DRY_RUN="0"), mock.patch("trading.sell", wraps=trading.sell) as sell:
            telegram_actions.handle_update(self.tap(f"c:{KEY}:0.24:60.45:{int(time.time())}"))
        methods = [m for m, _ in self.calls]
        self.assertLess(methods.index("editMessageText"), len(methods) - 1)  # closed before the result
        sell.assert_called_once_with(KEY, Decimal("60.45"), Decimal("0.24"))
        self.assertIn("✅ تم البيع", self.sent()[-1]["text"])
        self.assertIn("14.51", self.sent()[-1]["text"])

    def test_delayed_sale_gets_a_follow_up_message(self):
        trading._client = FakeClient(order=SimpleNamespace(
            ok=True, status="delayed", order_id="0xabc",
            making_amount=Decimal(0), taking_amount=Decimal(0)))

        class RunNow:  # run the follow-up thread inline
            def __init__(self, target, args, daemon):
                self.run = lambda: target(*args)

            def start(self):
                self.run()

        outcome = {"status": "matched", "sold": Decimal("5"), "received": Decimal("0.70")}
        with self.settings(TRADING_DRY_RUN="0"), \
                mock.patch("telegram_actions.threading.Thread", RunNow), \
                mock.patch("trading.await_delayed_fill", return_value=outcome) as wait:
            telegram_actions.handle_update(self.tap(f"c:{KEY}:0.14:5:{int(time.time())}"))
        self.assertEqual(wait.call_args.args[:2], ("0xabc", ASSET))
        first, follow_up = [p["text"] for p in self.sent()][-2:]
        self.assertIn("سأرسل لك النتيجة", first)
        self.assertIn("✅ تم البيع", follow_up)
        self.assertIn("$0.70", follow_up)

    def test_expired_confirmation_sells_nothing(self):
        stale = int(time.time()) - telegram_actions.CONFIRM_TTL - 5
        with self.settings(), mock.patch("trading.sell") as sell:
            telegram_actions.handle_update(self.tap(f"c:{KEY}:0.24:60.45:{stale}"))
        sell.assert_not_called()
        self.assertIn("انتهت صلاحية", self.sent("editMessageText")[0]["text"])

    def test_disabled_trading_explains_how_to_enable(self):
        with env(TELEGRAM_CHAT_ID="42"), mock.patch("trading.sell") as sell:
            telegram_actions.handle_update(self.tap(f"c:{KEY}:0.24:60.45:{int(time.time())}"))
        sell.assert_not_called()
        self.assertIn("TRADING_ENABLED", self.sent()[-1]["text"])

    def test_network_failure_is_reported_not_swallowed(self):
        from polymarket import TransportError
        trading._client = FakeClient()
        trading._client.list_positions = mock.Mock(side_effect=TransportError("network down"))
        with self.settings():
            telegram_actions.handle_update(
                {"update_id": 3, "message": {"chat": {"id": 42}, "text": "/positions"}})
        self.assertIn("network down", self.sent()[-1]["text"])

    def test_unexpected_sell_error_says_to_check_before_retrying(self):
        with self.settings(), mock.patch("trading.sell", side_effect=RuntimeError("??")):
            telegram_actions.handle_update(self.tap(f"c:{KEY}:0.24:60.45:{int(time.time())}"))
        self.assertIn("تحقق من الصفقة", self.sent()[-1]["text"])

    def test_positions_command_lists_with_sell_buttons(self):
        with self.settings():
            telegram_actions.handle_update(
                {"update_id": 2, "message": {"chat": {"id": 42}, "text": "/positions"}})
        last = self.sent()[-1]
        self.assertIn("60.45", last["text"])
        self.assertEqual(last["reply_markup"]["inline_keyboard"][0][0]["callback_data"], f"s:{KEY}")


class MonitorButtonTests(unittest.TestCase):
    def run_check(self, wallet, **settings):
        pos = dict(id=ASSET, wallet=wallet, name="n", shares=60, current_price=25.0,
                   stop_loss=32.2, take_profit=69.0, pnl_usd=-12.6, url="u")
        with env(TRADING_WALLET=BOT_WALLET, **settings), \
                mock.patch.object(monitor, "load_positions", return_value=([pos], "wallet", None)), \
                mock.patch.object(monitor.alerts, "send_alert", return_value=True) as send:
            monitor.check_once({})
        return send.call_args

    def test_bot_wallet_alert_gets_a_sell_button_when_enabled(self):
        args = self.run_check(BOT_WALLET, TRADING_ENABLED="1").args
        self.assertIn("محفظة البوت", args[0])
        self.assertEqual(args[1]["inline_keyboard"][0][0]["callback_data"], f"s:{KEY}")

    def test_same_market_in_two_wallets_alerts_for_each(self):
        both = [dict(id=ASSET, wallet=w, name="n", shares=60, current_price=25.0,
                     stop_loss=32.2, take_profit=69.0) for w in (MAIN_WALLET, BOT_WALLET)]
        with env(TRADING_WALLET=BOT_WALLET), \
                mock.patch.object(monitor, "load_positions", return_value=(both, "wallet", None)), \
                mock.patch.object(monitor.alerts, "send_alert", return_value=True) as send:
            monitor.check_once({})
        self.assertEqual(send.call_count, 2)

    def test_no_button_when_disabled_or_for_other_wallets(self):
        self.assertIsNone(self.run_check(BOT_WALLET).args[1])
        self.assertIsNone(self.run_check(MAIN_WALLET, TRADING_ENABLED="1").args[1])



class SecondWalletTests(unittest.TestCase):
    """TRADING_WALLET_2: selling from a second wallet, e.g. the main account."""

    KEY_2 = "0x" + "44" * 32

    def setUp(self):
        trading._client = FakeClient()
        main = FakeClient(order=SimpleNamespace(ok=True, status="matched", order_id="0xmain",
                                                making_amount=Decimal("60.45"), taking_amount=Decimal("14.51")))
        main.wallet = MAIN_WALLET
        trading._client_2 = main
        self.calls = []
        patcher = mock.patch("telegram_actions.alerts.telegram_api",
                             side_effect=lambda method, payload, **kw: self.calls.append((method, payload)) or ({}, None))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        trading._client = trading._client_2 = None

    def both(self, **extra):
        settings = dict(TELEGRAM_CHAT_ID="42", TRADING_ENABLED="1", TRADING_DRY_RUN="0",
                        TRADING_WALLET=BOT_WALLET, TRADING_PRIVATE_KEY="0x" + "33" * 32,
                        TRADING_WALLET_2=MAIN_WALLET.upper(), TRADING_PRIVATE_KEY_2=self.KEY_2)
        settings.update(extra)
        return env(**settings)

    def test_the_second_wallet_counts_only_with_its_key(self):
        with env(TRADING_ENABLED="1", TRADING_WALLET=BOT_WALLET, TRADING_WALLET_2=MAIN_WALLET):
            self.assertEqual(trading.second_wallet(), "")
            self.assertFalse(trading.can_sell(MAIN_WALLET))
            self.assertTrue(trading.can_sell(BOT_WALLET))
        with self.both():
            self.assertEqual(trading.second_wallet(), MAIN_WALLET)
            self.assertTrue(trading.can_sell(MAIN_WALLET))
        with self.both(TRADING_ENABLED="0"):
            self.assertFalse(trading.can_sell(MAIN_WALLET))

    def test_lists_both_wallets_with_distinct_keys(self):
        with self.both():
            rows = trading.list_positions()
        self.assertEqual([r["second"] for r in rows], [False, True])
        self.assertEqual(rows[0]["key"], KEY)
        with self.both():
            self.assertEqual(rows[1]["key"], trading.position_key(ASSET, MAIN_WALLET))
        self.assertNotEqual(rows[0]["key"], rows[1]["key"])

    def test_sells_from_the_wallet_that_holds_the_position(self):
        with self.both():
            key_2 = trading.position_key(ASSET, MAIN_WALLET)
            result = trading.sell(key_2, "60", "0.24")
        self.assertEqual((result["order_id"], result["second"]), ("0xmain", True))
        self.assertEqual(trading._client.placed, [])
        self.assertEqual(len(trading._client_2.placed), 1)

    def test_a_broken_second_wallet_does_not_block_the_bot_wallet(self):
        trading._client_2 = None
        with self.both(), mock.patch("polymarket.SecureClient.create") as create:
            rows = trading.list_positions()  # the throwaway key 0x44.. does not own MAIN_WALLET
        create.assert_not_called()
        self.assertEqual([r["second"] for r in rows], [False])
        self.assertIn("TRADING_WALLET_2", trading.status()["wallet_2"]["client_error"])

    def test_both_keys_are_redacted(self):
        with self.both():
            self.assertNotIn("44" * 32, trading._redact(f"boom {self.KEY_2}"))

    def test_positions_command_labels_each_wallet(self):
        with self.both():
            telegram_actions.handle_command("/positions")
        texts = [p["text"] for m, p in self.calls if m == "sendMessage"]
        self.assertIn("الصفقات التي يستطيع البوت بيعها: 2", texts[0])
        self.assertIn("المحفظة: محفظة البوت", texts[1])
        self.assertIn("المحفظة: المحفظة الثانية", texts[2])
        buttons = [p["reply_markup"]["inline_keyboard"][0][0]["callback_data"] for m, p in self.calls
                   if m == "sendMessage" and p.get("reply_markup")]
        self.assertEqual(len(set(buttons)), 2)

    def test_main_wallet_alert_gets_a_button_once_its_key_is_set(self):
        pos = dict(id=ASSET, wallet=MAIN_WALLET, name="n", shares=60, current_price=25.0,
                   stop_loss=32.2, take_profit=69.0, pnl_usd=-12.6, url="u")
        with self.both(), \
                mock.patch.object(monitor, "load_positions", return_value=([pos], "wallet", None)), \
                mock.patch.object(monitor.alerts, "send_alert", return_value=True) as send, \
                mock.patch.object(monitor.stop_review, "record"), mock.patch.object(monitor.exposure, "check"):
            monitor.check_once({})
            expected = f"s:{trading.position_key(ASSET, MAIN_WALLET)}"
        self.assertEqual(send.call_args.args[1]["inline_keyboard"][0][0]["callback_data"], expected)

    def test_pasted_junk_is_cleaned_and_bad_keys_are_explained(self):
        clean = "ab" * 32
        with env(TRADING_PRIVATE_KEY_2=f' "0x{clean}"\u200f\n'):
            self.assertEqual(trading._env("TRADING_PRIVATE_KEY_2"), f"0x{clean}")
            self.assertIsNone(trading.key_problem("TRADING_PRIVATE_KEY_2"))
        with env(TRADING_PRIVATE_KEY_2="0x" + "zz" * 32):
            self.assertIn("أحرف لا تكون في المفتاح", trading.key_problem("TRADING_PRIVATE_KEY_2"))
        with env(TRADING_PRIVATE_KEY_2="ab" * 20):
            self.assertIn("طوله 40", trading.key_problem("TRADING_PRIVATE_KEY_2"))
        with env(TRADING_PRIVATE_KEY_2=" ".join(["word"] * 12)):
            self.assertIn("لا الكلمات الـ 12", trading.key_problem("TRADING_PRIVATE_KEY_2"))

    def test_positions_command_says_why_the_second_wallet_is_missing(self):
        trading._client_2 = None
        with self.both(TRADING_PRIVATE_KEY_2="0x" + "zz" * 32):
            telegram_actions.handle_command("/positions")
        texts = [p["text"] for m, p in self.calls if m == "sendMessage"]
        self.assertIn("المحفظة الثانية لا تعمل", texts[0])
        self.assertIn("أحرف لا تكون في المفتاح", texts[0])
        self.assertNotIn("zz" * 32, " ".join(texts))

    def test_the_second_wallet_is_watched(self):
        with env(WALLET_ADDRESS=MAIN_WALLET, TRADING_WALLET=BOT_WALLET, TRADING_WALLET_2=MAIN_WALLET.upper()):
            self.assertEqual(positions.watched_wallets(), [MAIN_WALLET, BOT_WALLET])


if __name__ == "__main__":
    unittest.main()
