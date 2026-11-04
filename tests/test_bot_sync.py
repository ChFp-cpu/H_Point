"""Fake Telegram actions use the same email identities and records as the site."""
from datetime import datetime, timedelta, timezone
import os
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import uuid

from aiogram.types import Chat, Message, User
from hpoint import chat_threads, database, handlers, services
from test_bot_personal import MemoryState


class BotSyncCases:
    def prepare(self, connection):
        self.db=connection
        self.patches=[patch.object(module,"db",connection) for module in (database,handlers,services)]
        self.patches.append(patch.object(database,"REGISTRATION_BONUS_RUB",0))
        for item in self.patches:item.start()
        database.init_db()
        identities=[]
        for index in (1,2,3):
            uid=database.create_web_user("Synthetic linked user",f"sync{index}@example.test","hash")
            connection.execute("UPDATE users SET email_verified=1,tg_user_id=? WHERE user_id=?",(index*1001,uid))
            identities.append(uid)
        self.owner,self.helper,self.other=identities
        self.state=MemoryState()
        self.bot=SimpleNamespace(send_message=AsyncMock())

    def close(self):
        for item in reversed(self.patches):item.stop()
        self.db.close()

    def pro(self, uid, active=True):
        self.db.execute("UPDATE users SET pro_until=? WHERE user_id=?",((datetime.now(timezone.utc)+timedelta(days=30 if active else -1)).isoformat(),uid))

    def message(self, text="Synthetic message", uid=None, telegram_id=None):
        tid=telegram_id if telegram_id is not None else database.get_user(uid or self.owner)["tg_user_id"]
        return SimpleNamespace(text=text,from_user=SimpleNamespace(id=tid,username=None),
            chat=SimpleNamespace(type="private"),answer=AsyncMock(),edit_text=AsyncMock(),edit_reply_markup=AsyncMock())

    def callback(self, action, uid=None, telegram_id=None):
        actor=self.message(uid=uid,telegram_id=telegram_id)
        message=self.message(uid=uid,telegram_id=telegram_id)
        message.from_user=SimpleNamespace(id=999999999,username="synthetic_bot")
        return SimpleNamespace(data=action,from_user=actor.from_user,message=message,answer=AsyncMock(),bot=self.bot)

    def request(self, **fields):
        return services.create_request(self.owner,dict(what="Synthetic help",place="Synthetic place",time_needed="Today",urgency="Normal",details="Synthetic conditions",category="tech",**fields))

    async def test_unlinked_transport_cannot_unlink_a_colliding_legacy_profile(self):
        database.create_user(123,"Synthetic legacy profile",email="legacy-sync@example.test",tg_user_id=999999,web_verified=True)
        self.db.execute("UPDATE users SET email_verified=1 WHERE user_id=123")
        event=Message(message_id=1,date=datetime.now(),chat=Chat(id=123,type="private"),
            from_user=User(id=123,is_bot=False,first_name="Synthetic stranger"),text="/unlink")
        async def route(message,data):await handlers.unlink_account(message)
        with patch.object(Message,"answer",new_callable=AsyncMock):
            await handlers.EmailOnlyBotMiddleware()(route,event,{})
        self.assertEqual(database.get_user(123)["tg_user_id"],999999)
        self.assertEqual(handlers.resolve_profile_id(999999),123)

    async def test_own_unlink_keeps_canonical_email_records_and_can_be_relinked(self):
        rid=self.request()
        old_id=self.owner
        await handlers.unlink_account(self.message("/unlink"))
        user=database.get_user(old_id)
        self.assertIsNone(user["tg_user_id"])
        self.assertTrue(user["email_verified"])
        self.assertEqual(database.get_request(rid)["requester_id"],old_id)
        code=database.create_link_code(old_id)
        await handlers.link_account(self.message("/link "+code,telegram_id=1001),self.state)
        await handlers.confirm_telegram_link(self.callback("telegram-link:cancel",telegram_id=1001),self.state)
        await handlers.confirm_telegram_link(self.callback("telegram-link:confirm",telegram_id=1001),self.state)
        self.assertIsNone(database.get_user(old_id)["tg_user_id"])
        await handlers.link_account(self.message("/link "+code,telegram_id=1001),self.state)
        await handlers.confirm_telegram_link(self.callback("telegram-link:confirm",telegram_id=1001),self.state)
        self.assertEqual(handlers.resolve_profile_id(1001),old_id)
        self.assertEqual(database.get_request(rid)["requester_id"],old_id)

    async def test_non_text_review_preserves_state_and_a_later_text_is_shared(self):
        rid=self.request();self.assertEqual(services.accept_open_request(rid,self.helper),"created")
        self.assertTrue(services.complete_request(rid,self.helper,confirmed_by=self.owner))
        await self.state.set_state(handlers.Review.requester_review)
        await self.state.update_data(review_request_id=rid,review_side="requester")
        media=self.message(None)
        await handlers.finish_review(media,self.state,"requester")
        self.assertIn("текстом",media.answer.await_args.args[0])
        self.assertEqual(await self.state.get_state(),handlers.Review.requester_review.state)
        self.assertEqual((await self.state.get_data())["review_request_id"],rid)
        self.assertIsNone(database.get_request(rid)["requester_review"])
        await handlers.finish_review(self.message("Спасибо за помощь"),self.state,"requester")
        self.assertEqual(database.get_request(rid)["requester_review"],"Спасибо за помощь")
        self.assertIsNone(await self.state.get_state())

    async def test_free_chat_with_multiple_active_requests_requires_explicit_target(self):
        self.pro(self.owner)
        first=self.request();second=self.request()
        self.assertEqual(services.accept_open_request(first,self.helper),"created")
        self.assertEqual(services.accept_open_request(second,self.other),"created")
        self.pro(self.owner,False)
        ambiguous=self.message("/chat Which conversation?")
        await handlers.cmd_chat(ambiguous,self.state,self.bot)
        self.assertIn("несколько",ambiguous.answer.await_args.args[0])
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM chat_messages").fetchone()["n"],0)
        await handlers.cmd_chat(self.message(f"/chat #{first} Exact shared reply"),self.state,self.bot)
        first_chat=chat_threads.read_chat(self.db,self.helper,request_id=first)
        second_chat=chat_threads.read_chat(self.db,self.other,request_id=second)
        self.assertEqual([item["text"] for item in first_chat["messages"]],["Exact shared reply"])
        self.assertEqual(second_chat["messages"],[])
        self.assertEqual(self.bot.send_message.await_args.args[0],database.get_user(self.helper)["tg_user_id"])

    async def test_web_reserved_reward_is_finished_only_by_bot_author_and_rated_after_pro_expiry(self):
        self.pro(self.owner);self.pro(self.helper)
        database.wallet_add_entry(self.owner,2000,"test","Synthetic test funds","bot-sync-credit",test_amount_rub=2000)
        rid=self.request(reward_rub=1000)
        self.assertTrue(services.reserve_request_reward(rid,self.owner,1150))
        self.assertEqual(services.accept_open_request(rid,self.helper),"created")
        helper_attempt=self.callback("finish:"+str(rid),self.helper)
        await handlers.cb_finish(helper_attempt,self.bot)
        self.assertIn("автор",helper_attempt.answer.await_args.args[0])
        self.assertEqual(database.get_request(rid)["status"],"in_progress")
        self.assertEqual(database.wallet_summary(self.helper)["test_balance_rub"],0)
        await handlers.cb_finish(self.callback("finish:"+str(rid)),self.bot)
        finished=database.get_request(rid)
        self.assertEqual((finished["status"],finished["reward_payment_status"]),("done","released"))
        self.assertEqual((finished["helper_reward_rub"],finished["commission_rub"]),(1000,150))
        self.assertEqual(database.wallet_summary(self.owner)["test_balance_rub"],850)
        self.assertEqual(database.wallet_summary(self.helper)["test_balance_rub"],1000)
        self.pro(self.owner,False);self.pro(self.helper,False)
        await handlers.cb_rate(self.callback(f"rate:{rid}:5"),self.state)
        await handlers.cb_rate_help(self.callback(f"ratehelp:{rid}:4",self.helper),self.state)
        rated=database.get_request(rid)
        self.assertEqual((rated["requester_rating"],rated["helper_rating"]),(5,4))
        with self.assertRaises(ValueError):chat_threads.send_message(self.db,self.owner,"Late reply",request_id=rid)

    async def test_retired_manual_identity_commands_do_not_create_or_change_requests(self):
        await handlers.cmd_request_identity_verification(self.message("/verifyme"),self.state)
        self.assertIsNone(database.get_identity_verification(self.owner))
        database.request_identity_verification(self.owner)  # Preserved history fixture.
        before=dict(database.get_identity_verification(self.owner))
        self.db.execute("UPDATE users SET role='admin' WHERE user_id=?",(self.owner,))
        await handlers.cmd_verifications(self.message("/verifications"))
        for command in ("/verify ","/rejectverify "):
            await handlers.cmd_review_identity(self.message(command+str(self.owner)),self.bot)
        self.assertEqual(dict(database.get_identity_verification(self.owner)),before)
        self.bot.send_message.assert_not_awaited()
        event=Message(message_id=1,date=datetime.now(),chat=Chat(id=1001,type="private"),
            from_user=User(id=1001,is_bot=False,first_name="Synthetic"),text="/verifyme")
        with patch.object(Message,"answer",new_callable=AsyncMock) as answer:
            self.assertTrue(await handlers.simplified_bot_message(event,{"state":self.state}))
            self.assertIn("закрыта",answer.await_args.args[0])


class SQLiteBotSync(BotSyncCases,unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        connection=sqlite3.connect(":memory:",isolation_level=None,check_same_thread=False)
        connection.row_factory=sqlite3.Row;connection.execute("PRAGMA foreign_keys=ON")
        self.prepare(connection)
    def tearDown(self):self.close()


@unittest.skipUnless(os.environ.get("HPOINT_TEST_DATABASE_URL"),"requires isolated PostgreSQL test database")
class PostgreSQLBotSync(BotSyncCases,unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from test_postgres import IsolatedPostgres
        self.schema="bot_sync_"+uuid.uuid4().hex;url=os.environ["HPOINT_TEST_DATABASE_URL"]
        self.control=database.PostgresConnection(url);self.control.execute('CREATE SCHEMA "'+self.schema+'"')
        self.prepare(IsolatedPostgres(url,self.schema))
    def tearDown(self):
        self.close();self.control.execute('DROP SCHEMA "'+self.schema+'" CASCADE');self.control.close()


if __name__=="__main__":unittest.main()
