import unittest,sqlite3,urllib.request,urllib.error,json,threading
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from hpoint import database,services
import hpoint.billing as billing
import hpoint.web as web
class Web(unittest.TestCase):
 def setUp(self):
  self.old=database.db;self.db=sqlite3.connect(":memory:",isolation_level=None,check_same_thread=False);self.db.row_factory=sqlite3.Row
  database.db=self.db;services.db=self.db;billing.db=self.db;web.database.db=self.db;web.db=self.db;database.init_db()
 def tearDown(self):database.db=self.old;services.db=self.old;billing.db=self.old;web.database.db=self.old;web.db=self.old;self.db.close()
 def test_web_shares_logic(self):
  database.create_user(42,"Web",None);rid=services.create_request(42,{"what":"Помочь с компьютером","place":"x","time_needed":"x","urgency":"x","details":"x"})
  self.assertEqual(database.get_request(rid)["category"],"tech")
 def test_page_contains_platform(self):
  self.assertIn("Smart Match",web.PAGE);self.assertIn("Telegram",web.PAGE);self.assertIn("руб",web.PAGE)
  self.assertIn("timeout:2500",web.PAGE)
  self.assertIn("&csp=true",web.PAGE)
  self.assertIn("Создать профиль",web.PAGE)
  self.assertIn("resumeTelegramLogin",web.PAGE)
  self.assertIn("/api/requests/accept",web.PAGE)
  self.assertIn("https://*.maps.yandex.net",web.CSP)
  self.assertIn("https://api-maps.yandex.ru",web.CSP)
 def test_registration_login_and_api_access_control(self):
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  base=f"http://127.0.0.1:{server.server_address[1]}"
  def post(path,payload,cookie=None):
   headers={"Content-Type":"application/json"}
   if cookie:headers["Cookie"]=cookie
   req=urllib.request.Request(base+path,data=json.dumps(payload).encode(),headers=headers,method="POST")
   return urllib.request.urlopen(req,timeout=3)
  try:
   with post("/api/auth/register",{"name":"New User","email":"new@example.com","password":"correct horse"}) as response:
    created=json.load(response);cookie=response.headers["Set-Cookie"].split(";",1)[0]
   self.assertTrue(created["ok"])
   with urllib.request.urlopen(urllib.request.Request(base+"/api/me",headers={"Cookie":cookie}),timeout=3) as response:
    self.assertEqual(json.load(response)["user"]["email"],"new@example.com")
   with post("/api/auth/login",{"email":"new@example.com","password":"correct horse"}) as response:
    self.assertTrue(json.load(response)["ok"])
   with self.assertRaises(urllib.error.HTTPError) as denied:
    urllib.request.urlopen(base+"/api/me",timeout=3)
   self.assertEqual(denied.exception.code,401)
   denied.exception.close()
   self.db.execute("UPDATE users SET role='user' WHERE email='new@example.com'")
   with self.assertRaises(urllib.error.HTTPError) as forbidden:
    urllib.request.urlopen(urllib.request.Request(base+"/api/admin/summary",headers={"Cookie":cookie}),timeout=3)
   self.assertEqual(forbidden.exception.code,403)
   forbidden.exception.close()
  finally:
   server.shutdown();thread.join(timeout=3);server.server_close()
 def test_telegram_login_creates_one_shared_profile(self):
  old_username=web._telegram_username;web._telegram_username="hpoint_test_bot"
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  base=f"http://127.0.0.1:{server.server_address[1]}"
  try:
   request=urllib.request.Request(base+"/api/auth/telegram/start",data=b"{}",headers={"Content-Type":"application/json"},method="POST")
   with urllib.request.urlopen(request,timeout=3) as response: started=json.load(response)
   self.assertIn("start=login_",started["bot_url"])
   self.assertTrue(database.complete_telegram_auth_ticket(started["ticket"],777,"Telegram Person","tgperson"))
   with urllib.request.urlopen(base+"/api/auth/telegram/complete?ticket="+started["ticket"],timeout=3) as response:
    done=json.load(response);cookie=response.headers["Set-Cookie"].split(";",1)[0]
   self.assertTrue(done["ok"])
   with urllib.request.urlopen(urllib.request.Request(base+"/api/me",headers={"Cookie":cookie}),timeout=3) as response:
    self.assertEqual(json.load(response)["user"]["id"],777)
   with urllib.request.urlopen(base+"/api/auth/telegram/complete?ticket="+started["ticket"],timeout=3) as response:
    self.assertEqual(response.status,202)
  finally:
   web._telegram_username=old_username;server.shutdown();thread.join(timeout=3);server.server_close()
 def test_map_and_search_do_not_leak_exact_coordinates_or_details(self):
  database.create_user(1,"Requester");database.create_user(2,"Viewer")
  rid=services.create_request(1,{"what":"Нужна дрель","place":"район","time_needed":"сегодня","urgency":"обычная","details":"Точный адрес: секрет","lat":55.75123,"lon":37.61987})
  token=web.new_sess(2)
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   base=f"http://127.0.0.1:{server.server_address[1]}";headers={"Cookie":f"hpoint_session={token}"}
   with urllib.request.urlopen(urllib.request.Request(base+"/api/requests?open=1",headers=headers),timeout=3) as response: row=json.load(response)["requests"][0]
   self.assertEqual(row["id"],rid);self.assertIsNone(row["lat"]);self.assertIsNone(row["lon"]);self.assertNotIn("details",row);self.assertNotEqual(row["place"],"район")
  finally:
   server.shutdown();thread.join(timeout=3);server.server_close()
 def test_production_requires_same_origin_for_state_changes(self):
  class Request:
   def __init__(self, origin=None): self.headers={} if origin is None else {"Origin":origin}
  old_env,old_url=web.APP_ENV,web.WEB_PUBLIC_URL
  try:
   web.APP_ENV="production";web.WEB_PUBLIC_URL="https://gethpoint.ru"
   self.assertFalse(web.valid_origin(Request()))
   self.assertFalse(web.valid_origin(Request("https://attacker.example")))
   self.assertTrue(web.valid_origin(Request("https://gethpoint.ru")))
  finally:
   web.APP_ENV,web.WEB_PUBLIC_URL=old_env,old_url
 def test_telegram_ticket_logs_into_same_web_profile_once(self):
  database.create_user(42,"Telegram",None)
  ticket="one-time-test-ticket"
  database.create_web_login_ticket(42,ticket)
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  class NoRedirect(urllib.request.HTTPRedirectHandler):
   def redirect_request(self,req,fp,code,msg,headers,newurl):return None
  opener=urllib.request.build_opener(NoRedirect)
  try:
   base=f"http://127.0.0.1:{server.server_address[1]}"
   try:opener.open(base+"/auth/telegram?ticket="+ticket,timeout=3)
   except urllib.error.HTTPError as response:
    with response:
     self.assertEqual(response.code,303)
     cookie=response.headers["Set-Cookie"].split(";",1)[0]
   else:self.fail("Expected one-time ticket redirect")
   request=urllib.request.Request(base+"/api/me",headers={"Cookie":cookie})
   with urllib.request.urlopen(request,timeout=3) as response:profile=json.load(response)
   self.assertEqual(profile["user"]["id"],42)
   with self.assertRaises(urllib.error.HTTPError) as expired:
    urllib.request.urlopen(base+"/auth/telegram?ticket="+ticket,timeout=3)
   with expired.exception:
    self.assertEqual(expired.exception.code,403)
  finally:
   server.shutdown();thread.join(timeout=3);server.server_close()
 def test_linked_requests_sync_live_between_bot_and_site(self):
  database.create_user(42,"Telegram",None)
  telegram_request=services.create_request(42,{"what":"Заявка из Telegram","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"bot"})
  web_uid=database.create_web_user("Site","site@example.com","hash")
  site_old_request=services.create_request(web_uid,{"what":"Заявка до привязки","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"site"})
  self.db.execute("UPDATE users SET verification_code='LINK1234',verification_code_expires_at=? WHERE user_id=?",((datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(),web_uid))
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
 def test_parallel_sessions_keep_other_device_signed_in(self):
  uid=database.create_web_user("Parallel","parallel@example.com","hash")
  first,second=web.new_sess(uid),web.new_sess(uid)
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   base=f"http://127.0.0.1:{server.server_address[1]}"
   def get(cookie):
    return urllib.request.urlopen(urllib.request.Request(base+"/api/me",headers={"Cookie":f"hpoint_session={cookie}"}),timeout=3)
   with get(first) as response:self.assertEqual(json.load(response)["user"]["id"],uid)
   with get(second) as response:self.assertEqual(json.load(response)["user"]["id"],uid)
   request=urllib.request.Request(base+"/api/auth/logout",data=b"{}",headers={"Content-Type":"application/json","Cookie":f"hpoint_session={first}"},method="POST")
   with urllib.request.urlopen(request,timeout=3) as response:self.assertTrue(json.load(response)["ok"])
   with get(second) as response:self.assertEqual(json.load(response)["user"]["id"],uid)
  finally:
   server.shutdown();thread.join(timeout=3);server.server_close()
 def test_chat_is_private_live_and_input_is_validated(self):
  for uid,name in ((1,"Requester"),(2,"Helper"),(3,"Outsider")):database.create_user(uid,name)
  rid=services.create_request(1,{"what":"Нужна помощь","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"test"})
  self.assertTrue(services.try_assign_helper(rid,2))
  first_chat,second_chat=web.chat_for_request(rid),web.chat_for_request(rid)
  self.assertEqual(first_chat,second_chat)
  tokens={uid:web.new_sess(uid) for uid in (1,2,3)}
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   base=f"http://127.0.0.1:{server.server_address[1]}"
   def request(path,method="GET",payload=None,uid=1):
    headers={"Cookie":f"hpoint_session={tokens[uid]}"}
    data=None
    if payload is not None:headers["Content-Type"]="application/json";data=json.dumps(payload).encode()
    return urllib.request.urlopen(urllib.request.Request(base+path,data=data,headers=headers,method=method),timeout=3)
   with request("/api/chats/send","POST",{"request_id":rid,"text":"Здравствуйте!"},1) as response:
    self.assertEqual(json.load(response)["messages"][-1]["text"],"Здравствуйте!")
   with request(f"/api/chats?request_id={rid}",uid=2) as response:
    chat=json.load(response)["chats"][0]
   self.assertEqual(chat["messages"][-1]["text"],"Здравствуйте!")
   with self.assertRaises(urllib.error.HTTPError) as denied:
    request("/api/chats/send","POST",{"request_id":rid,"text":"Вмешательство"},3)
   self.assertEqual(denied.exception.code,403)
   denied.exception.close()
   with self.assertRaises(urllib.error.HTTPError) as malformed:
    request("/api/chats/send","POST",{"request_id":"bad","text":"x"},1)
   self.assertEqual(malformed.exception.code,400)
   malformed.exception.close()
  finally:
   server.shutdown();thread.join(timeout=3);server.server_close()
 def test_sync_endpoint_and_brand_images_are_available(self):
  database.create_user(1,"User")
  token=web.new_sess(1)
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   base=f"http://127.0.0.1:{server.server_address[1]}";headers={"Cookie":f"hpoint_session={token}"}
   with urllib.request.urlopen(urllib.request.Request(base+"/api/sync",headers=headers),timeout=3) as response:
    data=json.load(response)
   self.assertEqual(data["user"]["id"],1);self.assertIn("requests",data)
   for asset in ("hpoint-brand-hero.png", "hpoint-route-network.png", "hpoint-match-field.png", "hpoint-logo-dark.png"):
    with urllib.request.urlopen(base+"/assets/"+asset,timeout=3) as response:
     self.assertEqual(response.headers.get_content_type(),"image/png");self.assertGreater(len(response.read()),1000)
  finally:
   server.shutdown();thread.join(timeout=3);server.server_close()
 def test_helper_claims_existing_request_and_open_feed_hides_own_request(self):
  database.create_user(1,"Requester");database.create_user(2,"Helper")
  rid=services.create_request(1,{"what":"Нужна помощь с техникой","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"test"})
  token=web.new_sess(2)
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   base=f"http://127.0.0.1:{server.server_address[1]}";headers={"Cookie":f"hpoint_session={token}","Content-Type":"application/json"}
   with urllib.request.urlopen(urllib.request.Request(base+"/api/requests?open=1",headers=headers),timeout=3) as response:feed=json.load(response)["requests"]
   self.assertEqual([row["id"] for row in feed],[rid]);self.assertNotIn("details",feed[0])
   with urllib.request.urlopen(urllib.request.Request(base+"/api/helper/queue",data=b"{}",headers=headers,method="POST"),timeout=3) as response:claimed=json.load(response)
   self.assertTrue(claimed["matched"]);self.assertEqual(claimed["request_id"],rid)
   request=database.get_request(rid);self.assertEqual(request["helper_id"],2);self.assertEqual(request["status"],"in_progress")
   self.assertIsNotNone(web.chat_for_request(rid))
   with self.assertRaises(urllib.error.HTTPError) as busy:
    urllib.request.urlopen(urllib.request.Request(base+"/api/helper/queue",data=b"{}",headers=headers,method="POST"),timeout=3)
   self.assertEqual(busy.exception.code,409);busy.exception.close()
   with urllib.request.urlopen(urllib.request.Request(base+"/api/requests?open=1",headers=headers),timeout=3) as response:self.assertEqual(json.load(response)["requests"],[])
  finally:
   server.shutdown();thread.join(timeout=3);server.server_close()
 def test_helper_with_active_request_cannot_accept_another_request(self):
  database.create_user(1,"Requester");database.create_user(2,"Busy helper")
  target=services.create_request(1,{"what":"Нужна помощь","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"test"})
  services.create_request(2,{"what":"Моя активная заявка","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"test"})
  token=web.new_sess(2)
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   base=f"http://127.0.0.1:{server.server_address[1]}";headers={"Cookie":f"hpoint_session={token}","Content-Type":"application/json"}
   req=urllib.request.Request(base+"/api/requests/accept",data=json.dumps({"request_id":target}).encode(),headers=headers,method="POST")
   with self.assertRaises(urllib.error.HTTPError) as denied:urllib.request.urlopen(req,timeout=3)
   self.assertEqual(denied.exception.code,409);denied.exception.close()
   self.assertEqual(database.get_request(target)["status"],"open")
  finally:
   server.shutdown();thread.join(timeout=3);server.server_close()
 def test_points_purchase_and_device_profile_switching(self):
  database.create_user(1,"First");database.create_user(2,"Second")
  self.db.execute("UPDATE users SET balance=1000 WHERE user_id=1")
  device="shared-device";first=web.new_sess(1,device);web.new_sess(2,device)
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  base=f"http://127.0.0.1:{server.server_address[1]}";cookie=f"hpoint_session={first}; hpoint_device={device}"
  try:
   def post(path,payload,cookie_value=cookie):
    return urllib.request.urlopen(urllib.request.Request(base+path,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json","Cookie":cookie_value},method="POST"),timeout=3)
   with post("/api/payments/hp",{"item_type":"pro","purchase_key":"test-hp-one"}) as response:self.assertTrue(json.load(response)["created"])
   self.assertEqual(database.get_user(1)["balance"],820)
   with urllib.request.urlopen(urllib.request.Request(base+"/api/profiles",headers={"Cookie":cookie}),timeout=3) as response:self.assertEqual(len(json.load(response)["profiles"]),2)
   with post("/api/profiles/switch",{"user_id":2}) as response: switched=response.headers["Set-Cookie"].split(";",1)[0]
   with urllib.request.urlopen(urllib.request.Request(base+"/api/me",headers={"Cookie":switched+"; hpoint_device="+device}),timeout=3) as response:self.assertEqual(json.load(response)["user"]["id"],2)
  finally:
   server.shutdown();thread.join(timeout=3);server.server_close()
 def test_unlink_telegram_preserves_website_data(self):
  database.create_user(77,"Linked",tg_user_id=77,web_verified=True);self.db.execute("UPDATE users SET email='linked@example.com',password_hash='hash',balance=333 WHERE user_id=77")
  token=web.new_sess(77,"unlink-device")
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   base=f"http://127.0.0.1:{server.server_address[1]}";headers={"Content-Type":"application/json","Cookie":f"hpoint_session={token}; hpoint_device=unlink-device"}
   with urllib.request.urlopen(urllib.request.Request(base+"/api/profile/telegram/unlink",data=b"{}",headers=headers,method="POST"),timeout=3) as response:new_cookie=response.headers["Set-Cookie"].split(";",1)[0]
   with urllib.request.urlopen(urllib.request.Request(base+"/api/me",headers={"Cookie":new_cookie+"; hpoint_device=unlink-device"}),timeout=3) as response:site_user=json.load(response)["user"]
   self.assertLess(site_user["id"],0);self.assertEqual(site_user["balance"],333);self.assertFalse(site_user["tg_linked"])
   self.assertEqual(database.get_user(77)["tg_user_id"],77);self.assertEqual(database.get_user(77)["balance"],100)
  finally:
   server.shutdown();thread.join(timeout=3);server.server_close()
if __name__=="__main__":unittest.main()
