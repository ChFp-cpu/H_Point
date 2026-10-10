import unittest,sqlite3,urllib.request,json,threading
from http.server import ThreadingHTTPServer
from hpoint import database,services
import hpoint.web as web
class Web(unittest.TestCase):
 def setUp(self):
  self.old=database.db;self.db=sqlite3.connect(":memory:",isolation_level=None,check_same_thread=False);self.db.row_factory=sqlite3.Row
  database.db=self.db;services.db=self.db;web.database.db=self.db;web.db=self.db;database.init_db()
 def tearDown(self):database.db=self.old;services.db=self.old;web.database.db=self.old;web.db=self.old;self.db.close()
 def test_web_shares_logic(self):
  database.create_user(42,"Web",None);rid=services.create_request(42,{"what":"Помочь с компьютером","place":"x","time_needed":"x","urgency":"x","details":"x"})
  self.assertEqual(database.get_request(rid)["category"],"tech")
 def test_page_contains_platform(self):
  self.assertIn("Smart Match",web.PAGE);self.assertIn("Telegram",web.PAGE);self.assertIn("руб",web.PAGE)
 def test_linked_requests_sync_live_between_bot_and_site(self):
  database.create_user(42,"Telegram",None)
  telegram_request=services.create_request(42,{"what":"Заявка из Telegram","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"bot"})
  web_uid=database.create_web_user("Site","site@example.com","hash")
  site_old_request=services.create_request(web_uid,{"what":"Заявка до привязки","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"site"})
  self.db.execute("UPDATE users SET verification_code='LINK1234' WHERE user_id=?",(web_uid,))
  token=web.new_sess(web_uid)
  ok,_=database.link_by_code("LINK1234",42,"telegram_user")
  self.assertTrue(ok)

  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   base=f"http://127.0.0.1:{server.server_address[1]}"
   get=urllib.request.Request(base+"/api/requests/mine",headers={"Cookie":f"hpoint_session={token}"})
   with urllib.request.urlopen(get,timeout=3) as response: initial=json.load(response)
   self.assertEqual(initial["current_user_id"],42)
   self.assertEqual({r["id"] for r in initial["requests"]},{telegram_request,site_old_request})

   self.db.execute("UPDATE requests SET status='cancelled'")
   payload=json.dumps({"what":"Заявка с сайта","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"web"}).encode()
   post=urllib.request.Request(base+"/api/requests",data=payload,headers={"Cookie":f"hpoint_session={token}","Content-Type":"application/json"},method="POST")
   with urllib.request.urlopen(post,timeout=3) as response: created=json.load(response)
   site_request=created["request_id"]
   self.assertIn(site_request,{r["id"] for r in database.get_history(42)})

   self.db.execute("UPDATE requests SET status='cancelled' WHERE id=?",(site_request,))
   bot_request=services.create_request(42,{"what":"Новая заявка из Telegram","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"bot"})
   with urllib.request.urlopen(get,timeout=3) as response: refreshed=json.load(response)
   self.assertIn(bot_request,{r["id"] for r in refreshed["requests"]})
  finally:
   server.shutdown();thread.join(timeout=3);server.server_close()
if __name__=="__main__":unittest.main()
