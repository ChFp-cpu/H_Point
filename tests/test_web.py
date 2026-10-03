import unittest,sqlite3,urllib.request,json,threading
from hpoint import database,services
import hpoint.web as web
class Web(unittest.TestCase):
 def setUp(self):
  self.old=database.db;self.db=sqlite3.connect(":memory:",isolation_level=None);self.db.row_factory=sqlite3.Row
  database.db=self.db;services.db=self.db;web.database.db=self.db;web.db=self.db;database.init_db()
 def tearDown(self):database.db=self.old;services.db=self.old;web.database.db=self.old;web.db=self.old;self.db.close()
 def test_web_shares_logic(self):
  database.create_user(42,"Web",None);rid=services.create_request(42,{"what":"Помочь с компьютером","place":"x","time_needed":"x","urgency":"x","details":"x"})
  self.assertEqual(database.get_request(rid)["category"],"tech")
 def test_page_contains_platform(self):
  self.assertIn("Smart Match",web.PAGE);self.assertIn("Telegram",web.PAGE);self.assertIn("руб",web.PAGE)
if __name__=="__main__":unittest.main()
