"""Real HTTP support boundaries, notification dedup and profile validation.

Synthetic accounts live in a disposable SQLite file. Telegram is mocked and
email providers are never contacted by this suite.
"""
from contextlib import ExitStack, closing
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from hpoint import billing, database, services, web


class SupportHTTP(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.path=Path(self.directory.name)/"support.sqlite3"
        self.db=database.SQLiteConnection(str(self.path));self.stack=ExitStack()
        for module in (database,billing,services,web):self.stack.enter_context(patch.object(module,"db",self.db))
        self.stack.enter_context(patch.object(database,"REGISTRATION_BONUS_RUB",0));database.init_db()
        for uid in (1,2,3,4,5,6):
            database.create_user(uid,"Synthetic member "+str(uid),email=f"private{uid}@example.test",web_verified=True)
            self.db.execute("UPDATE users SET email_verified=?,role=?,is_blocked=?,city='Москва',bio='Сохранённое описание' WHERE user_id=?",(0 if uid==6 else 1,"admin" if uid in (3,4) else "user",1 if uid==5 else 0,uid))
        self.notices=[]
        self.notify=self.stack.enter_context(patch.object(web,"notify_telegram_user",side_effect=self.capture_notice))
        self.tokens={uid:web.new_sess(uid) for uid in (1,2,3,4,5,6)}
        self.server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown();self.thread.join(timeout=3);self.server.server_close();self.stack.close();self.db.close();self.directory.cleanup()

    def capture_notice(self,telegram_id,text,*args,**kwargs):
        # A separate connection can only see the message after its transaction
        # committed. This verifies delivery scheduling cannot precede storage.
        with closing(sqlite3.connect(str(self.path))) as independent:
            count=independent.execute("SELECT COUNT(*) FROM support_messages WHERE sender_role='admin'").fetchone()[0]
        self.notices.append((telegram_id,text,count))

    def request(self,path,uid=None,data=None,expected=200):
        headers={"Content-Type":"application/json","Origin":web.WEB_PUBLIC_URL.rstrip("/")}
        if uid is not None:headers["Cookie"]="hpoint_session="+self.tokens[uid]
        body=json.dumps(data).encode() if data is not None else None
        try:response=urlopen(Request(self.base+path,data=body,headers=headers),timeout=5)
        except HTTPError as error:response=error
        with response:
            payload=json.load(response)
            self.assertEqual(response.status,expected,payload)
            self.assertEqual(payload["ok"],expected==200)
            self.assertIn("no-store",response.headers["Cache-Control"])
            return payload

    def create(self,uid=1,**fields):
        return self.request("/api/support",uid,{"subject":"Вопрос по работе","message":"Исходное приватное сообщение","request_key":"http-support-create"+str(uid),**fields})["ticket_id"]

    def test_support_paths_require_verified_login_and_admin_endpoints_require_role(self):
        gets=("/api/support","/api/support/thread?id=1","/api/admin/support","/api/admin/support/thread?id=1")
        posts=("/api/support","/api/support/reply","/api/support/read","/api/support/status","/api/admin/support/reply","/api/admin/support/read","/api/admin/support/status")
        for path in gets:
            for uid,status in ((None,401),(5,403),(6,401)):
                with self.subTest(path=path,uid=uid):self.request(path,uid,expected=status)
        for path in posts:
            for uid,status in ((None,401),(5,403),(6,401)):
                with self.subTest(path=path,uid=uid):self.request(path,uid,{},status)
        for path in ("/api/admin/support","/api/admin/support/thread?id=1"):
            self.request(path,1,expected=403)
        for path in ("/api/admin/support/reply","/api/admin/support/read","/api/admin/support/status"):
            self.request(path,1,{},403)

    def test_conversation_history_read_state_resolve_and_followup_work_over_http(self):
        ticket=self.create()
        self.assertFalse(self.request("/api/support",1,{"subject":"Вопрос по работе","message":"Исходное приватное сообщение","request_key":"http-support-create1"})["created"])
        self.request(f"/api/support/thread?id={ticket}",2,expected=403)
        self.request(f"/api/support/thread?id={ticket}",3,expected=403)
        self.assertEqual(self.request("/api/support",2)["total"],0)
        self.assertEqual(self.request("/api/admin/support?status=waiting",3)["counts"]["unread"],1)
        detail=self.request(f"/api/admin/support/thread?id={ticket}",3)
        self.request("/api/admin/support/read",3,{"ticket_id":ticket,"last_message_id":detail["last_message_id"]})
        self.assertEqual(self.request("/api/admin/support",3)["counts"]["unread"],0)
        self.assertEqual(self.request("/api/admin/support",4)["counts"]["unread"],1)
        self.request("/api/admin/support/reply",3,{"ticket_id":ticket,"message":"Первый ответ","request_key":"http-support-reply1"})
        self.request("/api/admin/support/reply",3,{"ticket_id":ticket,"message":"Второй ответ","request_key":"http-support-reply2"})
        thread=self.request(f"/api/support/thread?id={ticket}",1)
        self.assertEqual([m["message"] for m in thread["messages"]],["Исходное приватное сообщение","Первый ответ","Второй ответ"])
        self.assertEqual(thread["ticket"]["unread_count"],2)
        self.assertNotIn("user_email",thread["ticket"])
        self.request("/api/support/read",1,{"ticket_id":ticket,"last_message_id":thread["last_message_id"]})
        self.assertEqual(self.request("/api/support?unread=1",1)["total"],0)
        self.request("/api/support/status",1,{"ticket_id":ticket,"status":"resolved"})
        self.request("/api/support/reply",1,{"ticket_id":ticket,"message":"Нужно уточнение","request_key":"http-support-followup"})
        self.assertEqual(self.request(f"/api/support/thread?id={ticket}",1)["ticket"]["status"],"open")
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM wallet_transactions").fetchone()["n"],0)

    def test_reply_retry_schedules_one_mock_notice_only_after_committing(self):
        ticket=self.create();data={"ticket_id":ticket,"message":"Ответ по обращению","request_key":"http-notice-idempotency"}
        result=self.request("/api/admin/support/reply",3,data)
        replay=self.request("/api/admin/support/reply",3,data)
        self.assertTrue(result["created"]);self.assertFalse(replay["created"])
        self.assertEqual(len(self.notices),1)
        self.assertEqual(self.notices[0][0],1)
        self.assertEqual(self.notices[0][2],1)
        self.assertIn("support_ticket="+str(ticket),self.notices[0][1])
        self.request("/api/admin/support/reply",3,{**data,"message":"Другие данные"},400)
        self.assertEqual(len(self.notices),1)
        self.assertEqual(self.request(f"/api/support/thread?id={ticket}",1)["ticket"]["admin_reply"],data["message"])

    def test_bad_inputs_other_threads_pagination_and_dispute_safety(self):
        ticket=self.create();other=self.create(2)
        foreign=self.request(f"/api/support/thread?id={other}",2)["last_message_id"]
        for path,data in (("/api/support",{}),("/api/support/reply",{"ticket_id":ticket,"message":[]}),("/api/support/read",{"ticket_id":ticket,"last_message_id":foreign}),("/api/support/status",{"ticket_id":ticket,"status":"bad"})):
            self.request(path,1,data,400)
        for path in ("/api/support?status=bad","/api/support?limit=101","/api/support?offset=-1",f"/api/support/thread?id={ticket}&after=bad",f"/api/support/thread?id={ticket}&after=1&before=2"):
            self.request(path,1,expected=400)
        for path in ("/api/support/reply","/api/support/read","/api/support/status"):
            self.request(path,2,{"ticket_id":ticket,"message":"Не моё обращение","last_message_id":0,"status":"open"},403)
        self.request("/api/support/thread?id=999999",1,expected=403)
        self.request("/api/support?limit=1",1)
        request=database.insert_id("INSERT INTO requests(requester_id,helper_id,what,place,time_needed,urgency,details,status) VALUES(1,2,'Помощь','Место','Сегодня','Обычная','Описание','in_progress')")
        dispute=database.create_request_dispute(request,1,"Описание проблемы по помощи")
        self.request("/api/admin/support/status",3,{"ticket_id":dispute,"status":"resolved"},400)
        self.assertEqual(self.db.execute("SELECT dispute_status FROM requests WHERE id=?",(request,)).fetchone()["dispute_status"],"open")

    def test_manual_identity_entry_is_disabled_without_erasing_legacy_review(self):
        self.db.execute("INSERT INTO identity_verification_requests(user_id,status) VALUES(1,'pending')")
        before=dict(self.db.execute("SELECT * FROM identity_verification_requests WHERE user_id=1").fetchone())
        self.request("/api/identity-verification",1,{},410)
        self.assertEqual(dict(self.db.execute("SELECT * FROM identity_verification_requests WHERE user_id=1").fetchone()),before)
        user=self.request("/api/me",1)["user"]
        self.assertFalse(user["identity_verification"]["enabled"])
        self.assertEqual(user["identity_verification"]["status"],"disabled")

    def test_profile_fields_are_strict_and_partial_updates_preserve_other_fields(self):
        before=dict(self.db.execute("SELECT name,city,bio FROM users WHERE user_id=1").fetchone())
        for data in ({"name":None},{"name":True},{"name":"x"},{"name":"x"*51},{"city":[]},{"city":"x"*81},{"bio":{}},{"bio":"x"*501}):
            self.request("/api/profile",1,data,400)
            self.assertEqual(dict(self.db.execute("SELECT name,city,bio FROM users WHERE user_id=1").fetchone()),before)
        updated=self.request("/api/profile",1,{"name":"  Новое имя  "})["user"]
        self.assertEqual(updated["name"],"Новое имя");self.assertEqual(updated["city"],before["city"]);self.assertEqual(updated["bio"],before["bio"])
        updated=self.request("/api/profile",1,{"city":""})["user"]
        self.assertEqual(updated["city"],"");self.assertEqual(updated["name"],"Новое имя")


if __name__=="__main__":unittest.main()
