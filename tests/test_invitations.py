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
            self.db.execute("UPDATE users SET email=?,email_verified=1 WHERE user_id=?",(f"user{uid}@example.test",uid))
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

    def test_direct_accept_is_atomic_idempotent_and_creates_chat(self):
        self.assertEqual(services.accept_open_request(self.rid,2),"created")
        self.assertEqual(services.accept_open_request(self.rid,2),"existing")
        self.assertEqual(services.accept_open_request(self.rid,3),"unavailable")
        self.assertEqual(database.get_request(self.rid)["helper_id"],2)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM chats").fetchone()["n"],1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM request_events WHERE event_type='helper_accepted'").fetchone()["n"],1)

    def test_paid_direct_accept_cannot_bypass_wallet_reserve(self):
        self.db.execute("UPDATE requests SET reward_rub=400 WHERE id=?",(self.rid,))
        self.assertEqual(services.accept_open_request(self.rid,2),"awaiting_funds")
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM chats").fetchone()["n"],0)
        database.wallet_add_entry(1,500,"test","Synthetic","test")
        services.reserve_request_reward(self.rid,1,400)
        self.assertEqual(services.accept_open_request(self.rid,2),"created")
        self.assertEqual(database.wallet_summary(2)["test_balance_rub"],0)

    def test_author_can_accept_legacy_response_without_inviting_again(self):
        services.apply_to_request(self.rid,2)
        token=services.get_request_applications(1)[0]["application_token"]
        self.assertEqual(services.accept_open_request(self.rid,2,author_id=3,application_token=token),"unavailable")
        self.assertEqual(services.accept_open_request(self.rid,2,author_id=1,application_token="stale"),"unavailable")
        self.assertEqual(services.accept_open_request(self.rid,2,author_id=1,application_token=token),"created")
        self.assertIsNone(services.get_current_helper_offer(self.rid))

    def test_failed_chat_creation_rolls_back_assignment(self):
        with patch.object(services,"get_or_create_chat_for_request",side_effect=RuntimeError("chat unavailable")):
            with self.assertRaises(RuntimeError):services.accept_open_request(self.rid,2)
        self.assertEqual(database.get_request(self.rid)["status"],"open")
        self.assertIsNone(database.get_request(self.rid)["helper_id"])
        self.assertTrue(services.is_in_queue(2))

    def test_direct_response_cannot_accept_own_or_blocked_help(self):
        self.assertEqual(services.accept_open_request(self.rid,1),"unavailable")
        self.db.execute("UPDATE users SET is_blocked=1 WHERE user_id=2")
        self.assertEqual(services.accept_open_request(self.rid,2),"unavailable")
        self.assertIsNone(database.get_request(self.rid)["helper_id"])

    def test_paid_invite_before_reserve_then_author_confirms_wallet_release(self):
        self.db.execute("UPDATE requests SET reward_rub=400 WHERE id=?", (self.rid,))
        hp = [database.get_user(uid)["balance"] for uid in (1, 2)]
        self.assertTrue(services.offer_helper(self.rid, 2))
        token = self.current()["offer_token"]
        self.assertFalse(services.respond_to_helper_offer(self.rid, 2, True, token))
        with self.assertRaisesRegex(ValueError, "insufficient wallet"):
            services.reserve_request_reward(self.rid, 1, 400)
        database.wallet_add_entry(1, 500, "test", "Synthetic funds", "test")
        with self.assertRaises(ValueError):
            services.reserve_request_reward(self.rid, 2, 400)
        with self.assertRaisesRegex(ValueError, "reward changed"):
            services.reserve_request_reward(self.rid, 1, 399)
        self.assertTrue(services.reserve_request_reward(self.rid, 1, 400))
        self.assertFalse(services.reserve_request_reward(self.rid, 1, 400))
        self.assertEqual(database.wallet_summary(1)["test_balance_rub"], 100)
        self.assertEqual(database.wallet_summary(1)["test_reserved_rub"], 400)
        self.assertEqual(database.wallet_summary(2)["test_balance_rub"], 0)
        self.assertTrue(services.respond_to_helper_offer(self.rid, 2, True, token))
        self.assertIsNone(database.get_request(self.rid)["completion_requested_at"])
        self.assertFalse(services.complete_request(self.rid, 2, confirmed_by=2))
        self.assertFalse(services.complete_request(self.rid, 2, confirmed_by=4))
        self.assertEqual(database.wallet_summary(2)["test_balance_rub"], 0)
        self.assertTrue(services.complete_request(self.rid, 2, confirmed_by=1))
        self.assertFalse(services.complete_request(self.rid, 2, confirmed_by=1))
        self.assertEqual(database.wallet_summary(1)["test_reserved_rub"], 0)
        self.assertEqual(database.wallet_summary(2)["test_balance_rub"], 340)
        self.assertEqual(self.db.execute("SELECT SUM(commission_test_rub) total FROM platform_commissions").fetchone()["total"],60)
        self.assertEqual([database.get_user(uid)["balance"] for uid in (1, 2)], hp)

    def test_paid_reserve_is_returned_once_if_open_request_is_cancelled(self):
        self.db.execute("UPDATE requests SET reward_rub=400 WHERE id=?", (self.rid,))
        database.wallet_add_entry(1, 500, "test", "Synthetic funds", "test")
        services.reserve_request_reward(self.rid, 1, 400)
        self.assertTrue(services.cancel_request(self.rid, 1))
        self.assertFalse(services.cancel_request(self.rid, 1))
        self.assertEqual(database.wallet_summary(1)["test_balance_rub"], 500)
        self.assertEqual(database.wallet_summary(1)["test_reserved_rub"], 0)

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
        self.assertEqual([row["helper_id"] for row in services.get_request_applications(1)], [3])

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
        self.directory = tempfile.TemporaryDirectory(prefix="hpoint-invitations-",dir=Path.cwd())
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

    def test_simultaneous_reserve_debits_only_once(self):
        self.db.execute("UPDATE requests SET reward_rub=400 WHERE id=?", (self.rid,))
        database.wallet_add_entry(1,600,"test","Synthetic","test")
        results=self.race(lambda:services.reserve_request_reward(self.rid,1,400),lambda:services.reserve_request_reward(self.rid,1,400))
        self.assertEqual(sorted(results),[False,True])
        self.assertEqual(database.wallet_summary(1)["test_balance_rub"],200)
        self.assertEqual(database.wallet_summary(1)["test_reserved_rub"],400)

    def test_two_reserves_cannot_overdraw_one_wallet(self):
        self.db.execute("UPDATE requests SET reward_rub=400 WHERE id=?", (self.rid,))
        other=services.create_request(1,{"what":"Другой резерв","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"test","reward_rub":400})
        database.wallet_add_entry(1,600,"test","Synthetic","test")
        def reserve(rid):
            try:return services.reserve_request_reward(rid,1,400)
            except ValueError as error:return str(error)
        results=self.race(lambda:reserve(self.rid),lambda:reserve(other))
        self.assertIn(True,results);self.assertIn("insufficient wallet",results)
        self.assertEqual(database.wallet_summary(1)["test_balance_rub"],200)

    def test_simultaneous_confirmation_cannot_pay_helper_twice(self):
        self.db.execute("UPDATE requests SET reward_rub=400 WHERE id=?", (self.rid,))
        database.wallet_add_entry(1,600,"test","Synthetic","test")
        services.reserve_request_reward(self.rid,1,400)
        self.assertTrue(services.respond_to_helper_offer(self.rid,2,True,self.token))
        self.assertEqual(services.request_help_completion(self.rid,2),"created")
        results=self.race(lambda:services.complete_request(self.rid,2,confirmed_by=1),lambda:services.complete_request(self.rid,2,confirmed_by=1))
        self.assertEqual(sorted(results),[False,True])
        self.assertEqual(database.wallet_summary(2)["test_balance_rub"],340)

    def test_cancel_and_accept_cannot_both_succeed(self):
        cancelled, accepted = self.race(
            lambda: services.withdraw_helper_offer(self.rid, 1, 2, self.token),
            lambda: services.respond_to_helper_offer(self.rid, 2, True, self.token),
        )
        self.assertEqual(sum((cancelled, accepted)), 1)
        self.assertEqual(database.get_request(self.rid)["status"], "open" if cancelled else "in_progress")
        self.assertEqual(database.get_request(self.rid)["helper_id"], None if cancelled else 2)

    def test_two_direct_responses_create_only_one_match_and_chat(self):
        results=self.race(lambda:services.accept_open_request(self.rid,2),lambda:services.accept_open_request(self.rid,3))
        self.assertEqual(sorted(results),["created","unavailable"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM chats").fetchone()["n"],1)

    def test_one_helper_cannot_directly_accept_two_requests(self):
        other=services.create_request(1,{"what":"Second request","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"test"})
        results=self.race(lambda:services.accept_open_request(self.rid,2),lambda:services.accept_open_request(other,2))
        self.assertEqual(sorted(results),["created","unavailable"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM chats").fetchone()["n"],1)

    def test_direct_response_and_invitation_cannot_both_assign(self):
        results=self.race(lambda:services.accept_open_request(self.rid,3),lambda:services.respond_to_helper_offer(self.rid,2,True,self.token))
        self.assertEqual(sum(result in (True,"created") for result in results),1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM chats").fetchone()["n"],1)

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

    def test_paid_request_api_invites_reserves_and_confirms_without_hp_or_direct_pay(self):
        self.db.execute("UPDATE requests SET reward_rub=400 WHERE id=?", (self.rid,))
        self.request(1, "/api/smart-match/assign", {"request_id":self.rid,"helper_id":2})
        offer = self.request(2, "/api/helper/offers")["offers"][0]
        self.assertEqual(offer["reward_rub"], 400)
        self.assertIn("400", self.notify.call_args_list[0].args[1])
        accept = {"request_id":self.rid,"accept":True,"offer_token":offer["offer_token"]}
        self.assert_error(409, 2, "/api/helper/offers/respond", accept)
        self.assert_error(409, 1, "/api/requests/reward/reserve", {"request_id":self.rid,"amount_rub":400})
        database.wallet_add_entry(1, 500, "test", "Synthetic", "test")
        self.assert_error(409, 2, "/api/requests/reward/reserve", {"request_id":self.rid,"amount_rub":400})
        self.assertTrue(self.request(1, "/api/requests/reward/reserve", {"request_id":self.rid,"amount_rub":400})["created"])
        self.assertFalse(self.request(1, "/api/requests/reward/reserve", {"request_id":self.rid,"amount_rub":400})["created"])
        self.request(2, "/api/helper/offers/respond", accept)
        self.assert_error(403, 2, "/api/requests/finish", {"request_id":self.rid})
        self.assertEqual(database.wallet_summary(2)["test_balance_rub"], 0)
        self.assert_error(403, 2, "/api/requests/completion/confirm", {"request_id":self.rid})
        self.request(1, "/api/requests/completion/confirm", {"request_id":self.rid})
        self.assert_error(409, 1, "/api/requests/completion/confirm", {"request_id":self.rid})
        self.assertEqual(database.wallet_summary(2)["test_balance_rub"], 340)

    def test_free_completion_api_is_requester_only_and_settles_once(self):
        self.assertTrue(services.accept_open_request(self.rid,2))
        for actor in (2,3):
            for endpoint in ("/api/requests/finish","/api/requests/completion/confirm"):
                self.assert_error(403,actor,endpoint,{"request_id":self.rid})
        self.assertEqual(database.get_request(self.rid)["status"],"in_progress")
        self.assertEqual([database.get_user(uid)["balance"] for uid in (1,2)],[100,100])
        self.assertTrue(self.request(1,"/api/requests/finish",{"request_id":self.rid})["ok"])
        self.assert_error(409,1,"/api/requests/finish",{"request_id":self.rid})
        self.assertEqual([database.get_user(uid)["balance"] for uid in (1,2)],[90,120])

    def test_real_acquiring_is_disabled_without_creating_a_reward_invoice(self):
        self.db.execute("UPDATE requests SET reward_rub=400 WHERE id=?", (self.rid,))
        with patch.object(web,"ROBOKASSA_MERCHANT_LOGIN",""),patch.object(web,"ROBOKASSA_PASSWORD_1",""),patch.object(web,"ROBOKASSA_PASSWORD_2",""):
            self.assert_error(409,1,"/api/requests/reward/pay",{"request_id":self.rid})
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM billing_invoices WHERE item_type='request_reward'").fetchone()["n"],0)

    def test_targeted_application_reaches_site_and_canonical_telegram_accounts_once(self):
        self.db.execute("UPDATE users SET tg_user_id=? WHERE user_id=?", (1001, 1))
        self.db.execute("UPDATE users SET tg_user_id=? WHERE user_id=?", (2002, 2))
        payload = {"request_id": self.rid}
        self.assertTrue(self.request(2, "/api/requests/accept", payload)["created"])
        self.assertEqual({call.args[0] for call in self.notify.call_args_list}, {1001, 2002})
        author_message = next(call for call in self.notify.call_args_list if call.args[0] == 1001)
        self.assertIn("User 2", author_message.args[1]);self.assertIn("Компьютер", author_message.args[1])
        self.assertIn(f"/#/help/chat/{self.rid}", str(author_message.kwargs["reply_markup"]))
        self.assertFalse(self.request(2, "/api/requests/accept", payload)["created"])
        self.assertEqual(self.notify.call_count, 2)
        incoming = self.request(1, "/api/sync")["applications"]
        outgoing = self.request(2, "/api/sync")["my_applications"]
        self.assertEqual(incoming, [])
        self.assertEqual(outgoing, [])
        self.assertEqual(self.request(4, "/api/sync")["applications"], [])
        self.assertEqual(database.get_request(self.rid)["status"], "in_progress")
        self.assertEqual(len(self.request(1, "/api/chats")["chats"]), 1)
        self.assert_error(409,3,"/api/requests/accept",payload)
        self.assertEqual(database.get_request(self.rid)["helper_id"],2)

    def test_application_cancel_endpoint_checks_actor_and_stale_tokens(self):
        services.apply_to_request(self.rid,2)
        response = self.request(1, "/api/sync")["applications"][0]
        payload = {"request_id": self.rid, "helper_id": 2, "application_token": response["application_token"]}
        self.assert_error(409, 4, "/api/requests/response/cancel", payload)
        self.notify.reset_mock()
        self.assertTrue(self.request(2, "/api/requests/response/cancel", payload)["cancelled"])
        self.assertEqual(self.notify.call_args.args[0], 1)
        self.assertEqual(self.request(1, "/api/sync")["applications"], [])
        services.apply_to_request(self.rid,2)
        self.assert_error(409, 1, "/api/requests/response/cancel", payload)
        payload["application_token"] = self.request(1, "/api/sync")["applications"][0]["application_token"]
        self.assertTrue(self.request(1, "/api/requests/response/cancel", payload)["cancelled"])

    def test_owner_accepts_legacy_response_from_notification_without_new_invite(self):
        services.apply_to_request(self.rid,2)
        response=self.request(1,"/api/sync")["applications"][0]
        payload={"request_id":self.rid,"helper_id":2,"application_token":response["application_token"]}
        self.assert_error(409,4,"/api/requests/response/accept",payload)
        self.assert_error(409,1,"/api/requests/response/accept",{**payload,"application_token":"old"})
        self.assertTrue(self.request(1,"/api/requests/response/accept",payload)["matched"])
        self.assertEqual(database.get_request(self.rid)["helper_id"],2)
        self.assertEqual(self.request(2,"/api/helper/offers")["offers"],[])
        self.assertEqual(len(self.request(1,"/api/chats")["chats"]),1)
        self.assertEqual({call.args[0] for call in self.notify.call_args_list},{1,2})
        self.assert_error(409,1,"/api/requests/response/accept",payload)
        self.assertEqual(self.notify.call_count,2)

    def test_matching_an_existing_response_accepts_it_instead_of_reinviting(self):
        services.apply_to_request(self.rid,2)
        result=self.request(1,"/api/smart-match/assign",{"request_id":self.rid,"helper_id":2})
        self.assertTrue(result["matched"])
        self.assertEqual(database.get_request(self.rid)["helper_id"],2)
        self.assertIsNone(self.current())
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
    async def test_paid_bot_explains_reserve_and_requires_author_payout(self):
        self.db.execute("UPDATE requests SET reward_rub=400 WHERE id=?", (self.rid,))
        services.offer_helper(self.rid,2)
        callback = self.callback(2,"accept",self.current()["offer_token"])
        await handlers.cb_helper_offer_response(callback,self.bot)
        self.assertIn("резерв",callback.answer.call_args.args[0])
        database.wallet_add_entry(1,500,"test","Synthetic","test")
        services.reserve_request_reward(self.rid,1,400)
        await handlers.cb_helper_offer_response(callback,self.bot)
        callback = self.callback(2,"finish","")
        callback.data = f"finish:{self.rid}"
        await handlers.cb_finish(callback,self.bot)
        self.assertEqual(database.wallet_summary(2)["test_balance_rub"],0)
        self.assertIn("только автор",callback.answer.call_args.args[0])
        self.assertIsNone(database.get_request(self.rid)["completion_requested_at"])
        callback = self.callback(1,"confirm","")
        callback.data = f"paid_done:{self.rid}"
        await handlers.cb_paid_completion(callback,self.bot)
        self.assertEqual(database.wallet_summary(2)["test_balance_rub"],340)
        await handlers.cb_paid_completion(callback,self.bot)
        self.assertEqual(database.wallet_summary(2)["test_balance_rub"],340)

    async def test_free_bot_completion_rejects_helper_and_notifies_after_author_confirmation(self):
        services.accept_open_request(self.rid,2)
        await handlers.notify_match(self.bot,self.rid)
        helper_message,author_message=self.bot.send_message.call_args_list[-2:]
        helper_keys=helper_message.kwargs["reply_markup"].inline_keyboard
        author_keys=author_message.kwargs["reply_markup"].inline_keyboard
        self.assertFalse(any(key.callback_data==f"finish:{self.rid}" for row in helper_keys for key in row))
        self.assertTrue(any(key.callback_data==f"finish:{self.rid}" for row in author_keys for key in row))
        for uid in (2,3):
            callback=self.callback(uid,"finish","");callback.data=f"finish:{self.rid}"
            await handlers.cb_finish(callback,self.bot)
            self.assertIn("только автор",callback.answer.call_args.args[0])
        self.assertEqual(database.get_request(self.rid)["status"],"in_progress")
        callback=self.callback(1,"finish","");callback.data=f"finish:{self.rid}"
        await handlers.cb_finish(callback,self.bot)
        self.assertEqual(database.get_request(self.rid)["status"],"done")
        self.assertEqual([database.get_user(uid)["balance"] for uid in (1,2)],[90,120])
        self.assertEqual(self.bot.send_message.call_args.args[0],2)
        await handlers.cb_finish(callback,self.bot)
        self.assertEqual([database.get_user(uid)["balance"] for uid in (1,2)],[90,120])

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

    async def test_bot_accepts_legacy_response_and_notifies_linked_accounts(self):
        services.apply_to_request(self.rid,2)
        self.db.execute("UPDATE users SET tg_user_id=user_id*1000")
        callback=self.callback(1,"accept","")
        callback.data=f"candidate:assign:{self.rid}:2"
        await handlers.cb_candidate_assign(callback,self.bot)
        self.assertEqual(database.get_request(self.rid)["helper_id"],2)
        self.assertIsNone(self.current())
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM chats").fetchone()["n"],1)
        self.assertEqual({call.args[0] for call in self.bot.send_message.call_args_list},{1000,2000})
        for call in self.bot.send_message.call_args_list:
            self.assertIn(f"/#/help/chat/{self.rid}",str(call.kwargs["reply_markup"]))

    async def test_bot_invitation_acceptance_creates_chat_in_one_consent(self):
        services.offer_helper(self.rid,2)
        callback=self.callback(2,"accept",self.current()["offer_token"])
        await handlers.cb_helper_offer_response(callback,self.bot)
        self.assertEqual(database.get_request(self.rid)["status"],"in_progress")
        self.assertIsNone(self.current())
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM chats").fetchone()["n"],1)
        self.assertEqual(self.bot.send_message.call_count,2)

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
