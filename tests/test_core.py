import sqlite3, unittest, tempfile, os, json
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
        services.set_helper_categories(2,["snow"]);services.set_helper_categories(3,["tech"])
        rid=services.create_request(1,{"what":"Помочь с компьютером","place":"центр","time_needed":"сегодня","urgency":"🕊 Не срочно","details":"test","lat":55.75,"lon":37.62})
        m=services.smart_match(rid);self.assertTrue(m);self.assertEqual(m[0]["user_id"],3)
    def test_atomic_completion_and_reviews(self):
        self.add(1);self.add(2);rid=services.create_request(1,{"what":"test","place":"x","time_needed":"x","urgency":"x","details":"x"})
        self.assertTrue(services.try_assign_helper(rid,2));self.assertTrue(services.complete_request(rid,2));self.assertFalse(services.complete_request(rid,2))
        self.assertEqual(database.get_user(1)["balance"],90);self.assertEqual(database.get_user(2)["balance"],120)
        self.assertTrue(services.set_rating(rid,1,5));self.assertTrue(services.set_helper_rating(rid,2,4))
        self.assertTrue(services.set_review(rid,1,"Отлично","requester"))
        self.assertTrue(services.set_review(rid,2,"Хорошо","helper"))
    def test_link_migrates_web_account_to_telegram_id(self):
        uid=database.create_web_user("Web","web@example.com","hash")
        self.db.execute("UPDATE users SET verification_code='ABCD1234' WHERE user_id=?",(uid,))
        ok,msg=database.link_by_code("ABCD1234",555,"user555");self.assertTrue(ok)
        u=database.get_user(555);self.assertIsNotNone(u);self.assertEqual(u["name"],"Web");self.assertEqual(u["tg_user_id"],555)
        self.assertIsNone(database.get_user(uid))
if __name__=="__main__":unittest.main()
