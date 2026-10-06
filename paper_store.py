"""
Paper trading ledger storage
============================
Render's disk is wiped on every deploy and restart, so the paper-trading
ledger is kept as a JSON file pinned in the bot's Telegram chat: no extra
account or secret is needed. The bot edits that one message in place on every
change (silently), and reads it back from the chat's pinned message on start.

Set PAPER_LEDGER_FILE to keep the ledger in a local file instead (local runs).

If the pinned message is deleted or another message is pinned after it, the
bot no longer finds the ledger and starts a new one, and says so in Telegram.
"""

import os
import json
import logging

import requests

logger = logging.getLogger(__name__)

FILE_NAME = "paper_trades.json"
CAPTION = ("📒 سجل التداول على الورق (بدون مال حقيقي). "
           "لا تحذف هذه الرسالة ولا تلغِ تثبيتها: البوت يحفظ فيها صفقاته الورقية.")


class StoreError(Exception):
    """The ledger could not be read or written. Never contains the bot token."""


class FileStore:
    def __init__(self, path):
        self.path = path

    def describe(self):
        return f"file {os.path.basename(self.path)}"

    def load(self):
        """The saved ledger, or None if there is none yet."""
        if not os.path.exists(self.path):
            return None
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError) as e:
            raise StoreError(f"cannot read {self.path}: {e}") from None

    def save(self, ledger):
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(ledger, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)


class TelegramStore:
    def __init__(self):
        self.message_id = None
        self.pinned = False

    def describe(self):
        return "telegram pinned message"

    @staticmethod
    def _token():
        return (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()

    @staticmethod
    def _chat_id():
        return (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()

    def _call(self, method, data=None, files=None, timeout=20):
        token = self._token()
        try:
            r = requests.post(f"https://api.telegram.org/bot{token}/{method}",
                              data=data, files=files, timeout=timeout)
            try:
                body = r.json()
            except ValueError:
                body = {}
            if r.ok and body.get("ok"):
                return body.get("result")
            error = f"{method}: HTTP {r.status_code}: {body.get('description') or r.text[:200]}"
        except requests.RequestException as e:
            error = f"{method}: {e}"
        raise StoreError(error.replace(token, "***") if token else error)

    def load(self):
        chat = self._call("getChat", {"chat_id": self._chat_id()})
        pinned = chat.get("pinned_message") or {}
        document = pinned.get("document") or {}
        if document.get("file_name") != FILE_NAME or not (pinned.get("from") or {}).get("is_bot"):
            return None
        info = self._call("getFile", {"file_id": document["file_id"]})
        token = self._token()
        try:
            r = requests.get(f"https://api.telegram.org/file/bot{token}/{info['file_path']}", timeout=20)
            r.raise_for_status()
            ledger = r.json()
        except (requests.RequestException, ValueError) as e:
            error = f"download ledger: {e}"
            raise StoreError(error.replace(token, "***") if token else error) from None
        self.message_id, self.pinned = pinned["message_id"], True
        return ledger

    def save(self, ledger):
        content = json.dumps(ledger, ensure_ascii=False, indent=1).encode()
        if self.message_id is not None:
            media = {"type": "document", "media": "attach://ledger", "caption": CAPTION}
            try:
                self._call("editMessageMedia",
                           {"chat_id": self._chat_id(), "message_id": self.message_id,
                            "media": json.dumps(media, ensure_ascii=False)},
                           {"ledger": (FILE_NAME, content, "application/json")})
            except StoreError as e:
                if "not found" in str(e) or "MESSAGE_ID_INVALID" in str(e):
                    logger.warning(f"[PAPER] ledger message is gone, posting a new one: {e}")
                    self.message_id = None
                elif "not modified" not in str(e):
                    raise
        if self.message_id is None:
            sent = self._call("sendDocument",
                              {"chat_id": self._chat_id(), "caption": CAPTION, "disable_notification": "true"},
                              {"document": (FILE_NAME, content, "application/json")})
            self.message_id, self.pinned = sent["message_id"], False
        if not self.pinned:  # retried on the next save if pinning failed
            self._call("pinChatMessage", {"chat_id": self._chat_id(), "message_id": self.message_id,
                                          "disable_notification": "true"})
            self.pinned = True


def default_store():
    path = (os.environ.get("PAPER_LEDGER_FILE") or "").strip()
    return FileStore(path) if path else TelegramStore()
