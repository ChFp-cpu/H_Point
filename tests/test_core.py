import sqlite3, unittest, tempfile, os, json, threading
from datetime import datetime, timedelta, timezone
from hpoint import database, services
class Core(unittest.TestCase):
    def setUp(self):
        self.old=database.db
        self.db=sqlite3.connect(":memory:",isolation_level=None);self.db.row_factory=sqlite3.Row
        database.db=self.db;services.db=self.db;database.init_db()
    def tearDown(self):
        database.db=self.old;services.db=self.old;self.db.close()
    def add(self,uid,b=100):database.create_user(uid,f"User {uid}",None);self.db.execute("UPDATE users SET balance=? WHERE user_id=?",(b,uid))
    def test_request_and_match(self):
        self.add(1);self.add(2);self.add(3)
        services.add_to_queue(2);services.add_to_queue(3)
        services.set_helper_categories(2,["snow"]);services.set_helper_categories(3,["tech"])
        rid=services.create_request(1,{"what":"Помочь с компьютером","place":"центр","time_needed":"сегодня","urgency":"🕊 Не срочно","details":"test","lat":55.75,"lon":37.62})
        m=services.smart_match(rid);self.assertTrue(m);self.assertEqual(m[0]["user_id"],3)
    def test_smart_match_explains_query_match(self):
        self.add(1);self.add(2)
        services.add_to_queue(2)
        services.set_helper_categories(2,["tech"])
        self.db.execute("UPDATE users SET bio='Опытный компьютерный мастер' WHERE user_id=2")
        rid=services.create_request(1,{"what":"Помочь с компьютером","place":"центр","time_needed":"сегодня","urgency":"🕊 Не срочно","details":"test"})
        match=services.smart_match(rid,query="опытный мастер")[0]
        self.assertIn("соответствует уточнению",match["reasons"])
    def test_smart_match_does_not_disclose_candidate_coordinates(self):
        self.add(1);self.add(2)
        services.add_to_queue(2)
        self.db.execute("UPDATE users SET lat=55.75123,lon=37.61987 WHERE user_id=2")
        rid=services.create_request(1,{"what":"Помочь","place":"центр","time_needed":"сегодня","urgency":"🕊 Не срочно","details":"test","lat":55.75,"lon":37.62})
        match=services.smart_match(rid)[0]
        self.assertEqual((match["lat"],match["lon"]),(None,None))
    def test_helper_offer_requires_queue_and_consent(self):
        self.add(1);self.add(2);self.add(3)
        rid=services.create_request(1,{"what":"Нужна помощь","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"test"})
        self.assertFalse(services.offer_helper(rid,2))
        services.add_to_queue(2)
        self.assertTrue(services.offer_helper(rid,2))
        self.assertEqual(database.get_request(rid)["status"],"open")
        self.assertIsNone(database.get_request(rid)["helper_id"])
        self.assertEqual(services.get_current_helper_offer(rid)["candidate_id"],2)
        self.assertTrue(services.respond_to_helper_offer(rid,2,False))
        self.assertTrue(services.is_in_queue(2))
        self.assertEqual(services.smart_match(rid),[])
        services.add_to_queue(3)
        self.assertTrue(services.offer_helper(rid,3))
        self.assertTrue(services.respond_to_helper_offer(rid,3,True))
        self.assertEqual(database.get_request(rid)["status"],"in_progress")
        self.assertEqual(database.get_request(rid)["helper_id"],3)
        self.assertFalse(services.is_in_queue(3))
    def test_auth_attempts_are_rate_limited_and_clear_on_success(self):
        self.assertFalse(database.auth_is_rate_limited("login","person@example.com",3))
        for _ in range(3): database.record_auth_failure("login","person@example.com")
        self.assertTrue(database.auth_is_rate_limited("login","person@example.com",3))
        database.clear_auth_failures("login","person@example.com")
        self.assertFalse(database.auth_is_rate_limited("login","person@example.com",3))
    def test_expired_telegram_link_code_cannot_link_account(self):
        uid=database.create_web_user("Web","expired@example.com","hash")
        self.db.execute("UPDATE users SET verification_code='EXPIRED',verification_code_expires_at=? WHERE user_id=?",((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),uid))
        ok,_=database.link_by_code("EXPIRED",555,"user555")
        self.assertFalse(ok)
    def test_atomic_completion_and_reviews(self):
        self.add(1);self.add(2);rid=services.create_request(1,{"what":"test","place":"x","time_needed":"x","urgency":"x","details":"x"})
        self.assertTrue(services.try_assign_helper(rid,2));self.assertTrue(services.complete_request(rid,2));self.assertFalse(services.complete_request(rid,2))
        self.assertEqual(database.get_user(1)["balance"],90);self.assertEqual(database.get_user(2)["balance"],120)
        self.assertTrue(services.set_rating(rid,1,5));self.assertTrue(services.set_helper_rating(rid,2,4))
        self.assertTrue(services.set_review(rid,1,"Отлично","requester"))
        self.assertTrue(services.set_review(rid,2,"Хорошо","helper"))
    def test_concurrent_assignment_cannot_double_book_helper(self):
        old_db, old_service_db = database.db, services.db
        temp = tempfile.TemporaryDirectory(dir=os.getcwd())
        shared = None
        try:
            shared = database.SQLiteConnection(os.path.join(temp.name, "concurrency.db"))
            database.db = services.db = shared
            database.init_db()
            for uid in (1, 2, 3):
                database.create_user(uid, f"User {uid}")
            first = services.create_request(1, {"what":"one", "place":"x", "time_needed":"x", "urgency":"x", "details":"x"})
            second = services.create_request(3, {"what":"two", "place":"x", "time_needed":"x", "urgency":"x", "details":"x"})
            barrier = threading.Barrier(3)
            outcomes = []
            def assign(request_id):
                try:
                    barrier.wait()
                    outcomes.append(services.try_assign_helper(request_id, 2))
                finally:
                    shared.close()
            workers = [threading.Thread(target=assign, args=(rid,)) for rid in (first, second)]
            for worker in workers: worker.start()
            barrier.wait()
            for worker in workers: worker.join(timeout=5)
            self.assertTrue(all(not worker.is_alive() for worker in workers))
            self.assertEqual(sum(outcomes), 1)
            active = shared.execute("SELECT COUNT(*) n FROM requests WHERE helper_id=? AND status=?", (2, "in_progress")).fetchone()["n"]
            self.assertEqual(active, 1)
        finally:
            if shared is not None: shared.close()
            database.db, services.db = old_db, old_service_db
            temp.cleanup()
    def test_concurrent_helpers_cannot_accept_same_request(self):
        old_db, old_service_db = database.db, services.db
        temp = tempfile.TemporaryDirectory(dir=os.getcwd())
        shared = database.SQLiteConnection(os.path.join(temp.name, "acceptance.db"))
        try:
            database.db = services.db = shared
            database.init_db()
            for uid in (1, 2, 3): database.create_user(uid, f"User {uid}")
            request_id = services.create_request(1, {"what":"help", "place":"x", "time_needed":"x", "urgency":"x", "details":"x"})
            barrier = threading.Barrier(3)
            outcomes = []
            def assign(helper_id):
                try:
                    barrier.wait()
                    outcomes.append(services.try_assign_helper(request_id, helper_id))
                finally:
                    shared.close()
            workers = [threading.Thread(target=assign, args=(uid,)) for uid in (2, 3)]
            for worker in workers: worker.start()
            barrier.wait()
            for worker in workers: worker.join(timeout=5)
            self.assertTrue(all(not worker.is_alive() for worker in workers))
            self.assertEqual(sum(outcomes), 1)
            self.assertEqual(shared.execute("SELECT COUNT(*) n FROM requests WHERE id=? AND status='in_progress'", (request_id,)).fetchone()["n"], 1)
        finally:
            shared.close()
            database.db, services.db = old_db, old_service_db
            temp.cleanup()
    def test_concurrent_completions_cannot_double_spend_or_pay(self):
        old_db, old_service_db = database.db, services.db
        temp = tempfile.TemporaryDirectory(dir=os.getcwd())
        shared = database.SQLiteConnection(os.path.join(temp.name, "completion.db"))
        try:
            database.db = services.db = shared
            database.init_db()
            for uid in (1, 2, 3): database.create_user(uid, f"User {uid}")
            shared.execute("UPDATE users SET balance=10 WHERE user_id=1")
            requests = [services.create_request(1, {"what":str(i), "place":"x", "time_needed":"x", "urgency":"x", "details":"x"}) for i in range(2)]
            for rid, helper in zip(requests, (2, 3)): self.assertTrue(services.try_assign_helper(rid, helper))
            barrier = threading.Barrier(3)
            outcomes = []
            def complete(rid, helper):
                try:
                    barrier.wait()
                    outcomes.append(services.complete_request(rid, helper))
                finally:
                    shared.close()
            workers = [threading.Thread(target=complete, args=(rid, helper)) for rid, helper in zip(requests, (2, 3))]
            for worker in workers: worker.start()
            barrier.wait()
            for worker in workers: worker.join(timeout=5)
            self.assertTrue(all(not worker.is_alive() for worker in workers))
            self.assertEqual(sum(outcomes), 1)
            self.assertEqual(database.get_user(1)["balance"], 0)
            self.assertEqual(sum(database.get_user(uid)["balance"] for uid in (2, 3)), 220)
        finally:
            shared.close()
            database.db, services.db = old_db, old_service_db
            temp.cleanup()
    def test_link_migrates_web_account_to_telegram_id(self):
        uid=database.create_web_user("Web","web@example.com","hash")
        self.db.execute("UPDATE users SET verification_code='ABCD1234',verification_code_expires_at=? WHERE user_id=?",((datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(),uid))
        ok,msg=database.link_by_code("ABCD1234",555,"user555");self.assertTrue(ok)
        u=database.get_user(555);self.assertIsNotNone(u);self.assertEqual(u["name"],"Web");self.assertEqual(u["tg_user_id"],555)
        self.assertIsNone(database.get_user(uid))
    def test_identity_verification_requires_manual_admin_review(self):
        self.add(1);self.add(99)
        self.db.execute("UPDATE users SET role='admin' WHERE user_id=99")
        ok,status=database.request_identity_verification(1)
        self.assertTrue(ok);self.assertEqual(status,"pending")
        self.assertFalse(services.is_verified(1))
        services.grant_entitlement(1,"verification")
        self.assertEqual(database.get_identity_verification(1)["status"],"pending")
        ok,status=database.review_identity_verification(99,1,True)
        self.assertTrue(ok);self.assertEqual(status,"approved")
        self.assertTrue(services.is_verified(1))
        self.assertEqual(database.get_identity_verification(1)["status"],"approved")
    def test_identity_verification_requires_linked_telegram(self):
        uid=database.create_web_user("Web","identity@example.com","hash")
        ok,status=database.request_identity_verification(uid)
        self.assertFalse(ok);self.assertEqual(status,"telegram_required")
    def test_admin_dashboard_and_request_moderation(self):
        self.add(1);self.add(99)
        self.db.execute("UPDATE users SET role='admin',last_seen_at=? WHERE user_id=99", (datetime.now(timezone.utc).isoformat(),))
        rid=services.create_request(1,{"what":"Нужна помощь","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"test"})
        self.db.execute("INSERT INTO support_tickets(user_id,subject,message) VALUES(?,?,?)",(1,"Вопрос","Нужна подсказка"))
        dashboard=database.admin_dashboard()
        self.assertEqual(dashboard["summary"]["users"],2)
        self.assertEqual(dashboard["summary"]["requests"]["open"],1)
        self.assertEqual(dashboard["summary"]["support"]["open"],1)
        self.assertTrue(any(user["id"]==1 for user in dashboard["users"]))
        cancelled,request=database.admin_cancel_request(99,rid,"дубликат")
        self.assertTrue(cancelled);self.assertEqual(request["id"],rid)
        self.assertEqual(database.get_request(rid)["status"],"cancelled")
        audit=self.db.execute("SELECT action FROM admin_audit_log WHERE target_user_id=?",(1,)).fetchone()
        self.assertEqual(audit["action"],"request_cancelled")
if __name__=="__main__":unittest.main()
