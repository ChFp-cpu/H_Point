"""PRO helping controls share site state; free notices/consent stay usable."""
from datetime import datetime, timedelta, timezone
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from hpoint import database, handlers, keyboards, services


class HelperBot(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:",isolation_level=None)
        self.db.row_factory=sqlite3.Row
        self.patches=[patch.object(module,"db",self.db) for module in (database,services,handlers)]
        self.patches.append(patch.object(database,"REGISTRATION_BONUS_RUB",0))
        for item in self.patches:item.start()
        database.init_db()
        self.author,self.helper,self.other=[self.user(n) for n in (1,2,3)]
        self.pro(self.helper)
        self.bot=SimpleNamespace(send_message=AsyncMock())
        self.state=SimpleNamespace(clear=AsyncMock())

    def tearDown(self):
        self.db.close()
        for item in reversed(self.patches):item.stop()

    def user(self,n):
        uid=database.create_web_user("Synthetic helper "+str(n),f"helper-bot-{n}@example.test","hash")
        self.db.execute("UPDATE users SET email_verified=1,tg_user_id=?,balance=1000 WHERE user_id=?",(n*101,uid))
        return uid

    def pro(self,uid,active=True):
        end=datetime.now(timezone.utc)+timedelta(days=30 if active else -1)
        self.db.execute("UPDATE users SET pro_until=? WHERE user_id=?",(end.isoformat(),uid))

    def tg(self,uid):return database.get_user(uid)["tg_user_id"]

    def message(self,uid=None,text=None):
        uid=uid or self.helper
        return SimpleNamespace(from_user=SimpleNamespace(id=self.tg(uid)),chat=SimpleNamespace(type="private"),
                               text=text or handlers.BTN_WANT_HELP,answer=AsyncMock(),edit_text=AsyncMock())

    def callback(self,action,uid=None):
        uid=uid or self.helper
        # The Telegram message sender is the bot, distinct from the actor.
        message=self.message(uid);message.from_user=SimpleNamespace(id=999999)
        return SimpleNamespace(data=action,from_user=SimpleNamespace(id=self.tg(uid)),message=message,answer=AsyncMock())

    def request(self,uid=None,**extra):
        return services.create_request(uid or self.author,{**dict(what="Помочь с компьютером",category="tech",place="Private exact address",
            time_needed="По договорённости",urgency="Обычная",details="Private task details",reward_rub=0),**extra})

    def body(self,message):return "\n".join(str(call.args[0]) for call in message.answer.await_args_list)

    async def action(self,name,uid=None):
        callback=self.callback("helper:"+name,uid)
        await handlers.cb_helper_management(callback,self.bot)
        return callback

    def test_menu_adds_helping_only_to_live_pro(self):
        labels=lambda uid:[button.text for row in keyboards.main_menu_kb(uid).keyboard for button in row]
        self.assertIn(handlers.BTN_WANT_HELP,labels(self.helper))
        self.assertNotIn(handlers.BTN_WANT_HELP,labels(self.author))
        self.pro(self.helper,False)
        self.assertNotIn(handlers.BTN_WANT_HELP,labels(self.helper))
        self.assertIn("💬 Мои чаты",labels(self.helper))
        self.assertIn("Хочу помочь",handlers.BOT_GUIDE)

    async def test_open_is_read_only_and_own_request_does_not_block_help(self):
        self.request(self.helper)
        message=self.message()
        await handlers.want_help(message,self.state,self.bot)
        self.assertIn("Хочу помочь",self.body(message))
        self.assertIn("Подобрать помощь",str(message.answer.await_args.kwargs["reply_markup"]))
        self.assertFalse(services.is_in_queue(self.helper))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM requests").fetchone()[0],1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM wallet_transactions").fetchone()[0],0)
        self.state.clear.assert_not_awaited()

    async def test_free_entry_has_site_and_pro_fallback_without_effects(self):
        message=self.message(self.author)
        await handlers.want_help(message,self.state,self.bot)
        self.assertIn("бесплатно на сайте",self.body(message))
        buttons=str(message.answer.await_args.kwargs["reply_markup"])
        self.assertIn("/#/help",buttons);self.assertIn("/#/profile/billing",buttons)
        self.assertFalse(services.is_in_queue(self.author))

    async def test_stale_helper_buttons_expired_pro_cannot_mutate_or_read(self):
        rid=self.request();self.pro(self.helper,False)
        for name in ("status","menu","find","ready",f"apply:{rid}",f"view:{rid}"):
            with self.subTest(name=name):
                callback=await self.action(name)
                self.assertIn("PRO",self.body(callback.message))
                self.assertNotIn("Private exact address",self.body(callback.message))
        self.assertFalse(services.is_in_queue(self.helper))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM request_candidates").fetchone()[0],0)
        self.bot.send_message.assert_not_awaited()

    async def test_unlinked_or_group_callbacks_cannot_help(self):
        rid=self.request()
        group=self.callback(f"helper:apply:{rid}");group.message.chat.type="group"
        await handlers.cb_helper_management(group,self.bot)
        self.assertIn("личном",group.answer.await_args.args[0])
        unlinked=self.callback(f"helper:apply:{rid}")
        self.db.execute("UPDATE users SET tg_user_id=NULL WHERE user_id=?",(self.helper,))
        await handlers.cb_helper_management(unlinked,self.bot)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM request_candidates").fetchone()[0],0)

    async def test_ready_uses_callback_actor_and_shares_queue_with_site(self):
        self.request(self.helper)
        await self.action("ready")
        self.assertTrue(services.is_in_queue(self.helper))
        self.assertFalse(services.is_in_queue(999999))
        status=await self.action("status")
        self.assertIn("включена",self.body(status.message))

    async def test_matching_hides_exact_address_and_uses_saved_categories(self):
        services.set_helper_categories(self.helper,["tech"])
        tech=self.request()
        self.request(self.other,category="pets")
        self.request(self.helper)
        callback=await self.action("find")
        text=self.body(callback.message)
        self.assertIn("Помочь с компьютером",text)
        self.assertNotIn("Private exact address",text);self.assertNotIn("Private task details",text)
        buttons=" ".join(str(call.kwargs.get("reply_markup")) for call in callback.message.answer.await_args_list)
        self.assertIn("helper:apply:"+str(tech),buttons)
        self.assertEqual(buttons.count("helper:apply:"),1)

    async def test_apply_opens_chat_notifies_free_author_once_and_never_assigns(self):
        self.request(self.helper)
        rid=self.request()
        await self.action(f"apply:{rid}")
        self.assertEqual(self.db.execute("SELECT status FROM request_candidates WHERE request_id=? AND candidate_id=?",(rid,self.helper)).fetchone()[0],"applied")
        self.assertEqual(database.get_request(rid)["status"],"open")
        self.assertIsNone(database.get_request(rid)["helper_id"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM chats WHERE request_id=?",(rid,)).fetchone()[0],1)
        self.assertEqual(self.bot.send_message.await_count,1)
        self.assertEqual(self.bot.send_message.await_args.args[0],self.tg(self.author))
        self.assertIn("Выбрать помощника на сайте",str(self.bot.send_message.await_args.kwargs["reply_markup"]))
        await self.action(f"apply:{rid}")
        self.assertEqual(self.bot.send_message.await_count,1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM request_events WHERE request_id=? AND event_type='helper_applied'",(rid,)).fetchone()[0],1)

    async def test_unfunded_paid_request_is_not_offered_and_cannot_be_applied(self):
        rid=self.request(reward_rub=1000)
        callback=await self.action(f"apply:{rid}")
        self.assertIn("недоступна",callback.answer.await_args.args[0])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM request_candidates").fetchone()[0],0)
        database.wallet_add_entry(self.author,5000,"test","Synthetic funds","bot-help-funds")
        services.reserve_request_reward(rid,self.author,1150)
        await self.action(f"apply:{rid}")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM request_candidates").fetchone()[0],1)
        self.assertEqual(database.wallet_summary(self.helper)["test_balance_rub"],0)

    async def test_tracking_shows_own_application_and_refuses_foreign_details(self):
        rid=self.request();services.apply_to_request(rid,self.helper)
        callback=await self.action("status")
        self.assertIn("Ожидают выбора автора: 1",self.body(callback.message))
        detail=await self.action(f"view:{rid}")
        self.assertIn("Ожидает выбора автора",self.body(detail.message))
        self.assertIn("Отозвать отклик",str(detail.message.answer.await_args.kwargs["reply_markup"]))
        # Grant access to ensure this is object ownership, not just a PRO denial.
        self.pro(self.other)
        foreign=await self.action(f"view:{rid}",self.other)
        self.assertIn("недоступна",foreign.answer.await_args.args[0])

    async def test_busy_helper_cannot_join_second_job_but_status_stays_useful(self):
        active=self.request();services.accept_open_request(active,self.helper)
        second=self.request(self.other)
        await self.action(f"apply:{second}")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM request_candidates WHERE request_id=?",(second,)).fetchone()[0],0)
        status=await self.action("status")
        self.assertIn("Сейчас вы помогаете",self.body(status.message))
        buttons=str(status.message.answer.await_args.kwargs["reply_markup"])
        self.assertIn("cancel_req:"+str(active),buttons)
        self.assertNotIn("finish:",buttons)

    async def test_pausing_invites_retains_application_and_free_withdrawal(self):
        rid=self.request();services.apply_to_request(rid,self.helper);services.add_to_queue(self.helper)
        callback=self.callback("leave_queue")
        await handlers.cb_leave_queue(callback)
        self.assertFalse(services.is_in_queue(self.helper))
        self.assertEqual(len(services.get_helper_applications(self.helper)),1)
        self.assertIn("продолжают действовать",callback.message.edit_text.await_args.args[0])
        token=services.get_helper_applications(self.helper)[0]["application_token"]
        self.pro(self.helper,False)
        await handlers.cb_application_cancel(self.callback(f"ac:{rid}:{self.helper}:{token}"),self.bot)
        self.assertEqual(len(services.get_helper_applications(self.helper)),0)
        self.assertEqual(self.bot.send_message.await_args.args[0],self.tg(self.author))

    async def test_existing_invitation_consent_remains_free_after_expiry(self):
        rid=self.request();services.add_to_queue(self.helper);self.assertTrue(services.offer_helper(rid,self.helper))
        token=services.get_current_helper_offer(rid)["offer_token"]
        self.pro(self.helper,False)
        await handlers.cb_helper_offer_response(self.callback(f"offer:accept:{rid}:{token}"),self.bot)
        self.assertEqual(database.get_request(rid)["helper_id"],self.helper)
        self.assertEqual(database.get_request(rid)["status"],"in_progress")
        self.assertGreaterEqual(self.bot.send_message.await_count,2)

    async def test_helper_cancellation_notifies_free_author_and_retains_history(self):
        rid=self.request();services.accept_open_request(rid,self.helper)
        await handlers.cb_cancel_request(self.callback("cancel_req:"+str(rid)),self.bot)
        self.assertEqual(database.get_request(rid)["status"],"cancelled")
        self.assertEqual(self.bot.send_message.await_args.args[0],self.tg(self.author))
        self.assertIn("Помощник сообщил",self.bot.send_message.await_args.args[1])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM chats WHERE request_id=?",(rid,)).fetchone()[0],1)

    async def test_paid_helper_cancellation_returns_full_reserve_without_payout(self):
        rid=self.request(reward_rub=1000)
        database.wallet_add_entry(self.author,2000,"test","Synthetic funds","paid-help-cancel")
        services.reserve_request_reward(rid,self.author,1150)
        self.assertEqual(services.accept_open_request(rid,self.helper),"created")
        await handlers.cb_cancel_request(self.callback("cancel_req:"+str(rid)),self.bot)
        self.assertEqual(database.wallet_summary(self.author)["test_balance_rub"],2000)
        self.assertEqual(database.wallet_summary(self.helper)["test_balance_rub"],0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM platform_commissions").fetchone()[0],0)
        self.assertEqual(database.get_request(rid)["reward_payment_status"],"wallet_refunded")
        self.assertEqual(self.bot.send_message.await_args.args[0],self.tg(self.author))

    async def test_author_cancellation_notifies_expired_pending_helper_once(self):
        self.pro(self.author);rid=self.request();services.apply_to_request(rid,self.helper)
        self.pro(self.helper,False)
        await handlers.cb_cancel_request(self.callback("cancel_req:"+str(rid),self.author),self.bot)
        self.assertEqual(self.bot.send_message.await_count,1)
        self.assertEqual(self.bot.send_message.await_args.args[0],self.tg(self.helper))
        await handlers.cb_cancel_request(self.callback("cancel_req:"+str(rid),self.author),self.bot)
        self.assertEqual(self.bot.send_message.await_count,1)
