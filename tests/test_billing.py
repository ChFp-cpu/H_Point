import json,sqlite3,unittest
from datetime import datetime,timedelta
from hpoint import database,services
import hpoint.billing as billing
from hpoint.billing import create_pending_invoice, purchase_with_points
class Billing(unittest.TestCase):
 def setUp(self):
  self.old=database.db;self.db=sqlite3.connect(":memory:",isolation_level=None);self.db.row_factory=sqlite3.Row
  database.db=self.db;services.db=self.db;billing.db=self.db;database.init_db();database.create_user(1,"u",None)
 def tearDown(self):database.db=self.old;services.db=self.old;billing.db=self.old;self.db.close()
 def test_rub_invoice(self):
  rid=self.request()
  iid,payload,amount=create_pending_invoice(1,"boost",{"request_id":rid})
  row=database.get_invoice(iid);self.assertEqual(row["currency"],"RUB");self.assertEqual(row["amount_rub"],49);self.assertTrue(payload.startswith("hpoint:v2:"))
 def test_hidden_real_funds_cannot_pay_for_hpoint_plus(self):
  database.wallet_add_entry(1,1000,"payment","Historical real credit","hidden-real-credit",test_amount_rub=0)
  with self.assertRaisesRegex(ValueError,"insufficient_wallet"):
   billing.purchase_with_wallet(1,"pro",{},"test-only-purchase")
  self.assertIsNone(database.get_user(1)["pro_until"])
  self.assertEqual(database.wallet_summary(1)["balance_rub"],1000)
  self.assertEqual(database.wallet_summary(1)["test_balance_rub"],0)
 def test_catalog(self):
  from hpoint.config import MONETIZATION_ITEMS
  self.assertEqual(set(MONETIZATION_ITEMS),{"boost","pro"})
  self.assertTrue(all("rub" in x and "hp" in x for x in MONETIZATION_ITEMS.values()))
 def test_points_purchase_is_atomic_and_idempotent(self):
  self.db.execute("UPDATE users SET balance=1000 WHERE user_id=1")
  before=database.get_user(1)["balance"]
  invoice,created=purchase_with_points(1,"pro",{},"one-purchase")
  self.assertTrue(created);self.assertEqual(database.get_invoice(invoice)["currency"],"HP")
  self.assertEqual(database.get_user(1)["balance"],before-90)
  self.assertIsNotNone(database.get_user(1)["pro_until"])
  same,created_again=purchase_with_points(1,"pro",{},"one-purchase")
  self.assertEqual(same,invoice);self.assertFalse(created_again)
 def request(self):
  return services.create_request(1,{"what":"Помочь с техникой","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"test","category":"tech"})
 def test_retired_items_cannot_be_sold_in_any_currency(self):
  from hpoint.config import LEGACY_MONETIZATION_ITEMS
  self.db.execute("UPDATE users SET balance=1000 WHERE user_id=1")
  database.wallet_add_entry(1,2000,"test","test","test")
  for item in LEGACY_MONETIZATION_ITEMS:
   for purchase in [lambda:create_pending_invoice(1,item),lambda:billing.purchase_with_points(1,item,{},"hp-"+item),lambda:billing.purchase_with_wallet(1,item,{},"rub-"+item)]:
    with self.assertRaises(ValueError):purchase()
  self.assertEqual(database.get_user(1)["balance"],1000)
  self.assertEqual(database.wallet_summary(1)["test_balance_rub"],2000)
  self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM billing_invoices").fetchone()["n"],0)
 def test_legacy_paid_invoices_still_fulfill_at_original_amounts(self):
  from hpoint.config import LEGACY_MONETIZATION_ITEMS
  self.db.execute("UPDATE users SET tg_user_id=1 WHERE user_id=1")
  rid=self.request()
  for item,offer in LEGACY_MONETIZATION_ITEMS.items():
   meta=json.dumps({"request_id":rid,"ad_text":"Ранее оплаченное объявление"})
   self.db.execute("INSERT INTO billing_invoices(user_id,item_type,amount_rub,currency,payload,metadata) VALUES(1,?,?,'RUB',?,?)",(item,offer["rub"],"legacy-"+item,meta))
   invoice=self.db.execute("SELECT id FROM billing_invoices WHERE payload=?",("legacy-"+item,)).fetchone()["id"]
   self.assertTrue(billing.fulfill_invoice(invoice)[0])
   self.assertTrue(billing.fulfill_invoice(invoice)[0])
   self.assertEqual(database.get_invoice(invoice)["amount_rub"],offer["rub"])
  self.assertEqual(database.get_user(1)["favorite_slots"],8)
  self.assertIsNotNone(database.get_user(1)["business_until"])
  self.assertEqual(database.get_request(rid)["priority_boost"],50)
  self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM ads").fetchone()["n"],1)
  self.assertEqual(database.get_identity_verification(1)["status"],"pending")
 def test_boost_is_request_specific_and_cannot_be_charged_twice(self):
  self.db.execute("UPDATE users SET balance=1000 WHERE user_id=1")
  rid=self.request();other=self.request()
  invoice,_=purchase_with_points(1,"boost",{"request_id":rid},"boost-once")
  self.assertEqual(purchase_with_points(1,"boost",{"request_id":rid},"boost-once"),(invoice,False))
  with self.assertRaisesRegex(ValueError,"already promoted"):
   purchase_with_points(1,"boost",{"request_id":rid},"boost-again")
  self.assertEqual(database.get_user(1)["balance"],975)
  self.assertEqual(database.get_request(rid)["priority_boost"],100)
  self.assertEqual(database.get_request(other)["priority_boost"],0)
 def test_pro_new_price_duration_and_real_priority_without_rating_changes(self):
  rid=self.request()
  database.create_user(2,"helper")
  services.add_to_queue(1);services.add_to_queue(2)
  helper_request=services.create_request(2,{"what":"Помощь","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"test"})
  before_score=services.match_score(database.get_request(rid),2)
  before_candidate=next(row for row in services.smart_match(helper_request) if row["user_id"]==1)["score"]
  database.wallet_add_entry(1,500,"test","test","wallet-test")
  invoice,_=billing.purchase_with_wallet(1,"pro",{},"pro-wallet")
  until=datetime.fromisoformat(database.get_user(1)["pro_until"])
  self.assertEqual(database.get_invoice(invoice)["amount_rub"],149)
  self.assertEqual(database.wallet_summary(1)["test_balance_rub"],351)
  self.assertEqual(services.match_score(database.get_request(rid),2),before_score+10)
  self.assertEqual(next(row for row in services.smart_match(helper_request) if row["user_id"]==1)["score"],before_candidate+8)
  billing.purchase_with_wallet(1,"pro",{},"pro-renew")
  self.assertEqual(datetime.fromisoformat(database.get_user(1)["pro_until"])-until,timedelta(days=30))
  self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM requests WHERE requester_rating IS NOT NULL OR helper_rating IS NOT NULL").fetchone()["n"],0)
if __name__=="__main__":unittest.main()
