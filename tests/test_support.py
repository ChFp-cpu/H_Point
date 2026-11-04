"""Durable support history, privacy, idempotency, read cursors and disputes."""
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

from hpoint import database, support as s


class SupportCases:
    def prepare(self, db):
        self.db = db
        self.patches = [patch.object(database, "db", db), patch.object(database, "REGISTRATION_BONUS_RUB", 0)]
        for item in self.patches:
            item.start()
        database.init_db()
        for uid in (1, 2, 3, 4):
            database.create_user(uid, "Участник "+str(uid), email=f"private{uid}@example.test", web_verified=True)
            db.execute("UPDATE users SET email_verified=1,role=? WHERE user_id=?", ("admin" if uid in (3, 4) else "user", uid))

    def close(self):
        self.db.close()
        for item in reversed(self.patches):
            item.stop()

    def create(self, uid=1, message="Исходное сообщение", key=None, subject="Нужна поддержка"):
        return s.create(self.db, uid, {"subject": subject, "message": message, "request_key": key or uuid.uuid4().hex})["ticket_id"]

    def reply(self, ticket, uid=1, message="Новое сообщение", admin=False, key=None):
        return s.reply(self.db, uid, {"ticket_id": ticket, "message": message, "request_key": key or uuid.uuid4().hex}, admin)

    def test_legacy_migration_and_new_replies_keep_history_without_duplicate_snapshots(self):
        ticket = database.insert_id("INSERT INTO support_tickets(user_id,subject,message,admin_reply,replied_by,replied_at) VALUES(1,'Старая тема','Старое письмо','Старый ответ',3,'2020-01-02 00:00:00')")
        s.initialize_schema(self.db);s.initialize_schema(self.db)
        self.assertEqual([m["message"] for m in s.detail(self.db, 1, ticket)["messages"]], ["Старое письмо", "Старый ответ"])
        self.reply(ticket, 3, "Новый ответ", True)
        s.initialize_schema(self.db);s.initialize_schema(self.db)
        messages = s.detail(self.db, 1, ticket)["messages"]
        self.assertEqual([m["message"] for m in messages], ["Старое письмо", "Старый ответ", "Новый ответ"])
        row = self.db.execute("SELECT * FROM support_tickets WHERE id=?", (ticket,)).fetchone()
        self.assertEqual((row["message"], row["admin_reply"]), ("Старое письмо", "Новый ответ"))

    def test_verified_email_scope_blocked_and_admin_mode_are_strict(self):
        ticket = self.create()
        for call in (lambda:s.detail(self.db, 2, ticket), lambda:s.detail(self.db, 3, ticket), lambda:s.detail(self.db, 2, ticket, True),
                     lambda:self.reply(ticket, 2), lambda:s.mark_read(self.db, 2, {"ticket_id":ticket,"last_message_id":0})):
            with self.assertRaises(PermissionError):call()
        self.assertEqual(s.list_tickets(self.db, 2)["total"], 0)
        self.assertEqual(s.detail(self.db, 3, ticket, True)["ticket"]["user_email"], "private1@example.test")
        self.assertNotIn("user_email", s.detail(self.db, 1, ticket)["ticket"])
        self.db.execute("UPDATE users SET email_verified=0 WHERE user_id=1")
        with self.assertRaises(PermissionError):s.detail(self.db, 1, ticket)
        self.db.execute("UPDATE users SET is_blocked=1 WHERE user_id=3")
        with self.assertRaises(PermissionError):s.list_tickets(self.db, 3, True)

    def test_create_reply_keys_are_payload_bound_and_actor_scoped(self):
        data={"subject":"Повторная отправка","message":"Не дублировать","request_key":"support-create-0001"}
        first=s.create(self.db,1,data);again=s.create(self.db,1,data)
        self.assertTrue(first["created"]);self.assertFalse(again["created"]);self.assertEqual(first["ticket_id"],again["ticket_id"])
        with self.assertRaises(ValueError):s.create(self.db,1,{**data,"message":"Другой текст"})
        self.assertTrue(s.create(self.db,2,data)["created"])
        result=self.reply(first["ticket_id"],key="support-reply-00001")
        self.assertFalse(self.reply(first["ticket_id"],key="support-reply-00001")["created"])
        self.assertEqual(len(s.detail(self.db,1,first["ticket_id"])["messages"]),2)
        with self.assertRaises(ValueError):self.reply(first["ticket_id"],message="Изменённый текст",key="support-reply-00001")
        self.assertEqual(result["message_id"],s.detail(self.db,1,first["ticket_id"])["last_message_id"])

    def test_legacy_clients_without_keys_get_short_retry_dedup(self):
        data={"subject":"Безопасный старый клиент","message":"Один текст"}
        first=s.create(self.db,1,data);second=s.create(self.db,1,data)
        self.assertFalse(second["created"]);self.assertEqual(first["ticket_id"],second["ticket_id"])
        reply={"ticket_id":first["ticket_id"],"message":"Продолжение"}
        self.assertTrue(s.reply(self.db,1,reply)["created"])
        self.assertFalse(s.reply(self.db,1,reply)["created"])
        with patch.object(s,"_now",return_value=s._now()+timedelta(seconds=61)):
            self.assertTrue(s.reply(self.db,1,reply)["created"])

    def test_resolve_followup_and_admin_replies_preserve_all_messages(self):
        ticket=self.create();self.reply(ticket,3,"Первый ответ",True);self.reply(ticket,4,"Второй ответ",True)
        self.assertEqual(s.detail(self.db,1,ticket)["ticket"]["status"],"answered")
        s.set_status(self.db,1,{"ticket_id":ticket,"status":"resolved"})
        self.assertFalse(s.set_status(self.db,1,{"ticket_id":ticket,"status":"resolved"})["changed"])
        self.reply(ticket,message="Проблема осталась")
        detail=s.detail(self.db,1,ticket)
        self.assertEqual(detail["ticket"]["status"],"open")
        self.assertEqual(detail["ticket"]["awaiting"],"admin")
        self.assertEqual([m["message"] for m in detail["messages"] if m["author_role"]!="system"],["Исходное сообщение","Первый ответ","Второй ответ","Проблема осталась"])
        self.assertEqual(detail["ticket"]["admin_reply"],"Второй ответ")

    def test_read_markers_are_private_monotonic_and_do_not_read_future_replies(self):
        ticket=self.create();initial=s.detail(self.db,1,ticket)["last_message_id"]
        self.assertEqual(s.list_tickets(self.db,3,True)["counts"]["unread"],1)
        s.mark_read(self.db,3,{"ticket_id":ticket,"last_message_id":initial},True)
        self.assertEqual(s.list_tickets(self.db,3,True)["counts"]["unread"],0)
        self.assertEqual(s.list_tickets(self.db,4,True)["counts"]["unread"],1)
        reply=self.reply(ticket,3,"Ответ поддержки",True)["message_id"]
        self.assertEqual(s.detail(self.db,1,ticket)["ticket"]["unread_count"],1)
        self.assertEqual(s.detail(self.db,1,ticket)["ticket"]["unread_count"],1) # GET is not read.
        s.mark_read(self.db,1,{"ticket_id":ticket,"last_message_id":reply})
        s.mark_read(self.db,1,{"ticket_id":ticket,"last_message_id":initial})
        self.assertEqual(s.detail(self.db,1,ticket)["ticket"]["unread_count"],0)
        self.reply(ticket,4,"Ещё один ответ",True)
        self.assertEqual(s.detail(self.db,1,ticket)["ticket"]["unread_count"],1)
        other=self.create(2)
        foreign=s.detail(self.db,2,other)["last_message_id"]
        with self.assertRaises(ValueError):s.mark_read(self.db,1,{"ticket_id":ticket,"last_message_id":foreign})

    def test_thread_pagination_returns_stable_ascending_pages(self):
        ticket=self.create()
        for index in range(9):self.reply(ticket,message="Сообщение "+str(index))
        whole=s.detail(self.db,1,ticket)["messages"]
        latest=s.detail(self.db,1,ticket,limit=3)
        self.assertEqual([m["id"] for m in latest["messages"]],[m["id"] for m in whole[-3:]])
        self.assertTrue(latest["has_older"]);self.assertFalse(latest["has_newer"])
        older=s.detail(self.db,1,ticket,before=latest["first_message_id"],limit=3)
        self.assertEqual([m["id"] for m in older["messages"]],[m["id"] for m in whole[-6:-3]])
        newer=s.detail(self.db,1,ticket,after=whole[0]["id"],limit=3)
        self.assertEqual([m["id"] for m in newer["messages"]],[m["id"] for m in whole[1:4]])
        self.assertTrue(newer["has_newer"])

    def test_search_pagination_status_waiting_and_unread_counts_respect_scope(self):
        first=self.create(message="Русский текст в истории",subject="Сметы")
        second=self.create(subject="Пароль")
        self.create(2,message="PRIVATE OTHER TEXT",subject="Другая приватная тема")
        self.reply(first,3,"Проверьте новую версию",True)
        self.assertEqual(s.list_tickets(self.db,1,query="РУССКИЙ")["total"],1)
        self.assertEqual(s.list_tickets(self.db,1,query="PRIVATE OTHER")["total"],0)
        waiting=s.list_tickets(self.db,1,status="waiting")
        self.assertEqual([t["id"] for t in waiting["tickets"]],[first])
        self.assertEqual(s.list_tickets(self.db,3,True)["counts"]["waiting_for_admin"],2)
        page=s.list_tickets(self.db,3,True,limit=1)
        self.assertTrue(page["has_more"])
        next_page=s.list_tickets(self.db,3,True,offset=1,limit=1)
        self.assertNotEqual(page["tickets"][0]["id"],next_page["tickets"][0]["id"])
        self.assertEqual(s.list_tickets(self.db,1,unread=True)["total"],1)
        self.assertEqual(s.detail(self.db,1,second)["ticket"]["unread_count"],0)

    def test_dispute_creation_and_resolution_join_history_without_changing_money(self):
        request=database.insert_id("INSERT INTO requests(requester_id,helper_id,what,place,time_needed,urgency,details,status) VALUES(1,2,'Помощь','Место','Сегодня','Обычная','Описание','in_progress')")
        ticket=database.create_request_dispute(request,1,"Нужна помощь поддержки")
        self.assertEqual(s.detail(self.db,1,ticket)["messages"][0]["message"],"Нужна помощь поддержки")
        self.assertFalse(s.detail(self.db,1,ticket)["permissions"]["can_resolve"])
        with self.assertRaises(ValueError):s.set_status(self.db,3,{"ticket_id":ticket,"status":"resolved"},True)
        self.assertTrue(database.resolve_request_dispute(3,request,"Решение по спору"))
        result=s.detail(self.db,1,ticket)
        self.assertEqual([m["message"] for m in result["messages"]],["Нужна помощь поддержки","Решение по спору"])
        self.assertEqual(result["ticket"]["status"],"resolved")
        self.reply(ticket,message="Уточнение по решению")
        self.assertEqual(self.db.execute("SELECT dispute_status FROM requests WHERE id=?",(request,)).fetchone()["dispute_status"],"resolved")
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM wallet_transactions").fetchone()["n"],0)

    def test_request_cancellation_is_recorded_once_in_support_history(self):
        request=database.insert_id("INSERT INTO requests(requester_id,helper_id,what,place,time_needed,urgency,details,status) VALUES(1,2,'Помощь','Место','Сегодня','Обычная','Описание','in_progress')")
        ticket=database.create_request_dispute(request,1,"Нужна помощь поддержки")
        self.assertTrue(database.admin_cancel_request(3,request,"Согласованная отмена")[0])
        self.assertFalse(database.admin_cancel_request(3,request,"Повтор отмены")[0])
        detail=s.detail(self.db,1,ticket)
        self.assertEqual(detail["ticket"]["status"],"resolved")
        self.assertEqual(len(detail["messages"]),2)
        self.assertIn("Согласованная отмена",detail["messages"][-1]["message"])
        self.assertEqual(detail["messages"][-1]["author_role"],"system")
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM wallet_transactions").fetchone()["n"],0)

    def test_literal_search_does_not_turn_wildcards_into_unfiltered_records(self):
        self.create(subject="Обычная тема");literal=self.create(subject="Цена 15% и строка_a")
        self.assertEqual([t["id"] for t in s.list_tickets(self.db,1,query="15%")["tickets"]],[literal])
        self.assertEqual(s.list_tickets(self.db,1,query="_")["total"],1)
        self.assertEqual(s.list_tickets(self.db,1,query="%_")["total"],0)

    def test_invalid_data_limits_and_rollback_leave_no_partial_ticket(self):
        for data in ([],{"subject":[],"message":"Текст"},{"subject":"Тема","message":True},{"subject":"Тема","message":"x"*4001},{"subject":"Тема","message":"Текст","request_key":"short"}):
            with self.assertRaises(ValueError):s.create(self.db,1,data)
        for values in ({"status":[]},{"limit":True},{"offset":-1},{"query":[]},{"unread":"yes"}):
            with self.assertRaises(ValueError):s.list_tickets(self.db,1,**values)
        with patch.object(s,"_append",side_effect=RuntimeError("write failure")):
            with self.assertRaises(RuntimeError):self.create()
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM support_tickets").fetchone()["n"],0)
        for index in range(20):self.create(subject="Обращение "+str(index))
        with self.assertRaises(ValueError):self.create(subject="Сверх лимита")
        self.assertEqual(s.list_tickets(self.db,1)["total"],20)


class SQLiteSupport(SupportCases,unittest.TestCase):
    def setUp(self):
        db=sqlite3.connect(":memory:",isolation_level=None);db.row_factory=sqlite3.Row;db.execute("PRAGMA foreign_keys=ON");self.prepare(db)
    def tearDown(self):self.close()


@unittest.skipUnless(os.environ.get("HPOINT_TEST_DATABASE_URL"),"requires isolated PostgreSQL test database")
class PostgreSQLSupport(SupportCases,unittest.TestCase):
    def setUp(self):
        from test_postgres import IsolatedPostgres
        self.schema="support_qa_"+uuid.uuid4().hex;url=os.environ["HPOINT_TEST_DATABASE_URL"]
        self.control=database.PostgresConnection(url);self.control.execute('CREATE SCHEMA "'+self.schema+'"')
        self.prepare(IsolatedPostgres(url,self.schema))
    def tearDown(self):
        self.close();self.control.execute('DROP SCHEMA "'+self.schema+'" CASCADE');self.control.close()


class SupportRaces:
    prepare=SupportCases.prepare
    close=SupportCases.close
    create=SupportCases.create
    reply=SupportCases.reply

    def race(self,*functions):
        gate=threading.Barrier(len(functions))
        def run(function):
            try:gate.wait(timeout=5);return function()
            finally:self.db.close()
        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            return [future.result(timeout=25) for future in [pool.submit(run,function) for function in functions]]

    def test_parallel_retry_creates_one_ticket_and_one_initial_message(self):
        data={"subject":"Параллельное обращение","message":"Первое сообщение","request_key":"support-race-create1"}
        results=self.race(lambda:s.create(self.db,1,data),lambda:s.create(self.db,1,data))
        self.assertEqual(sorted(r["created"] for r in results),[False,True])
        self.assertEqual(results[0]["ticket_id"],results[1]["ticket_id"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM support_tickets").fetchone()["n"],1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM support_messages").fetchone()["n"],1)

    def test_parallel_admin_retry_appends_one_reply(self):
        ticket=self.create();data={"ticket_id":ticket,"message":"Ответ поддержки","request_key":"support-race-reply01"}
        results=self.race(lambda:s.reply(self.db,3,data,True),lambda:s.reply(self.db,3,data,True))
        self.assertEqual(sorted(r["created"] for r in results),[False,True])
        self.assertEqual(len(s.detail(self.db,1,ticket)["messages"]),2)

    def test_new_reply_racing_read_marker_stays_unread(self):
        ticket=self.create();seen=s.detail(self.db,1,ticket)["last_message_id"]
        self.race(lambda:self.reply(ticket,3,"Новый ответ",True),lambda:s.mark_read(self.db,1,{"ticket_id":ticket,"last_message_id":seen}))
        self.assertEqual(s.detail(self.db,1,ticket)["ticket"]["unread_count"],1)


class SQLiteSupportRaces(SupportRaces,unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.prepare(database.SQLiteConnection(str(Path(self.directory.name)/"support.sqlite3")))
    def tearDown(self):self.close();self.directory.cleanup()


@unittest.skipUnless(os.environ.get("HPOINT_TEST_DATABASE_URL"),"requires isolated PostgreSQL test database")
class PostgreSQLSupportRaces(SupportRaces,unittest.TestCase):
    def setUp(self):
        from test_postgres import IsolatedPostgres
        self.schema="support_race_"+uuid.uuid4().hex;url=os.environ["HPOINT_TEST_DATABASE_URL"]
        self.control=database.PostgresConnection(url);self.control.execute('CREATE SCHEMA "'+self.schema+'"')
        self.prepare(IsolatedPostgres(url,self.schema))
    def tearDown(self):
        self.close();self.control.execute('DROP SCHEMA "'+self.schema+'" CASCADE');self.control.close()


if __name__=="__main__":unittest.main()
