"""Personal PRO bot rights and free communication, without contacting Telegram."""
from datetime import datetime, timedelta, timezone
from html import unescape
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from aiogram.types import Chat, Message, User
from hpoint import database, handlers, keyboards, services, commercial, work_bot
from hpoint.chat_notifications import chat_notification, chat_notification_chunks
from hpoint.states import HelpRequest, Review


class MemoryState:
    def __init__(self):
        self.state = None
        self.data = {}

    async def clear(self):
        self.state, self.data = None, {}

    async def get_state(self):
        return self.state

    async def set_state(self, value):
        self.state = getattr(value, "state", value)

    async def update_data(self, **values):
        self.data.update(values)

    async def get_data(self):
        return dict(self.data)


class PersonalBot(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.patches = [patch.object(module, "db", self.db) for module in (database, services, handlers)]
        self.patches.append(patch.object(database, "REGISTRATION_BONUS_RUB", 0))
        for item in self.patches:
            item.start()
        database.init_db()
        self.owner, self.helper, self.other = [self.user(index) for index in (1, 2, 3)]
        self.state = MemoryState()
        self.bot = SimpleNamespace(send_message=AsyncMock())

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.db.close()

    def user(self, index):
        uid = database.create_web_user("Synthetic member " + str(index), f"bot-pro-{index}@example.test", "hash")
        self.db.execute("UPDATE users SET email_verified=1,tg_user_id=?,balance=100 WHERE user_id=?", (index * 101, uid))
        return uid

    def access(self, uid=None, active=True):
        end = datetime.now(timezone.utc) + timedelta(days=30 if active else -1)
        self.db.execute("UPDATE users SET pro_until=? WHERE user_id=?", (end.isoformat(), uid or self.owner))

    def tg(self, uid):
        return database.get_user(uid)["tg_user_id"]

    def message(self, text="Synthetic text", uid=None, chat_type="private"):
        actor = self.tg(uid or self.owner)
        return SimpleNamespace(text=text, from_user=SimpleNamespace(id=actor, username=None),
                               chat=SimpleNamespace(type=chat_type), answer=AsyncMock(),
                               edit_text=AsyncMock(), edit_reply_markup=AsyncMock())

    def callback(self, data, uid=None):
        return SimpleNamespace(data=data, from_user=SimpleNamespace(id=self.tg(uid or self.owner), username=None),
                               message=self.message(uid=uid), answer=AsyncMock())

    def request(self, uid=None, title="Synthetic request"):
        return services.create_request(uid or self.owner, {"what": title, "category": "other", "place": "Synthetic place",
                                       "time_needed": "По договорённости", "urgency": "🕊 Не срочно", "details": "Synthetic conditions"})

    def real_message(self, text):
        return Message(message_id=1, date=datetime.now(), chat=Chat(id=self.tg(self.owner), type="private"),
                       from_user=User(id=self.tg(self.owner), is_bot=False, first_name="Synthetic"), text=text)

    def test_menu_tracks_pro_expiry_without_unlocking_work(self):
        labels = lambda: [button.text for row in keyboards.main_menu_kb(self.owner).keyboard for button in row]
        self.assertNotIn(handlers.BTN_NEED_HELP, labels())
        self.access()
        self.assertIn(handlers.BTN_NEED_HELP, labels())
        self.assertIn(keyboards.BOT_REQUESTS_BUTTON, labels())
        self.assertNotIn(work_bot.WORK_BUTTON, labels())
        self.access(active=False)
        self.assertNotIn(handlers.BTN_NEED_HELP, labels())
        self.assertIn("💬 Мои чаты", labels())

    def test_paid_work_access_remains_independent_of_personal_pro(self):
        commercial.save_profile(self.db, self.owner, {"kind": "trainer", "title": "Synthetic trainer"})
        self.db.execute("UPDATE commercial_profiles SET paid_until=? WHERE user_id=?", ((datetime.now(timezone.utc)+timedelta(days=30)).isoformat(), self.owner))
        labels = str(keyboards.main_menu_kb(self.owner))
        self.assertIn(work_bot.WORK_BUTTON, labels)
        self.assertNotIn(handlers.BTN_NEED_HELP, labels)

    async def test_free_management_denial_keeps_draft_and_offers_both_site_routes(self):
        await self.state.set_state(HelpRequest.details)
        await self.state.update_data(what="Saved conditions", place="Saved place")
        message = self.message()
        self.assertFalse(await handlers.require_pro_management(message, self.state))
        self.assertEqual(await self.state.get_state(), HelpRequest.details.state)
        self.assertEqual((await self.state.get_data())["what"], "Saved conditions")
        text = message.answer.await_args.args[0]
        self.assertIn("бесплатно на сайте", text)
        markup = message.answer.await_args.kwargs["reply_markup"]
        urls = [button.url for row in markup.inline_keyboard for button in row]
        self.assertTrue(any(url.endswith("/#/help") for url in urls))
        self.assertTrue(any(url.endswith("/#/profile/billing") for url in urls))

    async def test_direct_guard_rechecks_email_link_block_and_private_chat(self):
        self.access()
        self.assertTrue(await handlers.require_pro_management(self.message()))
        self.assertFalse(await handlers.require_pro_management(self.message(chat_type="group")))
        for column, value in (("email_verified", 0), ("is_blocked", 1)):
            with self.subTest(column=column):
                self.db.execute(f"UPDATE users SET {column}=? WHERE user_id=?", (value, self.owner))
                self.assertFalse(await handlers.require_pro_management(self.message()))
                self.db.execute(f"UPDATE users SET {column}=? WHERE user_id=?", (1 if column=="email_verified" else 0, self.owner))
        original = self.message()
        self.db.execute("UPDATE users SET tg_user_id=NULL WHERE user_id=?", (self.owner,))
        self.assertFalse(await handlers.require_pro_management(original))

    async def test_new_pro_form_creates_free_request_and_no_money_entries(self):
        self.access()
        await handlers.need_help_start(self.message(handlers.BTN_NEED_HELP), self.state)
        self.assertEqual(await self.state.get_state(), HelpRequest.what.state)
        await handlers.q_what(self.message("Synthetic task"), self.state)
        await handlers.q_place(self.message("Synthetic place"), self.state)
        await handlers.q_time(self.message("По договорённости"), self.state)
        await handlers.q_urgency(self.message("🕊 Не срочно"), self.state)
        await handlers.q_details(self.message(handlers.BTN_NO_DETAILS), self.state, self.bot)
        rows = self.db.execute("SELECT * FROM requests WHERE requester_id=?", (self.owner,)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reward_rub"], 0)
        self.assertEqual(rows[0]["reward_payment_status"], "none")
        self.assertIsNone(await self.state.get_state())
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM wallet_transactions").fetchone()[0], 0)
        self.bot.send_message.assert_not_awaited()

    async def test_expired_pro_form_steps_do_not_consume_answers_or_publish(self):
        self.access(active=False)
        for handler in (handlers.q_what, handlers.q_place, handlers.q_time, handlers.q_urgency, handlers.q_details):
            with self.subTest(handler=handler.__name__):
                await self.state.set_state(HelpRequest.details)
                await self.state.update_data(what="Saved task", place="Saved place", details="Saved detail")
                before = await self.state.get_data()
                args = (self.message("Replacement"), self.state, self.bot) if handler is handlers.q_details else (self.message("Replacement"), self.state)
                await handler(*args)
                self.assertEqual(await self.state.get_data(), before)
                self.assertEqual(await self.state.get_state(), HelpRequest.details.state)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM requests").fetchone()[0], 0)

    async def test_limit_race_after_form_open_preserves_complete_answers(self):
        self.access()
        await self.state.set_state(HelpRequest.details)
        await self.state.update_data(what="Saved task", category="other", place="Saved place", time_needed="По договорённости", urgency="🕊 Не срочно")
        for index in range(10):
            self.request(title="Existing task " + str(index))
        message = self.message("Saved final detail")
        await handlers.q_details(message, self.state, self.bot)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM requests").fetchone()[0], 10)
        self.assertEqual((await self.state.get_data())["details"], "Saved final detail")
        self.assertEqual(await self.state.get_state(), HelpRequest.details.state)
        self.assertIn("сохранены", message.answer.await_args.args[0])

    async def test_stale_management_callbacks_cannot_mutate_after_expiry(self):
        self.access()
        rid = self.request()
        self.access(active=False)
        cases = [(handlers.cb_candidate_assign, f"candidate:assign:{rid}:{self.helper}", True),
                 (handlers.cb_candidate_refresh, f"candidate:refresh:{rid}", False),
                 (handlers.cb_candidate_back, f"candidate:back:{rid}", False),
                 (handlers.cb_match_request, f"matchreq:{rid}", False),
                 (handlers.cb_cancel_request, f"cancel_req:{rid}", False),
                 (handlers.cb_finish, f"finish:{rid}", True),
                 (handlers.cb_paid_completion, f"paid_done:{rid}", True),
                 (handlers.cb_request_management_menu, "bot:requests", False),
                 (handlers.cb_request_management_view, f"request:view:{rid}", False),
                 (handlers.cb_helper_offer_response, f"offer:cancel:{rid}:old-token", True),
                 (handlers.cb_application_cancel, f"ac:{rid}:{self.helper}:old-token", True)]
        before = dict(database.get_request(rid))
        for handler, data, needs_bot in cases:
            with self.subTest(handler=handler.__name__):
                callback = self.callback(data)
                await handler(callback, self.bot) if needs_bot else await handler(callback)
                self.assertEqual(dict(database.get_request(rid)), before)
                self.assertIn("PRO", callback.answer.await_args.args[0])
        self.bot.send_message.assert_not_awaited()

    async def test_helper_consent_is_free_even_with_own_open_request(self):
        rid = self.request()
        self.request(self.helper, "Helper's own task")
        services.add_to_queue(self.helper)
        self.assertTrue(services.offer_helper(rid, self.helper))
        offer = services.get_current_helper_offer(rid)
        callback = self.callback(f"offer:accept:{rid}:{offer['offer_token']}", self.helper)
        await handlers.cb_helper_offer_response(callback, self.bot)
        request = database.get_request(rid)
        self.assertEqual(request["status"], "in_progress")
        self.assertEqual(request["helper_id"], self.helper)
        self.assertNotIn("PRO", callback.answer.await_args.args[0])

    async def test_helper_can_withdraw_response_without_pro(self):
        rid = self.request()
        self.assertEqual(services.apply_to_request(rid, self.helper), "created")
        application = self.db.execute("SELECT offer_token FROM request_candidates WHERE request_id=? AND candidate_id=?", (rid, self.helper)).fetchone()
        callback = self.callback(f"ac:{rid}:{self.helper}:{application['offer_token']}", self.helper)
        await handlers.cb_application_cancel(callback, self.bot)
        self.assertNotEqual(self.db.execute("SELECT status FROM request_candidates WHERE request_id=? AND candidate_id=?", (rid, self.helper)).fetchone()[0], "applied")

    async def test_free_chat_ignores_own_open_request_and_preserves_pending_draft(self):
        self.access()
        rid = self.request(title="Ongoing task")
        self.assertEqual(services.accept_open_request(rid, self.helper), "created")
        self.request(title="New open task")
        self.access(active=False)
        await self.state.set_state(HelpRequest.details)
        await self.state.update_data(what="Draft retained")
        message = self.message("/chat Free complete message")
        await handlers.cmd_chat(message, self.state, self.bot)
        saved = self.db.execute("SELECT m.text FROM chat_messages m JOIN chats c ON c.id=m.chat_id WHERE c.request_id=?", (rid,)).fetchall()
        self.assertEqual([row[0] for row in saved], ["Free complete message"])
        self.assertEqual((await self.state.get_data())["what"], "Draft retained")
        self.assertTrue(self.bot.send_message.await_count)

    async def test_multiple_free_chats_require_explicit_target_and_never_misdeliver(self):
        self.access()
        first, second = self.request(title="First conversation"), self.request(title="Second conversation")
        self.assertEqual(services.accept_open_request(first, self.helper), "created")
        self.assertEqual(services.accept_open_request(second, self.other), "created")
        self.access(active=False)
        message = self.message("/chat Choose safely")
        await handlers.cmd_chat(message, self.state, self.bot)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0], 0)
        self.assertIn("First conversation", message.answer.await_args.args[0])
        self.assertIn("Second conversation", message.answer.await_args.args[0])
        await handlers.cmd_chat(self.message(f"/chat #{first} Exact message"), self.state, self.bot)
        rows = self.db.execute("SELECT c.request_id,m.text FROM chat_messages m JOIN chats c ON c.id=m.chat_id").fetchall()
        self.assertEqual([(r[0], r[1]) for r in rows], [(first, "Exact message")])

    async def test_oversize_chat_is_rejected_without_silent_truncation(self):
        rid = self.request()
        self.assertEqual(services.accept_open_request(rid, self.helper), "created")
        message = self.message("/chat " + "x" * 1001)
        await handlers.cmd_chat(message, self.state, self.bot)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0], 0)
        self.assertIn("не был обрезан", message.answer.await_args.args[0])
        self.bot.send_message.assert_not_awaited()

    async def test_chat_notification_chunks_deliver_every_character_after_pro_expiry(self):
        rid = self.request(title="Escaped <title>")
        self.assertEqual(services.accept_open_request(rid, self.helper), "created")
        self.access(active=False)
        text = "<&>" * 333 + "🙂"
        self.assertEqual(len(text), 1000)
        await handlers.cmd_chat(self.message("/chat " + text), self.state, self.bot)
        rows = self.db.execute("SELECT text FROM chat_messages").fetchall()
        self.assertEqual(rows[0][0], text)
        payloads = [item.args[1] for item in self.bot.send_message.await_args_list]
        self.assertGreater(len(payloads), 1)
        self.assertTrue(all(len(part)<3800 and "<title>" not in part for part in payloads))
        recovered = "".join(unescape(part.split("\n\n",1)[1].rsplit("\n\n",1)[0]) for part in payloads)
        self.assertEqual(recovered, text)
        self.assertTrue(all("купить" not in part.lower() and "PRO" not in part for part in payloads))

    async def test_review_and_chat_commands_reach_free_handlers_after_expiry(self):
        self.access(active=False)
        self.assertFalse(await handlers.simplified_bot_message(self.real_message("/chat hello"), {"state": self.state}))
        await self.state.set_state(Review.requester_review)
        self.assertFalse(await handlers.simplified_bot_message(self.real_message("Synthetic review"), {"state": self.state}))

    async def test_every_retired_purchase_callback_rejects_without_invoice_or_draft_loss(self):
        await self.state.set_state(HelpRequest.details)
        await self.state.update_data(what="Protected draft")
        with patch.object(handlers, "create_pending_invoice", new=Mock(side_effect=AssertionError("No invoice allowed"))):
            for item in ("boost", "more_responses", "verification", "favorites", "business", "business_pro", "ad", "unknown"):
                await handlers.cb_buy(self.callback("buy:"+item), self.state)
            await handlers.cb_buy_request(self.callback("buyreq:boost"))
            await handlers.cb_pay_request(self.callback("payreq:boost:1"))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM billing_invoices").fetchone()[0], 0)
        self.assertEqual((await self.state.get_data())["what"], "Protected draft")

    async def test_pro_purchase_is_site_link_and_not_a_bot_charge(self):
        callback = self.callback("buy:pro")
        await handlers.cb_buy(callback, self.state)
        text = callback.message.answer.await_args.args[0]
        self.assertIn("149", text)
        self.assertIn("90 HP", text)
        markup = callback.message.answer.await_args.kwargs["reply_markup"]
        self.assertTrue(any("item=pro" in b.url for row in markup.inline_keyboard for b in row))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM billing_invoices").fetchone()[0], 0)

    async def test_old_telegram_registration_never_creates_an_account(self):
        before = self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        message = self.message("Synthetic name")
        message.from_user.id = 999999
        await handlers.reg_name(message, self.state)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0], before)
        self.assertIn("email", message.answer.await_args.args[0])


class NotificationFormat(unittest.TestCase):
    def test_legacy_string_formatter_keeps_full_text_without_ads(self):
        body = "a" * 1100 + "tail<&>"
        value = chat_notification(42, "Name", body, "Task")
        self.assertIn("tail&lt;&amp;&gt;", value)
        self.assertEqual(unescape(value.split("\n\n",1)[1].rsplit("\n\n",1)[0]), body)
        self.assertNotIn("PRO", value)

    def test_empty_and_emoji_text_create_valid_complete_chunks(self):
        for text in ("", "🙂"*1500, "'\"&<>"*300):
            parts = chat_notification_chunks(7, "<sender>", text, "<task>", chat_id=3)
            self.assertTrue(parts)
            self.assertTrue(all(len(part)<3800 for part in parts))
            actual = "".join(unescape(part.split("\n\n",1)[1].rsplit("\n\n",1)[0]) for part in parts)
            self.assertEqual(actual, text)
            self.assertTrue(all('/#/help/chat/7/3' in part for part in parts))


if __name__ == "__main__":
    unittest.main()
