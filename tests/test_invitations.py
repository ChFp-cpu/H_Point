"""Invitation cancellation uses the same state on the website and Telegram."""
import json
import sqlite3
import threading
import tempfile
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, patch

from hpoint import database, handlers, services, web
from hpoint.keyboards import candidates_navigation_kb, helper_offer_kb


class InvitationData:
    def prepare(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.patches = [patch.object(module, "db", self.db) for module in (database, services, web, handlers)]
        for item in self.patches:
            item.start()
        database.init_db()
        for uid in (1, 2, 3, 4):
            database.create_user(uid, f"User {uid}", tg_user_id=uid, web_verified=True)
            if uid != 1:
                services.add_to_queue(uid)
        self.rid = services.create_request(1, {"what": "Компьютер", "category": "tech", "place": "центр", "time_needed": "сегодня", "urgency": "обычная", "details": "test"})

    def close(self):
        for item in reversed(self.patches):
            item.stop()
        self.db.close()

    def current(self):
        return services.get_current_helper_offer(self.rid)


class InvitationCore(InvitationData, unittest.TestCase):
    def setUp(self):
        self.prepare()

    def tearDown(self):
        self.close()

    def test_targeted_application_is_distinct_from_queue_and_prioritized(self):
        self.assertEqual(services.get_request_applications(1), [])
        services.set_helper_categories(2, ["shopping"])
        self.assertEqual(services.apply_to_request(self.rid, 2), "created")
        token = self.db.execute("SELECT offer_token FROM request_candidates WHERE request_id=? AND candidate_id=2", (self.rid,)).fetchone()["offer_token"]
        self.assertEqual(services.apply_to_request(self.rid, 2), "applied")
        self.assertEqual(len(services.get_request_applications(1)), 1)
        self.assertEqual(services.get_request_applications(3), [])
        self.assertEqual(services.get_helper_applications(2)[0]["application_token"], token)
        match = services.smart_match(self.rid)[0]
        self.assertEqual(match["user_id"], 2); self.assertTrue(match["applied"])
        self.assertEqual(services.get_request_applications(1)[0]["application_token"], token)
        self.assertEqual(database.get_request(self.rid)["status"], "open")
        self.assertIsNone(database.get_request(self.rid)["helper_id"])
        self.assertTrue(services.offer_helper(self.rid, 2))
        self.assertFalse(services.cancel_request_application(self.rid, 2, 2, token))
        self.assertEqual(services.apply_to_request(self.rid, 2), "offered")

    def test_application_can_be_cancelled_by_either_party_but_not_a_stranger(self):
        self.assertEqual(services.apply_to_request(self.rid, 2), "created")
        token = services.get_helper_applications(2)[0]["application_token"]
        self.assertFalse(services.cancel_request_application(self.rid, 2, 4, token))
        self.assertFalse(services.cancel_request_application(self.rid, 2, 1, "old"))
        self.assertTrue(services.cancel_request_application(self.rid, 2, 2, token))
        self.assertEqual(services.get_request_applications(1), [])
        self.assertEqual(services.apply_to_request(self.rid, 2), "created")
        newer = services.get_helper_applications(2)[0]["application_token"]
        self.assertNotEqual(token, newer)
        self.assertFalse(services.cancel_request_application(self.rid, 2, 1, token))
        self.assertTrue(services.cancel_request_application(self.rid, 2, 1, newer))
        self.assertEqual(services.get_helper_applications(2), [])
        self.assertEqual(database.get_request(self.rid)["status"], "open")
        self.assertEqual(services.apply_to_request(self.rid, 1), "unavailable")
        services.apply_to_request(self.rid, 3);services.remove_from_queue(3)
        self.assertEqual(services.get_request_applications(1), [])

    def test_withdraw_is_owner_only_and_does_not_cancel_request(self):
        self.assertTrue(services.offer_helper(self.rid, 2))
        token = self.current()["offer_token"]
        balances = [database.get_user(uid)["balance"] for uid in (1, 2)]
        self.assertFalse(services.withdraw_helper_offer(self.rid, 2, 2, token))
        self.assertFalse(services.withdraw_helper_offer(self.rid, 4, 2, token))
        self.assertFalse(services.withdraw_helper_offer(self.rid, 1, 3, token))
        self.assertFalse(services.withdraw_helper_offer(self.rid, 1, 2, "stale"))
        self.assertTrue(services.withdraw_helper_offer(self.rid, 1, 2, token))
        self.assertFalse(services.withdraw_helper_offer(self.rid, 1, 2, token))
        self.assertIsNone(self.current())
        self.assertEqual(database.get_request(self.rid)["status"], "open")
        self.assertIsNone(database.get_request(self.rid)["helper_id"])
        self.assertTrue(services.is_in_queue(2))
        self.assertEqual([database.get_user(uid)["balance"] for uid in (1, 2)], balances)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM chats").fetchone()["n"], 0)
        self.assertIn(2, [row["user_id"] for row in services.smart_match(self.rid)])

    def test_old_buttons_cannot_cancel_or_accept_a_new_invitation(self):
        self.assertTrue(services.offer_helper(self.rid, 2))
        old = self.current()["offer_token"]
        self.assertTrue(services.withdraw_helper_offer(self.rid, 1, 2, old))
        self.assertFalse(services.respond_to_helper_offer(self.rid, 2, True, old))
        self.assertTrue(services.offer_helper(self.rid, 2))
        new = self.current()["offer_token"]
        self.assertNotEqual(old, new)
        self.assertFalse(services.withdraw_helper_offer(self.rid, 1, 2, old))
        self.assertFalse(services.respond_to_helper_offer(self.rid, 2, False, old))
        self.assertFalse(services.respond_to_helper_offer(self.rid, 2, True, ""))
        self.assertTrue(services.respond_to_helper_offer(self.rid, 2, True, new))
        self.assertFalse(services.withdraw_helper_offer(self.rid, 1, 2, new))
        self.assertEqual(database.get_request(self.rid)["status"], "in_progress")

    def test_pending_invite_does_not_hide_other_candidates(self):
        self.assertTrue(services.offer_helper(self.rid, 2))
        token = self.current()["offer_token"]
        self.assertEqual({row["user_id"] for row in services.smart_match(self.rid)}, {3, 4})
        self.assertEqual(self.current()["offer_token"], token)
        self.assertFalse(services.offer_helper(self.rid, 3))
        self.assertFalse(services.offer_helper(self.rid, 3, "stale"))
        self.assertTrue(services.offer_helper(self.rid, 3, token))
        self.assertEqual(self.current()["candidate_id"], 3)
        self.assertEqual(services.get_helper_offers(2), [])
        self.assertFalse(services.respond_to_helper_offer(self.rid, 2, True, token))

    def test_existing_legacy_invitation_remains_actionable(self):
        self.db.execute("INSERT INTO request_candidates(request_id,candidate_id,status) VALUES(?,2,'offered')", (self.rid,))
        database.init_db()
        self.assertIsNone(self.current()["offer_token"])
        self.assertTrue(services.withdraw_helper_offer(self.rid, 1, 2, ""))
        self.assertTrue(services.offer_helper(self.rid, 2))
        self.assertFalse(services.respond_to_helper_offer(self.rid, 2, True, ""))


class InvitationRace(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="hpoint-invitations-")
        self.db = database.SQLiteConnection(str(Path(self.directory.name) / "race.db"))
        self.patches = [patch.object(module, "db", self.db) for module in (database, services)]
        for item in self.patches:
            item.start()
        database.init_db()
        for uid in (1, 2, 3):
            database.create_user(uid, f"User {uid}")
            services.add_to_queue(uid)
        self.rid = services.create_request(1, {"what": "Помочь", "place": "центр", "time_needed": "сегодня", "urgency": "обычная", "details": "test"})
        services.offer_helper(self.rid, 2)
        self.token = services.get_current_helper_offer(self.rid)["offer_token"]

    def tearDown(self):
        self.db.close()
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    def race(self, first, second):
        barrier = threading.Barrier(2)
        def run(action):
            try:
                barrier.wait(timeout=5)
                return action()
            finally:
                self.db.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(run, action) for action in (first, second)]
            return [job.result(timeout=10) for job in jobs]

    def test_cancel_and_accept_cannot_both_succeed(self):
        cancelled, accepted = self.race(
            lambda: services.withdraw_helper_offer(self.rid, 1, 2, self.token),
            lambda: services.respond_to_helper_offer(self.rid, 2, True, self.token),
        )
        self.assertEqual(sum((cancelled, accepted)), 1)
        self.assertEqual(database.get_request(self.rid)["status"], "open" if cancelled else "in_progress")
        self.assertEqual(database.get_request(self.rid)["helper_id"], None if cancelled else 2)

    def test_replacement_and_old_accept_cannot_both_succeed(self):
        replaced, accepted = self.race(
            lambda: services.offer_helper(self.rid, 3, self.token),
            lambda: services.respond_to_helper_offer(self.rid, 2, True, self.token),
        )
        self.assertEqual(sum((replaced, accepted)), 1)
        self.assertEqual(database.get_request(self.rid)["status"], "open" if replaced else "in_progress")
        self.assertEqual(database.get_request(self.rid)["helper_id"], None if replaced else 2)
        if replaced:
            self.assertEqual(services.get_current_helper_offer(self.rid)["candidate_id"], 3)


class InvitationAPI(InvitationData, unittest.TestCase):
    def setUp(self):
        self.prepare()
        self.tokens = {uid: web.new_sess(uid) for uid in (1, 2, 3, 4)}
        self.notify_patch = patch.object(web, "notify_telegram_user")
        self.notify = self.notify_patch.start()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=3)
        self.server.server_close()
        self.notify_patch.stop()
        self.close()

    def request(self, uid, path, data=None):
        headers = {"Content-Type": "application/json"}
        if uid:
            headers["Cookie"] = "hpoint_session=" + self.tokens[uid]
        request = urllib.request.Request(f"http://127.0.0.1:{self.server.server_port}" + path, headers=headers, data=json.dumps(data).encode() if data is not None else None)
        with urllib.request.urlopen(request, timeout=3) as response:
            return json.load(response)

    def assert_error(self, status, uid, path, data):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request(uid, path, data)
        with error.exception as response:
            self.assertEqual(response.code, status)

    def test_targeted_application_reaches_site_and_canonical_telegram_accounts_once(self):
        self.db.execute("UPDATE users SET tg_user_id=? WHERE user_id=?", (1001, 1))
        self.db.execute("UPDATE users SET tg_user_id=? WHERE user_id=?", (2002, 2))
        payload = {"request_id": self.rid}
        self.assertTrue(self.request(2, "/api/requests/accept", payload)["created"])
        self.assertEqual({call.args[0] for call in self.notify.call_args_list}, {1001, 2002})
        author_message = next(call for call in self.notify.call_args_list if call.args[0] == 1001)
        self.assertIn("User 2", author_message.args[1]);self.assertIn("Компьютер", author_message.args[1])
        self.assertIn(f"candidate:assign:{self.rid}:2", str(author_message.kwargs["reply_markup"]))
        self.assertFalse(self.request(2, "/api/requests/accept", payload)["created"])
        self.assertEqual(self.notify.call_count, 2)
        incoming = self.request(1, "/api/sync")["applications"]
        outgoing = self.request(2, "/api/sync")["my_applications"]
        self.assertEqual(incoming[0]["helper_id"], 2)
        self.assertEqual(incoming[0]["application_token"], outgoing[0]["application_token"])
        self.assertEqual(self.request(4, "/api/sync")["applications"], [])
        matches = self.request(1, "/api/assistant/candidates", payload)["matches"]
        self.assertEqual(matches[0]["user_id"], 2);self.assertTrue(matches[0]["applied"])
        self.assertEqual(database.get_request(self.rid)["status"], "open")
        self.assertEqual(self.request(1, "/api/chats")["chats"], [])

    def test_application_cancel_endpoint_checks_actor_and_stale_tokens(self):
        self.request(2, "/api/requests/accept", {"request_id": self.rid})
        response = self.request(1, "/api/sync")["applications"][0]
        payload = {"request_id": self.rid, "helper_id": 2, "application_token": response["application_token"]}
        self.assert_error(409, 4, "/api/requests/response/cancel", payload)
        self.notify.reset_mock()
        self.assertTrue(self.request(2, "/api/requests/response/cancel", payload)["cancelled"])
        self.assertEqual(self.notify.call_args.args[0], 1)
        self.assertEqual(self.request(1, "/api/sync")["applications"], [])
        self.request(2, "/api/requests/accept", {"request_id": self.rid})
        self.assert_error(409, 1, "/api/requests/response/cancel", payload)
        payload["application_token"] = self.request(1, "/api/sync")["applications"][0]["application_token"]
        self.assertTrue(self.request(1, "/api/requests/response/cancel", payload)["cancelled"])
        self.assertEqual(self.notify.call_args.args[0], 2)

    def test_cancel_from_either_side_and_find_new_candidates(self):
        assign = {"request_id": self.rid, "helper_id": 2}
        self.request(1, "/api/smart-match/assign", assign)
        offer = self.request(1, "/api/sync")["outgoing_offers"][0]
        token = offer["offer_token"]
        self.assertEqual(offer["helper_id"], 2)
        matches = self.request(1, "/api/assistant/candidates", {"request_id": self.rid})
        self.assertEqual(matches["offer"]["offer_token"], token)
        self.assertEqual({row["user_id"] for row in matches["matches"]}, {3, 4})
        cancel = {**assign, "offer_token": token}
        self.assert_error(401, None, "/api/helper/offers/withdraw", cancel)
        self.assert_error(409, 4, "/api/helper/offers/withdraw", cancel)
        self.assert_error(409, 2, "/api/helper/offers/withdraw", cancel)
        self.notify.reset_mock()
        self.assertTrue(self.request(1, "/api/helper/offers/withdraw", cancel)["withdrawn"])
        self.assertEqual({call.args[0] for call in self.notify.call_args_list}, {1, 2})
        self.assertEqual(self.request(2, "/api/helper/offers")["offers"], [])
        self.assertEqual(self.request(1, "/api/sync")["outgoing_offers"], [])
        self.assert_error(409, 2, "/api/helper/offers/respond", {"request_id": self.rid, "accept": True, "offer_token": token})
        self.request(1, "/api/smart-match/assign", assign)
        new = self.request(2, "/api/helper/offers")["offers"][0]["offer_token"]
        self.assertNotEqual(token, new)
        self.assert_error(409, 1, "/api/helper/offers/withdraw", cancel)
        self.notify.reset_mock()
        result = self.request(2, "/api/helper/offers/respond", {"request_id": self.rid, "accept": False, "offer_token": new})
        self.assertFalse(result["accepted"])
        self.assertEqual(self.notify.call_args.args[0], 1)
        self.assertEqual(self.request(1, "/api/sync")["outgoing_offers"], [])
        self.assertEqual(database.get_request(self.rid)["status"], "open")
        self.assertEqual(self.request(1, "/api/chats")["chats"], [])
        self.assertTrue(services.is_in_queue(2))

    def test_explicit_replacement_notifies_the_previous_helper(self):
        self.request(1, "/api/smart-match/assign", {"request_id": self.rid, "helper_id": 2})
        token = self.current()["offer_token"]
        replacement = {"request_id": self.rid, "helper_id": 3}
        self.assert_error(409, 1, "/api/smart-match/assign", replacement)
        self.notify.reset_mock()
        self.request(1, "/api/smart-match/assign", {**replacement, "replace_offer_token": token})
        self.assertEqual({call.args[0] for call in self.notify.call_args_list}, {1, 2, 3})
        self.assertEqual(self.current()["candidate_id"], 3)
        new = self.current()["offer_token"]
        self.request(3, "/api/helper/offers/respond", {"request_id": self.rid, "accept": True, "offer_token": new})
        self.assert_error(409, 1, "/api/helper/offers/withdraw", {**replacement, "offer_token": new})
        self.assertEqual(database.get_request(self.rid)["helper_id"], 3)
        self.assertEqual(len(self.request(1, "/api/chats")["chats"]), 1)

    def test_bad_or_stale_tokens_do_not_change_a_pending_invite(self):
        self.request(1, "/api/smart-match/assign", {"request_id": self.rid, "helper_id": 2})
        original = self.current()["offer_token"]
        for token, status in [(None, 400), ([original], 400), ("x" * 33, 400), ("", 409), ("old", 409)]:
            self.assert_error(status, 1, "/api/helper/offers/withdraw", {"request_id": self.rid, "helper_id": 2, "offer_token": token})
            self.assert_error(status, 2, "/api/helper/offers/respond", {"request_id": self.rid, "accept": False, "offer_token": token})
        self.assertEqual(self.current()["offer_token"], original)


class InvitationBot(InvitationData, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.prepare()
        self.bot = SimpleNamespace(send_message=AsyncMock())

    def tearDown(self):
        self.close()

    def callback(self, uid, action, token):
        # Telegram callback.message is sent by the bot, not by the requester.
        message = SimpleNamespace(from_user=SimpleNamespace(id=999000), edit_text=AsyncMock(), answer=AsyncMock())
        return SimpleNamespace(from_user=SimpleNamespace(id=uid), data=f"offer:{action}:{self.rid}:{token}", message=message, answer=AsyncMock())

    async def test_bot_reads_real_applications_and_can_decline_them(self):
        services.apply_to_request(self.rid, 2)
        candidate = services.smart_match(self.rid)[0]
        self.assertIn("Откликнулся", await handlers._candidate_card(candidate))
        token = services.get_request_applications(1)[0]["application_token"]
        callback = self.callback(1, "cancel", token)
        callback.data = f"ac:{self.rid}:2:{token}"
        await handlers.cb_application_cancel(callback, self.bot)
        self.assertEqual(services.get_request_applications(1), [])
        self.assertEqual(self.bot.send_message.call_args.args[0], 2)
        self.assertEqual(database.get_request(self.rid)["status"], "open")

    async def test_requester_can_cancel_in_bot_and_reopen_candidates(self):
        services.offer_helper(self.rid, 2)
        token = self.current()["offer_token"]
        callback = self.callback(1, "cancel", token)
        await handlers.cb_helper_offer_response(callback, self.bot)
        self.assertIsNone(self.current())
        self.assertEqual(database.get_request(self.rid)["status"], "open")
        self.bot.send_message.assert_awaited_once()
        self.assertEqual(self.bot.send_message.call_args.args[0], 2)
        self.assertIn("Кандидаты", callback.message.edit_text.call_args.args[0])
        callback.message.answer.assert_awaited()

    async def test_stale_telegram_buttons_cannot_answer_a_new_invitation(self):
        services.offer_helper(self.rid, 2)
        token = self.current()["offer_token"]
        services.withdraw_helper_offer(self.rid, 1, 2, token)
        services.offer_helper(self.rid, 2)
        callback = self.callback(2, "accept", token)
        await handlers.cb_helper_offer_response(callback, self.bot)
        self.assertIn("неактуально", callback.answer.call_args.args[0])
        self.assertEqual(database.get_request(self.rid)["status"], "open")
        self.bot.send_message.assert_not_awaited()
        callback = self.callback(2, "decline", self.current()["offer_token"])
        await handlers.cb_helper_offer_response(callback, self.bot)
        self.assertIsNone(self.current())
        self.assertEqual(self.bot.send_message.call_args.args[0], 1)

    async def test_helper_cannot_cancel_as_requester(self):
        services.offer_helper(self.rid, 2)
        token = self.current()["offer_token"]
        await handlers.cb_helper_offer_response(self.callback(2, "cancel", token), self.bot)
        self.assertEqual(self.current()["offer_token"], token)
        self.bot.send_message.assert_not_awaited()

    async def test_buttons_include_invitation_identity_and_fit_telegram_limit(self):
        token = "a" * 16
        rid = 9223372036854775807
        for markup in (helper_offer_kb(rid, token), candidates_navigation_kb(rid, {"offer_token": token})):
            for row in markup.inline_keyboard:
                for button in row:
                    self.assertLessEqual(len(button.callback_data.encode()), 64)
        self.assertTrue(helper_offer_kb(rid, token).inline_keyboard[0][0].callback_data.endswith(token))


if __name__ == "__main__":
    unittest.main()
