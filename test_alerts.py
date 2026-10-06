#!/usr/bin/env python3
"""
Tests for alert delivery and the monitor loop (no network: HTTP is mocked).

    python -m unittest test_alerts.py
"""

import json
import os
import unittest
from unittest import mock

os.environ["ENABLE_MONITOR"] = "0"  # importing polymarket_bot must not start the thread

import alerts
import polymarket_monitor as monitor

TOKEN = "123456:SECRET-TOKEN"
ALERT_ENV = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
             "WHATSAPP_TOKEN", "PHONE_NUMBER_ID", "RECIPIENT_PHONE")


def env(**values):
    """Patch os.environ so only the given alert settings are set."""
    patched = {k: v for k, v in os.environ.items() if k not in ALERT_ENV}
    patched.update(values)
    return mock.patch.dict(os.environ, patched, clear=True)


def response(status=200, body=None):
    r = mock.Mock()
    r.status_code = status
    r.ok = status < 400
    r.json.return_value = body if body is not None else {}
    r.text = json.dumps(body)
    return r


POSITION = {
    "id": "tok-1",
    "name": "Saudi Arabia military action against Yemen on September 24? — No",
    "url": "https://polymarket.com/event/x",
    "shares": 60.0,
    "buy_price": 46.0,
    "current_price": 25.0,
    "stop_loss": 32.2,
    "take_profit": 69.0,
    "pnl_usd": -12.6,
}


class SendAlertTests(unittest.TestCase):
    def setUp(self):
        alerts._status.clear()

    def test_no_channel_configured_sends_nothing(self):
        with env(), mock.patch("alerts.requests.post") as post:
            self.assertFalse(alerts.send_alert("hi"))
        post.assert_not_called()

    def test_telegram_success(self):
        with env(TELEGRAM_BOT_TOKEN=TOKEN, TELEGRAM_CHAT_ID="42"), \
                mock.patch("alerts.requests.post", return_value=response(200, {"ok": True})) as post:
            self.assertTrue(alerts.send_alert("hi"))
            status = alerts.status()["telegram"]
        url, kwargs = post.call_args.args[0], post.call_args.kwargs
        self.assertEqual(url, f"https://api.telegram.org/bot{TOKEN}/sendMessage")
        self.assertEqual(kwargs["json"]["chat_id"], "42")
        self.assertEqual(kwargs["json"]["text"], "hi")
        self.assertEqual(status["accepted"], 1)
        self.assertTrue(status["configured"])

    def test_telegram_api_error_is_recorded(self):
        body = {"ok": False, "description": "Bad Request: chat not found"}
        with env(TELEGRAM_BOT_TOKEN=TOKEN, TELEGRAM_CHAT_ID="42"), \
                mock.patch("alerts.requests.post", return_value=response(400, body)):
            self.assertFalse(alerts.send_alert("hi"))
            status = alerts.status()["telegram"]
        self.assertEqual(status["failed"], 1)
        self.assertIn("chat not found", status["last_error"])

    def test_token_never_leaks_from_connection_errors(self):
        error = ConnectionError(f"Max retries exceeded with url: /bot{TOKEN}/sendMessage")
        with env(TELEGRAM_BOT_TOKEN=TOKEN, TELEGRAM_CHAT_ID="42"), \
                mock.patch("alerts.requests.post", side_effect=error), \
                self.assertLogs("alerts", level="ERROR") as logs:
            alerts.send_alert("hi")
            dumped = json.dumps(alerts.status())
        self.assertNotIn(TOKEN, dumped)
        self.assertNotIn(TOKEN, "\n".join(logs.output))
        self.assertIn("/bot***/sendMessage", dumped)

    def test_whatsapp_error_code_is_recorded(self):
        body = {"error": {"code": 190, "message": "Error validating access token"}}
        with env(WHATSAPP_TOKEN="wa-secret", PHONE_NUMBER_ID="1", RECIPIENT_PHONE="9665"), \
                mock.patch("alerts.requests.post", return_value=response(401, body)):
            self.assertFalse(alerts.send_alert("hi"))
            status = alerts.status()["whatsapp"]
        self.assertIn("[190]", status["last_error"])

    def test_sends_to_every_configured_channel(self):
        with env(TELEGRAM_BOT_TOKEN=TOKEN, TELEGRAM_CHAT_ID="42", WHATSAPP_TOKEN="wa",
                 PHONE_NUMBER_ID="1", RECIPIENT_PHONE="9665"), \
                mock.patch("alerts.requests.post",
                           side_effect=[response(200, {"ok": True}), response(500, {})]) as post:
            self.assertTrue(alerts.send_alert("hi"))  # Telegram accepted it
        self.assertEqual(post.call_count, 2)

    def test_status_lists_missing_settings_without_values(self):
        with env(TELEGRAM_BOT_TOKEN=TOKEN):
            status = alerts.status()
        self.assertFalse(status["telegram"]["configured"])
        self.assertEqual(status["telegram"]["missing_settings"], ["TELEGRAM_CHAT_ID"])
        self.assertNotIn(TOKEN, json.dumps(status))


class MonitorTests(unittest.TestCase):
    def test_format_alert(self):
        msg = monitor.format_alert(POSITION, 25.0, "stop_loss")
        self.assertIn("وقف الخسارة", msg)
        self.assertIn(POSITION["name"], msg)
        self.assertIn("25.0¢ (الحد: 32.2¢)", msg)
        self.assertIn("‎-$12.60", msg)
        self.assertIn(POSITION["url"], msg)

    def test_level_hit(self):
        self.assertEqual(monitor.level_hit(POSITION, 25.0), "stop_loss")
        self.assertEqual(monitor.level_hit(POSITION, 70.0), "take_profit")
        self.assertIsNone(monitor.level_hit(POSITION, 50.0))

    def run_check(self, next_alert_at, now, sent=True, positions=(POSITION,)):
        with mock.patch.object(monitor, "load_positions",
                               return_value=(list(positions), "wallet", None)), \
                mock.patch.object(monitor.time, "time", return_value=now), \
                mock.patch.object(monitor.alerts, "send_alert", return_value=sent) as send:
            monitor.check_once(next_alert_at)
        return send

    def test_alerts_once_per_cooldown(self):
        next_alert_at = {}
        self.assertEqual(self.run_check(next_alert_at, 1000).call_count, 1)
        self.assertEqual(self.run_check(next_alert_at, 1030).call_count, 0)
        later = 1000 + monitor.ALERT_COOLDOWN
        self.assertEqual(self.run_check(next_alert_at, later).call_count, 1)
        self.assertEqual(monitor.STATE["past_level"], 1)

    def test_failed_alert_is_retried_sooner(self):
        next_alert_at = {}
        self.run_check(next_alert_at, 1000, sent=False)
        self.assertEqual(next_alert_at[":tok-1"], 1000 + monitor.RETRY_AFTER_FAILURE)

    def test_position_inside_its_levels_is_quiet(self):
        inside = dict(POSITION, current_price=50.0)
        self.assertEqual(self.run_check({}, 1000, positions=[inside]).call_count, 0)


class StatusEndpointTests(unittest.TestCase):
    def test_endpoint_reports_monitor_and_channels(self):
        import polymarket_bot
        with env(TELEGRAM_BOT_TOKEN=TOKEN, TELEGRAM_CHAT_ID="42"):
            resp = polymarket_bot.app.test_client().get("/api/alerts/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("running", data["monitor"])
        self.assertTrue(data["channels"]["telegram"]["configured"])
        self.assertNotIn(TOKEN, resp.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
