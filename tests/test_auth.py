"""Email activation is fail-closed; SMTP is always mocked in this suite."""
import json
import sqlite3
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import ExitStack
from http.server import ThreadingHTTPServer
from unittest.mock import MagicMock, patch

from hpoint import billing, database, services, web


class EmailActivation(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.db = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        for module in (database, services, billing, web):
            self.stack.enter_context(patch.object(module, "db", self.db))
        database.init_db()
        self.delivered = []
        self.configured = self.stack.enter_context(patch.object(web, "email_delivery_configured", return_value=True))
        self.send = self.stack.enter_context(patch.object(web, "send_email_verification_code", side_effect=self.capture_mail))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=3)
        self.server.server_close()
        self.stack.close()
        self.db.close()

    def capture_mail(self, address, code):
        self.delivered.append((address, code))
        return True

    def request(self, route, payload=None, cookie=""):
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        request = urllib.request.Request(self.base + route, data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
        try:
            response = urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response), response.headers

    def register(self):
        return self.request("/api/auth/register", {"name": "Pending User", "email": "pending@example.test", "password": "Ab1234", "password_confirm": "Ab1234"})

    def cookie(self, headers, name):
        return next(value.split(";", 1)[0] for value in headers.get_all("Set-Cookie", []) if value.startswith(name + "="))

    def test_six_character_password_and_validation_boundaries(self):
        self.assertIsNone(web.password_error("Ab1234"))
        self.assertIsNotNone(web.password_error("Ab123"))
        self.assertIsNotNone(web.password_error("abcdef"))
        self.assertIsNotNone(web.password_error("Ab1" + "x" * 254))
        self.assertIsNone(web.password_error("Ab1" + "x" * 253))

    def test_mail_not_configured_creates_neither_account_nor_session(self):
        self.configured.return_value = False
        status, result, headers = self.register()
        self.assertEqual(status, 503)
        self.assertFalse(result["ok"])
        self.assertFalse(headers.get_all("Set-Cookie"))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)
        self.send.assert_not_called()

    def test_mail_failure_never_logs_in_and_retry_can_recover(self):
        self.send.side_effect = None
        self.send.return_value = False
        for route, payload in (("/api/auth/register", {"name": "Pending User", "email": "pending@example.test", "password": "Ab1234", "password_confirm": "Ab1234"}),
                               ("/api/auth/login", {"email": "pending@example.test", "password": "Ab1234"})):
            status, result, headers = self.request(route, payload)
            self.assertEqual(status, 503)
            self.assertFalse(result["ok"])
            self.assertFalse(headers.get_all("Set-Cookie"))
            self.assertEqual(self.db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)
            self.assertEqual(self.db.execute("SELECT COUNT(*) FROM email_verification_codes").fetchone()[0], 0)
        self.assertFalse(database.get_user_by_email("pending@example.test")["email_verified"])
        self.send.side_effect = self.capture_mail
        status, result, headers = self.register()
        self.assertEqual(status, 200)
        self.assertTrue(result["verification_required"])
        self.assertTrue(self.cookie(headers, "hpoint_verification"))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)

    def test_confirmation_is_required_even_when_modal_is_closed_or_token_renamed(self):
        status, result, headers = self.register()
        self.assertEqual(status, 200)
        self.assertTrue(result["verification_required"])
        self.assertEqual(self.cookie(headers, "hpoint_session"), "hpoint_session=")
        pending = self.cookie(headers, "hpoint_verification")
        for cookie in (pending, pending.replace("hpoint_verification=", "hpoint_session=")):
            for route in ("/api/me", "/api/dashboard", "/api/sync", "/api/wallet", "/api/requests"):
                self.assertEqual(self.request(route, cookie=cookie)[0], 401, route)
            self.assertEqual(self.request("/api/games/start", {"game_code": "crossing"}, cookie)[0], 401)
        self.assertEqual(self.request("/api/auth/email/verify", {"code": "000000"}, pending)[0], 400)
        self.assertFalse(database.get_user_by_email("pending@example.test")["email_verified"])
        status, result, confirmed_headers = self.request("/api/auth/email/verify", {"code": self.delivered[-1][1]}, pending)
        self.assertEqual(status, 200)
        session = self.cookie(confirmed_headers, "hpoint_session")
        self.assertEqual(self.request("/api/me", cookie=session)[0], 200)
        self.assertEqual(self.request("/api/auth/email/verify", {"code": self.delivered[-1][1]}, session)[0], 400)
        self.assertEqual(self.request("/api/auth/email/resend", {}, pending)[0], 401)

    def test_legacy_unconfirmed_session_is_blocked_and_revoked_after_confirmation(self):
        uid = database.create_web_user("Legacy", "legacy@example.test", web.ph("Ab1234"))
        legacy = "hpoint_session=" + web.new_sess(uid, "old-device")
        self.assertEqual(self.request("/api/me", cookie=legacy)[0], 401)
        status, result, headers = self.request("/api/auth/login", {"email": "legacy@example.test", "password": "Ab1234"})
        self.assertEqual(status, 200)
        self.assertTrue(result["verification_required"])
        pending = self.cookie(headers, "hpoint_verification")
        status, _, confirmed_headers = self.request("/api/auth/email/verify", {"code": self.delivered[-1][1]}, pending)
        self.assertEqual(status, 200)
        self.assertEqual(self.request("/api/me", cookie=legacy)[0], 401)
        self.assertEqual(self.request("/api/me", cookie=self.cookie(confirmed_headers, "hpoint_session"))[0], 200)

    def test_expired_code_is_rejected_and_resend_recovers(self):
        _, _, headers = self.register()
        pending = self.cookie(headers, "hpoint_verification")
        old_code = self.delivered[-1][1]
        self.db.execute("UPDATE email_verification_codes SET expires_at='2000-01-01T00:00:00+00:00'")
        self.assertEqual(self.request("/api/auth/email/verify", {"code": old_code}, pending)[0], 400)
        status, _, new_headers = self.request("/api/auth/email/resend", {}, pending)
        self.assertEqual(status, 200)
        pending = self.cookie(new_headers, "hpoint_verification")
        self.assertEqual(self.request("/api/auth/email/verify", {"code": self.delivered[-1][1]}, pending)[0], 200)

    def test_expired_pending_session_and_logout_cannot_resume_confirmation(self):
        _, _, headers = self.register()
        pending = self.cookie(headers, "hpoint_verification")
        self.db.execute("UPDATE sessions SET expires_at='2000-01-01T00:00:00+00:00'")
        self.assertEqual(self.request("/api/auth/email/verify", {"code": self.delivered[-1][1]}, pending)[0], 401)
        _, _, headers = self.request("/api/auth/login", {"email": "pending@example.test", "password": "Ab1234"})
        pending = self.cookie(headers, "hpoint_verification")
        self.assertEqual(self.request("/api/auth/logout", {}, pending)[0], 200)
        self.assertEqual(self.request("/api/auth/email/resend", {}, pending)[0], 401)

    def test_telegram_session_keeps_working_without_email_and_cannot_be_unlinked_unsafely(self):
        database.create_user(42, "Telegram", tg_user_id=42)
        session = "hpoint_session=" + web.new_sess(42)
        self.assertEqual(self.request("/api/me", cookie=session)[0], 200)
        self.assertEqual(self.request("/api/profile/telegram/unlink", {}, session)[0], 409)
        self.assertEqual(database.get_user(42)["tg_user_id"], 42)

    def test_profile_switch_does_not_bypass_confirmation(self):
        database.create_user(42, "Telegram", tg_user_id=42)
        uid = database.create_web_user("Pending", "switch@example.test", web.ph("Ab1234"))
        first = web.new_sess(42, "device-test")
        web.new_sess(uid, "device-test")
        cookie = "hpoint_session=" + first + "; hpoint_device=device-test"
        self.assertEqual(self.request("/api/profiles/switch", {"user_id": uid}, cookie)[0], 403)
        self.assertEqual(self.request("/api/me", cookie=cookie)[0], 200)


class MailTransport(unittest.TestCase):
    def client(self):
        client = MagicMock()
        client.__enter__.return_value = client
        return client

    def send(self, smtp):
        with patch.object(web, "email_delivery_configured", return_value=True), patch.object(web, "SMTP_USE_SSL", False), patch.object(web, "SMTP_USE_TLS", True), patch.object(web.smtplib, "SMTP", smtp):
            return web.send_email_verification_code("only-a-mock@example.test", "123456")

    def test_handshake_timeout_retries_before_sending_and_sends_once(self):
        first, second = self.client(), self.client()
        first.starttls.side_effect = TimeoutError("simulated handshake timeout")
        smtp = MagicMock(side_effect=[first, second])
        self.assertTrue(self.send(smtp))
        first.send_message.assert_not_called()
        second.send_message.assert_called_once()
        self.assertEqual(smtp.call_count, 2)

    def test_uncertain_data_delivery_is_not_retried(self):
        client = self.client()
        client.send_message.side_effect = TimeoutError("simulated DATA timeout")
        smtp = MagicMock(return_value=client)
        with self.assertLogs(level="ERROR"):
            self.assertFalse(self.send(smtp))
        self.assertEqual(smtp.call_count, 1)
        client.send_message.assert_called_once()

    def test_quit_timeout_after_acceptance_is_still_success(self):
        client = self.client()
        client.__exit__.side_effect = web.smtplib.SMTPServerDisconnected("simulated QUIT disconnect")
        smtp = MagicMock(return_value=client)
        self.assertTrue(self.send(smtp))
        self.assertEqual(smtp.call_count, 1)


if __name__ == "__main__":
    unittest.main()
