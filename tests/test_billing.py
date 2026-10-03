import sqlite3,unittest
from hpoint import database,services
import hpoint.billing as billing
from hpoint.billing import create_pending_invoice
class Billing(unittest.TestCase):
 def setUp(self):
  self.old=database.db;self.db=sqlite3.connect(":memory:",isolation_level=None);self.db.row_factory=sqlite3.Row
  database.db=self.db;services.db=self.db;billing.db=self.db;database.init_db();database.create_user(1,"u",None)
 def tearDown(self):database.db=self.old;services.db=self.old;billing.db=self.old;self.db.close()
 def test_rub_invoice(self):
  iid,payload,amount=create_pending_invoice(1,"boost",{"request_id":7})
  row=database.get_invoice(iid);self.assertEqual(row["currency"],"RUB");self.assertEqual(row["amount_rub"],49);self.assertTrue(payload.startswith("hpoint:v2:"))
 def test_catalog(self):
  from hpoint.config import MONETIZATION_ITEMS
  self.assertEqual(len(MONETIZATION_ITEMS),8)
  self.assertTrue(all("rub" in x for x in MONETIZATION_ITEMS.values()))
if __name__=="__main__":unittest.main()
