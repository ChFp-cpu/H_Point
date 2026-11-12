"""The bot stays small; account linking remains explicitly cancellable."""
import asyncio
from datetime import datetime
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch

from aiogram.types import Message,Chat,User
from hpoint import database,handlers,keyboards,services


class MemoryState:
    def __init__(self):self.state=None;self.data={}
    async def clear(self):self.state=None;self.data={}
    async def get_state(self):return self.state
    async def get_data(self):return dict(self.data)
    async def set_state(self,value):self.state=value
    async def update_data(self,**kwargs):self.data.update(kwargs)


class SimpleBot(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:",isolation_level=None);self.db.row_factory=sqlite3.Row
        self.patches=[patch.object(module,"db",self.db) for module in (database,handlers,services)]
        self.patches.append(patch.object(database,"REGISTRATION_BONUS_RUB",0))
        for item in self.patches:item.start()
        database.init_db()
        self.uid=database.create_web_user("Synthetic email profile","bot@example.test","hash")
        self.db.execute("UPDATE users SET email_verified=1 WHERE user_id=?",(self.uid,))
        self.state=MemoryState()
    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.db.close()
    def message(self,text="/start",uid=123,chat_type="private"):
        return SimpleNamespace(text=text,from_user=SimpleNamespace(id=uid,username="synthetic"),chat=SimpleNamespace(type=chat_type),answer=AsyncMock())
    def callback(self,action="confirm",uid=123):
        return SimpleNamespace(data="telegram-link:"+action,from_user=SimpleNamespace(id=uid,username="synthetic"),message=self.message(uid=uid),answer=AsyncMock())
    async def prepare_link(self):
        code=database.create_link_code(self.uid)
        message=self.message("/link "+code)
        await handlers.link_account(message,self.state)
        return code,message
    def test_reply_menu_and_guide_have_only_current_controls(self):
        labels=[b.text for row in keyboards.main_menu_kb().keyboard for b in row]
        self.assertEqual(labels,[handlers.BTN_WEBSITE,"💬 Мои чаты",handlers.BTN_NAVIGATOR,handlers.BTN_CANCEL])
        self.assertNotIn("Игры",str(labels))
        self.assertNotIn("Подобрать кандидатов",handlers.BOT_START_OVERVIEW)
        self.assertIn("/cancel",handlers.BOT_GUIDE)
    async def test_link_has_no_effect_until_confirmation(self):
        code,message=await self.prepare_link()
        self.assertIsNone(database.get_user(self.uid)["tg_user_id"])
        self.assertTrue(handlers.link_owner_has_verified_email(self.db,code))
        callback=self.callback()
        await handlers.confirm_telegram_link(callback,self.state)
        self.assertEqual(database.get_user(self.uid)["tg_user_id"],123)
        self.assertIsNone(await self.state.get_state())
        self.assertFalse(handlers.link_owner_has_verified_email(self.db,code))
    async def test_cancel_then_old_confirmation_cannot_link(self):
        await self.prepare_link()
        await handlers.confirm_telegram_link(self.callback("cancel"),self.state)
        await handlers.confirm_telegram_link(self.callback(),self.state)
        self.assertIsNone(database.get_user(self.uid)["tg_user_id"])
    async def test_cancel_command_discards_pending_confirmation(self):
        await self.prepare_link()
        await handlers.cancel_action(self.message("/cancel"),self.state)
        await handlers.confirm_telegram_link(self.callback(),self.state)
        self.assertIsNone(database.get_user(self.uid)["tg_user_id"])
    async def test_expired_confirmation_cannot_link(self):
        await self.prepare_link()
        await self.state.update_data(telegram_link_created_at=handlers.time.time()-301)
        await handlers.confirm_telegram_link(self.callback(),self.state)
        self.assertIsNone(database.get_user(self.uid)["tg_user_id"])
    async def test_website_revoked_code_cannot_be_confirmed(self):
        await self.prepare_link()
        self.db.execute("UPDATE users SET verification_code=NULL,verification_code_hash=NULL,verification_code_expires_at=NULL WHERE user_id=?",(self.uid,))
        await handlers.confirm_telegram_link(self.callback(),self.state)
        self.assertIsNone(database.get_user(self.uid)["tg_user_id"])
    async def test_group_cannot_start_link_flow(self):
        code=database.create_link_code(self.uid)
        await handlers.link_account(self.message("/link "+code,chat_type="group"),self.state)
        self.assertEqual(await self.state.get_data(),{})
        self.assertIsNone(database.get_user(self.uid)["tg_user_id"])
    async def test_expired_pro_form_is_redirected_without_clearing_draft(self):
        message=Message(message_id=1,date=datetime.now(),chat=Chat(id=123,type="private"),from_user=User(id=123,is_bot=False,first_name="Synthetic"),text=handlers.BTN_NEED_HELP)
        await self.state.set_state("HelpRequest:details")
        with patch.object(Message,"answer",new_callable=AsyncMock) as answer:
            self.assertTrue(await handlers.simplified_bot_message(message,{"state":self.state}))
            self.assertIn("на сайте",answer.await_args.args[0])
        self.assertEqual(await self.state.get_state(),"HelpRequest:details")
    async def test_chat_command_and_pending_review_still_reach_handler(self):
        message=Message(message_id=1,date=datetime.now(),chat=Chat(id=123,type="private"),from_user=User(id=123,is_bot=False,first_name="Synthetic"),text="/chat hello")
        self.assertFalse(await handlers.simplified_bot_message(message,{"state":self.state}))
        await self.state.set_state(handlers.Review.requester_review.state)
        review=message.model_copy(update={"text":"Synthetic review"})
        self.assertFalse(await handlers.simplified_bot_message(review,{"state":self.state}))
