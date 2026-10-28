"""Paid-only Telegram work actions and opt-in reminders; never contact Telegram."""
import asyncio
from datetime import datetime,timedelta,timezone
import json
import os
import sqlite3
import threading
import unittest
import uuid
from unittest.mock import AsyncMock,patch

from aiogram.types import Message,Chat,User,CallbackQuery
from hpoint import database,commercial,work_bot,bot_work_ui,keyboards,handlers


class WorkBotCases:
    def prepare(self,db):
        self.db=db
        self.patches=[patch.object(database,"db",db),patch.object(handlers,"db",db),patch.object(database,"REGISTRATION_BONUS_RUB",0)]
        for item in self.patches:item.start()
        database.init_db()
        for uid,tg in ((-101,1001),(-202,2002),(-303,3003)):
            database.create_user(uid,"Synthetic member",web_verified=True,tg_user_id=tg)
            db.execute("UPDATE users SET email=?,email_verified=1 WHERE user_id=?",(f"person{abs(uid)}@example.test",uid))
        commercial.save_profile(db,-101,{"kind":"trainer","title":"Synthetic work"})
        self.client=commercial.save_client(db,-101,{"name":"Private client","contact":"private@example.test","notes":"PRIVATE HEALTH NOTE"})["id"]
        self.at=datetime.now(timezone.utc)

    def close(self):
        for item in reversed(self.patches):item.stop()
        self.db.close()

    def pay(self):
        self.db.execute("UPDATE commercial_profiles SET paid_until=? WHERE user_id=-101",((self.at+timedelta(days=30)).isoformat(),))

    def member(self):
        invitation=commercial.post_action(self.db,-101,"/api/commercial/team/invite",{"email":"person202@example.test"})["id"]
        commercial.post_action(self.db,-202,"/api/commercial/team/accept",{"invitation_id":invitation})

    def booking(self,person=-101,minutes=30,**changes):
        return commercial.save_booking(self.db,-101,{"client_id":self.client,"title":"Synthetic booking","starts_at":(self.at+timedelta(minutes=minutes)).isoformat(),"duration_minutes":15,"assignee_id":person,"notes":"PRIVATE HEALTH NOTE",**changes})["id"]

    def test_trial_and_pro_do_not_unlock_work_bot(self):
        self.assertFalse(work_bot.has_paid_access(self.db,-101))
        self.db.execute("UPDATE users SET pro_until=? WHERE user_id=-101",((self.at+timedelta(days=30)).isoformat(),))
        self.assertFalse(work_bot.has_paid_access(self.db,-101))
        self.assertNotIn(work_bot.WORK_BUTTON,str(keyboards.main_menu_kb(-101)))
        database.wallet_add_entry(-101,500,"synthetic_test","Synthetic test funds","work-bot-subscription-credit",test_amount_rub=500)
        commercial.renew(self.db,-101,"work-bot-subscription-paid")
        self.assertTrue(work_bot.has_paid_access(self.db,-101))
        self.assertIn(work_bot.WORK_BUTTON,str(keyboards.main_menu_kb(-101)))

    def test_paid_team_access_closes_after_leaving_expiry_unlink_or_block(self):
        self.pay();self.member()
        self.assertTrue(work_bot.has_paid_access(self.db,-202))
        commercial.post_action(self.db,-202,"/api/commercial/team/leave",{"owner_id":-101})
        self.assertFalse(work_bot.has_paid_access(self.db,-202))
        self.db.execute("UPDATE commercial_profiles SET paid_until=? WHERE user_id=-101",((self.at-timedelta(seconds=1)).isoformat(),))
        self.assertFalse(work_bot.has_paid_access(self.db,-101))
        self.pay();self.db.execute("UPDATE users SET tg_user_id=NULL WHERE user_id=-101")
        self.assertFalse(work_bot.has_paid_access(self.db,-101))
        self.db.execute("UPDATE users SET tg_user_id=1001,is_blocked=1 WHERE user_id=-101")
        self.assertFalse(work_bot.has_paid_access(self.db,-101))

    def test_agenda_contains_only_authorised_titles_not_private_crm(self):
        self.pay();self.member()
        own=self.booking(-202);other=self.booking(-101)
        data=work_bot.agenda(self.db,-202,-101)
        self.assertEqual([row["id"] for row in data["bookings"]],[own])
        text=json.dumps(data)
        for private in ("PRIVATE HEALTH NOTE","private@example.test","Private client"):
            self.assertNotIn(private,text)
        self.assertEqual(len(work_bot.agenda(self.db,-101)["bookings"]),2)
        self.assertNotEqual(own,other)

    def test_old_or_other_staff_rows_do_not_hide_future_personal_agenda(self):
        self.pay();self.member()
        for index in range(305):
            self.db.execute("INSERT INTO commercial_bookings(owner_id,client_id,title,starts_at,assignee_id) VALUES(?,?,?,?,?)",(-101,self.client,"Past synthetic booking",(self.at-timedelta(days=10,minutes=index)).isoformat(),-202))
        wanted=self.booking(-202)
        self.assertEqual([r["id"] for r in work_bot.agenda(self.db,-202,-101)["bookings"]],[wanted])

    def test_completion_is_idempotent_and_never_spends_money(self):
        self.pay();item=self.booking()
        before=self.db.execute("SELECT COUNT(*) n FROM wallet_transactions").fetchone()["n"]
        self.assertTrue(work_bot.complete_item(self.db,-101,-101,"booking",item)["changed"])
        self.assertFalse(work_bot.complete_item(self.db,-101,-101,"booking",item)["changed"])
        self.assertEqual(self.db.execute("SELECT status FROM commercial_bookings WHERE id=?",(item,)).fetchone()["status"],"completed")
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM wallet_transactions").fetchone()["n"],before)

    def test_other_assignees_and_organisations_cannot_be_completed(self):
        self.pay();self.member();item=self.booking(-101)
        with self.assertRaises(PermissionError):work_bot.complete_item(self.db,-202,-101,"booking",item)
        with self.assertRaises(PermissionError):work_bot.complete_item(self.db,-303,-101,"booking",item)
        self.db.execute("UPDATE commercial_profiles SET paid_until='2020-01-01T00:00:00+00:00' WHERE user_id=-101")
        with self.assertRaises(PermissionError):work_bot.complete_item(self.db,-101,-101,"booking",item)

    def test_reminders_are_opt_in_and_sent_claims_are_not_repeated(self):
        self.pay();self.booking()
        self.assertEqual(work_bot.collect_reminders(self.db,self.at),[])
        work_bot.set_preferences(self.db,-101,True,60)
        jobs=work_bot.collect_reminders(self.db,self.at)
        self.assertEqual(len(jobs),1)
        self.assertNotIn("PRIVATE HEALTH NOTE",work_bot.reminder_text(jobs[0]))
        work_bot.finish_reminder(self.db,jobs[0],True)
        self.assertEqual(work_bot.collect_reminders(self.db,self.at+timedelta(minutes=5)),[])

    def test_cancelled_unassigned_other_and_too_late_records_are_not_reminded(self):
        self.pay();self.member()
        self.booking(-202);self.booking(-101,minutes=90);self.booking(-101,minutes=15,status="cancelled")
        work_bot.set_preferences(self.db,-101,True,60)
        self.assertEqual(work_bot.collect_reminders(self.db,self.at),[])
        self.assertEqual(work_bot.collect_reminders(self.db,self.at+timedelta(minutes=100)),[])

    def test_failed_delivery_has_backoff_and_bounded_retries(self):
        self.pay();self.booking();work_bot.set_preferences(self.db,-101,True,60)
        for attempt in range(3):
            jobs=work_bot.collect_reminders(self.db,self.at+timedelta(minutes=4*attempt))
            self.assertEqual(len(jobs),1)
            work_bot.finish_reminder(self.db,jobs[0],False)
            self.assertEqual(work_bot.collect_reminders(self.db,self.at+timedelta(minutes=4*attempt,seconds=10)),[])
        self.assertEqual(work_bot.collect_reminders(self.db,self.at+timedelta(minutes=13)),[])

    def test_revocation_or_disabled_preferences_prevent_future_claims(self):
        self.pay();self.member();self.booking(-202)
        work_bot.set_preferences(self.db,-202,True)
        commercial.post_action(self.db,-101,"/api/commercial/team/remove",{"owner_id":-101,"user_id":-202})
        self.assertEqual(work_bot.collect_reminders(self.db,self.at),[])
        with self.assertRaises(PermissionError):work_bot.set_preferences(self.db,-202,True)


class SQLiteWorkBot(WorkBotCases,unittest.TestCase):
    def setUp(self):
        db=sqlite3.connect(":memory:",isolation_level=None,check_same_thread=False);db.row_factory=sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON");self.prepare(db)
    def tearDown(self):self.close()


@unittest.skipUnless(os.environ.get("HPOINT_TEST_DATABASE_URL"),"requires isolated PostgreSQL test database")
class PostgreSQLWorkBot(WorkBotCases,unittest.TestCase):
    def setUp(self):
        from test_postgres import IsolatedPostgres
        self.schema="work_bot_qa_"+uuid.uuid4().hex;url=os.environ["HPOINT_TEST_DATABASE_URL"]
        self.control=database.PostgresConnection(url);self.control.execute('CREATE SCHEMA "'+self.schema+'"')
        self.prepare(IsolatedPostgres(url,self.schema))
    def tearDown(self):
        self.close();self.control.execute('DROP SCHEMA "'+self.schema+'" CASCADE');self.control.close()


class BotCompanionUI(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture=SQLiteWorkBot();self.fixture.setUp();self.db=self.fixture.db
        self.message=Message(message_id=1,date=datetime.now(),chat=Chat(id=1001,type="private"),from_user=User(id=1001,is_bot=False,first_name="Synthetic"),text=work_bot.WORK_BUTTON)
    def tearDown(self):self.fixture.tearDown()
    async def test_middleware_paid_menu_and_actions_stay_compact(self):
        self.fixture.pay();self.fixture.booking()
        handler=AsyncMock()
        with patch.object(Message,"answer",new_callable=AsyncMock) as answer:
            await handlers.EmailOnlyBotMiddleware()(handler,self.message,{})
            handler.assert_not_awaited()
            text=answer.await_args.args[0]
            self.assertIn("Ближайшие записи",text)
            self.assertNotIn("PRIVATE HEALTH NOTE",text)
            buttons=[b for row in answer.await_args.kwargs["reply_markup"].inline_keyboard for b in row]
            self.assertTrue(any(b.url and "/#/work/-101/" in b.url for b in buttons))
            self.assertLessEqual(len(buttons),7)
        self.assertIsNone(keyboards.MENU_USER.get())
    async def test_group_and_unlinked_identity_cannot_read_work(self):
        self.fixture.pay()
        with patch.object(Message,"answer",new_callable=AsyncMock) as answer:
            group=self.message.model_copy(update={"chat":Chat(id=-5,type="group")})
            await bot_work_ui.handle_event(group,{},database.get_user(-101),self.db)
            self.assertNotIn("Synthetic work",answer.await_args.args[0])
            stranger=self.message.model_copy(update={"from_user":User(id=777,is_bot=False,first_name="Other")})
            await bot_work_ui.handle_event(stranger,{},database.get_user(-101),self.db)
            self.assertNotIn("Synthetic work",answer.await_args.args[0])
    async def test_delivery_uses_fake_bot_and_does_not_repeat(self):
        self.fixture.pay();self.fixture.booking();work_bot.set_preferences(self.db,-101,True)
        bot=type("FakeBot",(),{"send_message":AsyncMock()})()
        await work_bot.deliver_reminders(bot,self.db)
        self.assertEqual(bot.send_message.await_count,1)
        self.assertEqual(bot.send_message.await_args.args[0],1001)
        self.assertNotIn("PRIVATE HEALTH NOTE",bot.send_message.await_args.args[1])
        await work_bot.deliver_reminders(bot,self.db)
        self.assertEqual(bot.send_message.await_count,1)

    async def test_an_old_reminder_can_be_disabled_after_subscription_expiry(self):
        self.fixture.pay();work_bot.set_preferences(self.db,-101,True)
        self.db.execute("UPDATE commercial_profiles SET paid_until='2020-01-01T00:00:00+00:00' WHERE user_id=-101")
        callback=CallbackQuery(id="synthetic",from_user=self.message.from_user,chat_instance="synthetic",message=self.message,data="work:reminders:off")
        with patch.object(Message,"answer",new_callable=AsyncMock),patch.object(CallbackQuery,"answer",new_callable=AsyncMock):
            self.assertTrue(await bot_work_ui.handle_event(callback,{},database.get_user(-101),self.db))
        self.assertFalse(work_bot.preferences(self.db,-101)["enabled"])
