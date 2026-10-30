import asyncio
from datetime import datetime, timedelta, timezone
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from hpoint import database, handlers, services
from hpoint.email_access import has_verified_email, link_owner_has_verified_email, telegram_cleanup_preview, cleanup_telegram_only_accounts


class EmailAccess(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:",isolation_level=None)
        self.db.row_factory=sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.patches=[patch.object(module,"db",self.db) for module in (database,handlers,services)]
        self.patches.append(patch.object(database,"REGISTRATION_BONUS_RUB",0))
        for item in self.patches:item.start()
        database.init_db()

    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.db.close()

    def email_user(self,email="synthetic@example.test",telegram=None):
        uid=database.create_web_user("Email participant",email,"hash")
        self.db.execute("UPDATE users SET email_verified=1,tg_user_id=? WHERE user_id=?",(telegram,uid))
        return uid

    def message(self,uid,text="/start"):
        return SimpleNamespace(from_user=SimpleNamespace(id=uid,full_name="Synthetic",username="synthetic"),text=text,answer=AsyncMock())

    def test_email_gate_is_strict(self):
        self.assertFalse(has_verified_email(None))
        self.assertFalse(has_verified_email({"email":None,"email_verified":1}))
        self.assertFalse(has_verified_email({"email":"person@example.test","email_verified":0}))
        self.assertTrue(has_verified_email({"email":"person@example.test","email_verified":1}))

    def test_start_never_creates_telegram_account(self):
        message=self.message(123)
        state=SimpleNamespace(clear=AsyncMock(),set_state=AsyncMock())
        with patch.object(handlers,"create_user") as create,patch.object(handlers,"complete_telegram_auth_ticket") as ticket:
            asyncio.run(handlers.cmd_start(message,state))
            message.text="/start login_old-token"
            asyncio.run(handlers.cmd_start(message,state))
            create.assert_not_called();ticket.assert_not_called();state.set_state.assert_not_called()
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM users").fetchone()["n"],0)
        self.assertIn("email",message.answer.await_args.args[0])

    def test_old_registration_state_cannot_register(self):
        message=self.message(123,"Old name answer")
        state=SimpleNamespace(clear=AsyncMock())
        with patch.object(handlers,"create_user") as create:
            asyncio.run(handlers.reg_name(message,state))
            create.assert_not_called()
        state.clear.assert_awaited_once()

    def test_website_and_games_never_issue_login_ticket(self):
        message=self.message(123,"/website")
        state=SimpleNamespace(clear=AsyncMock())
        with patch.object(handlers,"create_web_login_ticket") as create:
            asyncio.run(handlers.website(message,state))
            url=handlers._game_website_url(123,"crossing")
            create.assert_not_called()
        self.assertNotIn("auth/telegram",url)
        self.assertNotIn("ticket",url)

    def test_stable_email_profile_is_resolved_from_telegram_transport(self):
        uid=self.email_user(telegram=123)
        self.assertNotEqual(uid,123)
        self.assertEqual(handlers.resolve_profile_id(123),uid)
        message=self.message(123)
        state=SimpleNamespace(clear=AsyncMock())
        self.assertTrue(asyncio.run(handlers.ensure_registered(message,state)))
        handler=AsyncMock(return_value="handled")
        self.assertEqual(asyncio.run(handlers.EmailOnlyBotMiddleware()(handler,message,{})),"handled")

    def test_middleware_blocks_legacy_telegram_profile_without_email(self):
        database.create_user(123,"Telegram-only")
        message=self.message(123,"Create help")
        handler=AsyncMock()
        asyncio.run(handlers.EmailOnlyBotMiddleware()(handler,message,{}))
        handler.assert_not_awaited()
        self.assertIn("email",message.answer.await_args.args[0])

    def test_link_requires_verified_email_and_keeps_user_id(self):
        uid=self.email_user()
        code=database.create_link_code(uid)
        self.assertTrue(link_owner_has_verified_email(self.db,code))
        self.assertEqual(database.link_by_code(code,123),(True,"linked"))
        self.assertIsNotNone(database.get_user(uid))
        self.assertIsNone(database.get_user(123))
        self.assertEqual(handlers.resolve_profile_id(123),uid)
        self.assertEqual(database.detach_telegram_to_web_profile(uid),uid)
        self.assertIsNone(database.get_user(uid)["tg_user_id"])

    def test_unverified_email_cannot_link(self):
        uid=database.create_web_user("Unverified","unverified@example.test","hash")
        code=database.create_link_code(uid)
        self.assertFalse(link_owner_has_verified_email(self.db,code))
        self.assertFalse(database.link_by_code(code,123)[0])

    def test_cleanup_requires_backup_and_is_scoped_to_explicit_telegram(self):
        uid=self.email_user(telegram=124)
        pure_email=database.create_web_user("Not verified","pending@example.test","hash")
        database.create_user(123,"Telegram-only")
        self.assertEqual(telegram_cleanup_preview(self.db)["delete_user_ids"],[123])
        with self.assertRaises(ValueError):cleanup_telegram_only_accounts(self.db,database.wallet_add_entry)
        result=cleanup_telegram_only_accounts(self.db,database.wallet_add_entry,backup_confirmed=True)
        self.assertEqual(result["deleted_users"],1)
        self.assertIsNone(database.get_user(123))
        self.assertIsNotNone(database.get_user(uid))
        self.assertIsNotNone(database.get_user(pure_email))
        self.assertEqual(cleanup_telegram_only_accounts(self.db,database.wallet_add_entry,backup_confirmed=True)["deleted_users"],0)

    def test_cleanup_refunds_surviving_email_author_and_ends_tg_sessions(self):
        owner=self.email_user(telegram=124)
        pure_email=self.email_user("other@example.test")
        database.create_user(123,"Telegram helper")
        database.grant_registration_bonus(owner,500)
        rid=services.create_request(owner,dict(what="Synthetic help",place="Test",time_needed="Today",urgency="Normal",details="Test",reward_rub=400))
        services.reserve_request_reward(rid,owner,460)
        services.accept_open_request(rid,123)
        until=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
        for uid in (owner,pure_email,123):
            self.db.execute("INSERT INTO sessions(token,user_id,expires_at) VALUES(?,?,?)",(str(uid),uid,until))
            database.create_web_login_ticket(uid,"synthetic-ticket"+str(uid))
        result=cleanup_telegram_only_accounts(self.db,database.wallet_add_entry,backup_confirmed=True)
        self.assertEqual(result["ended_sessions"],2)
        self.assertEqual(result["cancelled_requests"],1)
        self.assertEqual(database.wallet_summary(owner)["test_balance_rub"],500)
        self.assertEqual(database.get_request(rid)["status"],"cancelled")
        self.assertIsNone(database.get_request(rid)["helper_id"])
        self.assertEqual(self.db.execute("SELECT user_id FROM sessions").fetchone()["user_id"],pure_email)
        self.assertEqual(self.db.execute("SELECT user_id FROM web_login_tickets").fetchone()["user_id"],pure_email)

    def test_request_display_uses_title_and_author(self):
        owner=self.email_user()
        rid=services.create_request(owner,dict(what="Настроить компьютер",place="Test",time_needed="Today",urgency="Normal",details="Test"))
        text=handlers.request_text(database.get_request(rid))
        self.assertIn("Настроить компьютер",text)
        self.assertIn("Email participant",text)
        self.assertNotIn("№",text)

    def test_cleanup_cascades_new_media_and_commercial_dependencies(self):
        from hpoint import commercial,media,workflow
        commercial.initialize_schema(self.db);media.initialize_schema(self.db);workflow.initialize_schema(self.db)
        database.create_user(123,"Telegram-only")
        rid=services.create_request(123,dict(what="Old task",place="Test",time_needed="Today",urgency="Normal",details="Test"))
        self.db.execute("INSERT INTO photos(id,owner_id,request_id,mime,content_base64,width,height) VALUES('synthetic-photo',123,?,'image/jpeg','AA==',1,1)",(rid,))
        self.db.execute("INSERT INTO commercial_profiles(user_id,kind,title,trial_started_at,trial_until) VALUES(123,'trainer','Old cabinet','2020-01-01T00:00:00+00:00','2020-01-08T00:00:00+00:00')")
        self.db.execute("INSERT INTO commercial_services(id,owner_id,title) VALUES(1,123,'Old service')")
        self.db.execute("INSERT INTO commercial_clients(id,owner_id,name) VALUES(1,123,'Synthetic client')")
        self.db.execute("INSERT INTO commercial_bookings(owner_id,client_id,service_id,title,starts_at) VALUES(123,1,1,'Old booking','2020-01-01T12:00:00+00:00')")
        workflow.record_commission(self.db,rid,400)
        result=cleanup_telegram_only_accounts(self.db,database.wallet_add_entry,backup_confirmed=True)
        self.assertEqual(result["deleted_users"],1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM photos").fetchone()["n"],0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM commercial_bookings").fetchone()["n"],0)
        record=self.db.execute("SELECT * FROM platform_commissions").fetchone()
        self.assertIsNone(record["request_id"])
        self.assertEqual(record["commission_test_rub"],60)
