import json,sqlite3,unittest
from datetime import datetime,timedelta
from unittest.mock import patch
from hpoint import database,services
import hpoint.billing as billing
from hpoint.billing import create_pending_invoice, purchase_with_points
class Billing(unittest.TestCase):
 def setUp(self):
  self.old=database.db;self.db=sqlite3.connect(":memory:",isolation_level=None);self.db.row_factory=sqlite3.Row
  database.db=self.db;services.db=self.db;billing.db=self.db;database.init_db();database.create_user(1,"u",None)
 def tearDown(self):database.db=self.old;services.db=self.old;billing.db=self.old;self.db.close()
 def test_rub_invoice(self):
  iid,payload,amount=create_pending_invoice(1,"pro")
  row=database.get_invoice(iid);self.assertEqual(row["currency"],"RUB");self.assertEqual(row["amount_rub"],249);self.assertEqual(amount,249);self.assertTrue(payload.startswith("hpoint:v2:"))
 def test_hidden_real_funds_cannot_pay_for_hpoint_plus(self):
  database.wallet_add_entry(1,1000,"payment","Historical real credit","hidden-real-credit",test_amount_rub=0)
  with self.assertRaisesRegex(ValueError,"insufficient_wallet"):
   billing.purchase_with_wallet(1,"pro",{},"test-only-purchase")
  self.assertIsNone(database.get_user(1)["pro_until"])
  self.assertEqual(database.wallet_summary(1)["balance_rub"],1000)
  self.assertEqual(database.wallet_summary(1)["test_balance_rub"],0)
 def test_catalog(self):
  from hpoint.config import MONETIZATION_ITEMS
  self.assertEqual(set(MONETIZATION_ITEMS),{"pro"})
  self.assertEqual(MONETIZATION_ITEMS["pro"]["rub"],249)
  self.assertIsNone(MONETIZATION_ITEMS["pro"]["hp"])
  self.assertEqual(MONETIZATION_ITEMS["pro"]["payments"],["wallet"])
  state=billing.subscription_state(1)["pro"]
  self.assertEqual(state["price_test_rub"],249)
  self.assertIsNone(state["price_hp"])
  self.assertEqual(state["payments"],["wallet"])
 def test_points_purchase_and_new_hp_invoice_are_rejected_without_changes(self):
  self.db.execute("UPDATE users SET balance=1000 WHERE user_id=1")
  before=dict(database.get_user(1))
  with self.assertRaisesRegex(ValueError,"points payment unavailable"):
   purchase_with_points(1,"pro",{},"one-purchase")
  with patch.object(billing,"PAYMENT_CURRENCY","HP"):
   with self.assertRaisesRegex(ValueError,"points payment unavailable"):
    create_pending_invoice(1,"pro")
  self.assertEqual(dict(database.get_user(1)),before)
  for table in ("billing_invoices","billing_events","wallet_transactions","subscriptions"):
   self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM "+table).fetchone()["n"],0)
 def test_old_pending_hp_pro_cannot_be_paid_or_acquired(self):
  self.db.execute("UPDATE users SET balance=1000 WHERE user_id=1")
  invoice=database.insert_id("INSERT INTO billing_invoices(user_id,item_type,amount_rub,currency,payload) VALUES(1,'pro',90,'HP','old-pending-hp')",())
  before=dict(database.get_user(1));old=dict(database.get_invoice(invoice))
  for operation in (lambda:billing.fulfill_invoice(invoice),lambda:billing.create_payment(invoice)):
   with self.assertRaisesRegex(ValueError,"points payment unavailable"):operation()
  self.assertEqual(dict(database.get_user(1)),before)
  self.assertEqual(dict(database.get_invoice(invoice)),old)
  for table in ("billing_events","wallet_transactions","subscriptions"):
   self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM "+table).fetchone()["n"],0)
 def test_historical_paid_hp_pro_replays_without_repricing_or_extending(self):
  self.db.execute("UPDATE users SET balance=910,pro_until='2090-01-01T00:00:00+00:00' WHERE user_id=1")
  invoice=database.insert_id("INSERT INTO billing_invoices(user_id,item_type,amount_rub,currency,payload,status,paid_at) VALUES(1,'pro',90,'HP','hpoint:hp:old-paid','paid',CURRENT_TIMESTAMP)",())
  self.db.execute("INSERT INTO subscriptions(user_id,invoice_id,plan,status,starts_at,ends_at,provider) VALUES(1,?,'pro','active','2089-12-02T00:00:00+00:00','2090-01-01T00:00:00+00:00','points')",(invoice,))
  before=dict(database.get_user(1));history=billing.subscription_state(1)["history"]
  self.assertEqual(purchase_with_points(1,"pro",{},"old-paid"),(invoice,False))
  self.assertEqual(billing.fulfill_invoice(invoice),(True,"already_paid"))
  self.assertEqual(database.get_invoice(invoice)["amount_rub"],90)
  self.assertEqual(dict(database.get_user(1)),before)
  self.assertEqual(billing.subscription_state(1)["history"],history)
 def test_legacy_paid_wallet_purchase_keeps_its_amount_and_new_price_needs_249(self):
  self.db.execute("UPDATE users SET pro_until='2000-01-01T00:00:00+00:00' WHERE user_id=1")
  invoice=database.insert_id("INSERT INTO billing_invoices(user_id,item_type,amount_rub,currency,payload,status,paid_at) VALUES(1,'pro',149,'WALLET','hpoint:wallet:old-wallet-paid','paid',CURRENT_TIMESTAMP)",())
  self.assertEqual(billing.purchase_with_wallet(1,"pro",{},"old-wallet-paid"),(invoice,False))
  self.assertEqual(database.get_invoice(invoice)["amount_rub"],149)
  database.wallet_add_entry(1,248,"test","Synthetic funds","almost-enough",test_amount_rub=248)
  with self.assertRaisesRegex(ValueError,"insufficient_wallet"):
   billing.purchase_with_wallet(1,"pro",{},"new-wallet-249")
  self.assertEqual(database.wallet_summary(1)["test_balance_rub"],248)
  self.assertEqual(database.get_user(1)["pro_until"],"2000-01-01T00:00:00+00:00")
  database.wallet_add_entry(1,1,"test","Synthetic funds","enough",test_amount_rub=1)
  created,is_new=billing.purchase_with_wallet(1,"pro",{},"new-wallet-249")
  self.assertTrue(is_new)
  self.assertEqual(database.get_invoice(created)["amount_rub"],249)
  self.assertEqual(database.wallet_summary(1)["test_balance_rub"],0)
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
  # Both historical obligations (boost +100 and more_responses +50) remain.
  self.assertEqual(database.get_request(rid)["priority_boost"],150)
  self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM ads").fetchone()["n"],1)
  self.assertEqual(database.get_identity_verification(1)["status"],"pending")
 def test_legacy_boost_is_request_specific_and_callback_replay_is_safe(self):
  self.db.execute("UPDATE users SET balance=1000 WHERE user_id=1")
  rid=self.request()
  database.create_user(2,"Other author")
  other=services.create_request(2,{"what":"Другая заявка","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"test","category":"tech"})
  self.db.execute("INSERT INTO billing_invoices(user_id,item_type,amount_rub,currency,payload,metadata) VALUES(1,'boost',49,'RUB','historical-boost',?)",(json.dumps({"request_id":rid}),))
  invoice=self.db.execute("SELECT id FROM billing_invoices WHERE payload='historical-boost'").fetchone()["id"]
  self.assertEqual(billing.fulfill_invoice(invoice),(True,"boost"))
  self.assertEqual(billing.fulfill_invoice(invoice),(True,"already_paid"))
  with self.assertRaises(ValueError):purchase_with_points(1,"boost",{"request_id":rid},"boost-new")
  self.assertEqual(database.get_user(1)["balance"],1000)
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
  self.assertEqual(database.get_invoice(invoice)["amount_rub"],249)
  self.assertEqual(database.wallet_summary(1)["test_balance_rub"],251)
  self.assertEqual(services.match_score(database.get_request(rid),2),before_score+10)
  self.assertEqual(next(row for row in services.smart_match(helper_request) if row["user_id"]==1)["score"],before_candidate+8)
  billing.purchase_with_wallet(1,"pro",{"renew":True,"expected_until":until.isoformat()},"pro-renew")
  self.assertEqual(datetime.fromisoformat(database.get_user(1)["pro_until"])-until,timedelta(days=30))
  self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM requests WHERE requester_rating IS NOT NULL OR helper_rating IS NOT NULL").fetchone()["n"],0)
if __name__=="__main__":unittest.main()
