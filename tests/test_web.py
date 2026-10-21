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
  self.assertIn('rel="icon" type="image/svg+xml" href="/assets/favicon.svg"',web.PAGE)
  self.assertIn("timeout:2500",web.PAGE)
  if web.YANDEX_MAPS_API_KEY:self.assertIn("api-maps.yandex.ru",web.PAGE)
  else:self.assertIn("leaflet@1.9.4",web.PAGE)
  self.assertIn("Создать профиль",web.PAGE)
  self.assertIn("resumeTelegramLogin",web.PAGE)
  self.assertIn("/api/helper/offers",web.PAGE)
  self.assertIn("Предложения помощи",web.PAGE)
  self.assertIn("ratingPodium",web.PAGE)
  self.assertIn("activityStats",web.PAGE)
  self.assertIn("globalBalance",web.PAGE)
  self.assertIn("homePulse",web.PAGE)
  self.assertIn("telegramSummary",web.PAGE)
  self.assertIn("renderAuditHeader",web.PAGE)
  self.assertIn("onclick=\"openProfileMenu()\"",web.PAGE)
  self.assertIn("Панель администратора",web.PAGE)
  self.assertIn("Сменить аккаунт",web.PAGE)
  self.assertIn("Выйти из аккаунта",web.PAGE)
  self.assertIn("balanceSkeleton",web.PAGE)
  self.assertIn("grid-template-areas",web.PAGE)
  self.assertIn("hpointAuditWallet",web.PAGE)
  self.assertIn("window.load();",web.PAGE)
  self.assertIn("soloBoard",web.PAGE)
  self.assertIn("ПЕРВОПРОХОДЕЦ СЕЗОНА",web.PAGE)
  self.assertIn("hpointShowcaseGo",web.PAGE)
  self.assertIn("https://*.yandex.ru",web.CSP)
  self.assertIn("https://*.yandex.net",web.CSP)
  self.assertNotIn("unsafe-eval",web.CSP)
 def test_head_for_public_page_and_health(self):
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   base=f"http://127.0.0.1:{server.server_address[1]}"
   for path,content_type in (("/","text/html"),("/api/health","application/json"),("/assets/favicon.svg","image/svg+xml")):
    req=urllib.request.Request(base+path,method="HEAD")
    with urllib.request.urlopen(req,timeout=3) as response:
     self.assertEqual(response.status,200);self.assertEqual(response.headers.get_content_type(),content_type);self.assertEqual(response.read(),b"")
  finally:
   server.shutdown();thread.join(timeout=3);server.server_close()
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
   password="ValidPassword123"
   with post("/api/auth/register",{"name":"New User","email":"new@example.com","password":password,"password_confirm":password}) as response:
    created=json.load(response);cookie=response.headers["Set-Cookie"].split(";",1)[0]
   self.assertTrue(created["ok"])
   with urllib.request.urlopen(urllib.request.Request(base+"/api/me",headers={"Cookie":cookie}),timeout=3) as response:
    self.assertEqual(json.load(response)["user"]["email"],"new@example.com")
   with post("/api/auth/login",{"email":"new@example.com","password":password}) as response:
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
 def test_paid_request_does_not_require_hpoints_and_sync_has_wallet(self):
  database.create_user(1,"Requester")
  self.db.execute("UPDATE users SET balance=0,email_verified=1 WHERE user_id=1")
  token=web.new_sess(1)
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  base=f"http://127.0.0.1:{server.server_address[1]}";headers={"Content-Type":"application/json","Cookie":f"hpoint_session={token}"}
  try:
   payload={"what":"Оплатить работу","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"test","reward_rub":500}
   with urllib.request.urlopen(urllib.request.Request(base+"/api/requests",data=json.dumps(payload).encode(),headers=headers,method="POST"),timeout=3) as response:
    created=json.load(response);self.assertTrue(created["ok"])
   self.assertEqual(database.get_user(1)["balance"],0)
   with urllib.request.urlopen(urllib.request.Request(base+"/api/sync",headers={"Cookie":f"hpoint_session={token}"}),timeout=3) as response:
    synced=json.load(response)
   self.assertIn("wallet",synced);self.assertEqual(synced["wallet"]["balance_rub"],0)
  finally:
   server.shutdown();thread.join(timeout=3);server.server_close()
 def test_user_payload_includes_safe_telegram_summary(self):
  database.create_user(7,"Telegram Person","tgperson")
  self.db.execute("UPDATE users SET tg_user_id=7 WHERE user_id=7")
  payload=web.user_payload(database.get_user(7))
  self.assertTrue(payload["tg_linked"])
  self.assertEqual(payload["telegram"],{"name":"Telegram Person","username":"tgperson","avatar_url":None})
 def test_email_code_is_one_time_and_required_for_email_actions(self):
  old_configured,old_send=web.email_delivery_configured,web.send_email_verification_code
  delivered=[];web.email_delivery_configured=lambda:True;web.send_email_verification_code=lambda address,code:delivered.append((address,code)) or True
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  base=f"http://127.0.0.1:{server.server_address[1]}"
  def post(path,payload,cookie=None):
   headers={"Content-Type":"application/json"}
   if cookie:headers["Cookie"]=cookie
   return urllib.request.urlopen(urllib.request.Request(base+path,data=json.dumps(payload).encode(),headers=headers,method="POST"),timeout=3)
  try:
   password="SecurePass123A"
   with post("/api/auth/register",{"name":"Verified User","email":"verified@example.com","password":password,"password_confirm":password}) as response:
    created=json.load(response);cookie=response.headers["Set-Cookie"].split(";",1)[0]
   self.assertTrue(created["email_verification_sent"]);self.assertEqual(delivered[0][0],"verified@example.com")
   request={"what":"Нужна помощь","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"test"}
   with self.assertRaises(urllib.error.HTTPError) as blocked:
    post("/api/requests",request,cookie)
   self.assertEqual(blocked.exception.code,403);blocked.exception.close()
   with self.assertRaises(urllib.error.HTTPError) as wrong:
    post("/api/auth/email/verify",{"code":"000000"},cookie)
   self.assertEqual(wrong.exception.code,400);wrong.exception.close()
   with post("/api/auth/email/verify",{"code":delivered[0][1]},cookie) as response:self.assertTrue(json.load(response)["verified"])
   with post("/api/requests",request,cookie) as response:self.assertTrue(json.load(response)["ok"])
   with self.assertRaises(urllib.error.HTTPError) as reused:
    post("/api/auth/email/verify",{"code":delivered[0][1]},cookie)
   self.assertEqual(reused.exception.code,400);reused.exception.close()
  finally:
   web.email_delivery_configured,web.send_email_verification_code=old_configured,old_send
   server.shutdown();thread.join(timeout=3);server.server_close()
 def test_registration_requires_matching_strong_password(self):
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  base=f"http://127.0.0.1:{server.server_address[1]}"
  try:
   def register(payload):return urllib.request.urlopen(urllib.request.Request(base+"/api/auth/register",data=json.dumps(payload).encode(),headers={"Content-Type":"application/json"},method="POST"),timeout=3)
   with self.assertRaises(urllib.error.HTTPError) as weak:
    register({"name":"Weak User","email":"weak@example.com","password":"weakpassword12","password_confirm":"weakpassword12"})
   self.assertEqual(weak.exception.code,400);weak.exception.close()
   with self.assertRaises(urllib.error.HTTPError) as short:
    register({"name":"Short User","email":"short@example.com","password":"Aa1234","password_confirm":"Aa1234"})
   self.assertEqual(short.exception.code,400);short.exception.close()
   with self.assertRaises(urllib.error.HTTPError) as mismatch:
    register({"name":"Mismatch User","email":"mismatch@example.com","password":"SecurePass123A","password_confirm":"SecurePass123B"})
   self.assertEqual(mismatch.exception.code,400);mismatch.exception.close()
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
 def test_helper_location_updates_distance_and_active_map_stays_private(self):
  database.create_user(1,"Requester");database.create_user(2,"Helper")
  rid=services.create_request(1,{"what":"Нужна дрель","place":"район","time_needed":"сегодня","urgency":"обычная","details":"Точный адрес","lat":55.75123,"lon":37.61987})
  requester_token=web.new_sess(1);helper_token=web.new_sess(2)
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   base=f"http://127.0.0.1:{server.server_address[1]}"
   def post(path,payload,cookie):
    return urllib.request.urlopen(urllib.request.Request(base+path,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json","Cookie":cookie},method="POST"),timeout=3)
   with post("/api/helper/queue",{"lat":55.752,"lon":37.62},f"hpoint_session={helper_token}") as response:
    self.assertTrue(json.load(response)["ok"])
   with urllib.request.urlopen(urllib.request.Request(base+f"/api/smart-match?request_id={rid}",headers={"Cookie":f"hpoint_session={requester_token}"}),timeout=3) as response:
    candidate=json.load(response)["matches"][0]
   self.assertIsNotNone(candidate["distance_km"]);self.assertIsNone(candidate["lat"]);self.assertIsNone(candidate["lon"])
   with urllib.request.urlopen(urllib.request.Request(base+"/api/map/active",headers={"Cookie":f"hpoint_session={helper_token}"}),timeout=3) as response:
    self.assertEqual(json.load(response)["tasks"],[])
   self.assertTrue(services.try_assign_helper(rid,2))
   with urllib.request.urlopen(urllib.request.Request(base+"/api/map/active",headers={"Cookie":f"hpoint_session={helper_token}"}),timeout=3) as response:
    task=json.load(response)["tasks"][0]
   self.assertEqual(task["id"],rid);self.assertEqual(task["destination"]["lat"],55.75123)
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
  self.db.execute("UPDATE users SET verification_code='A1B2C3D4',verification_code_expires_at=? WHERE user_id=?",((datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(),web_uid))
  token=web.new_sess(web_uid)
  ok,_=database.link_by_code("A1B2C3D4",42,"telegram_user")
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
 def test_session_tokens_are_hashed_and_legacy_tokens_upgrade(self):
  uid=database.create_web_user("Session User","session@example.com","hash")
  token=web.new_sess(uid)
  stored=self.db.execute("SELECT token FROM sessions WHERE user_id=?",(uid,)).fetchone()["token"]
  self.assertNotEqual(stored,token)
  self.assertEqual(len(stored),64)
  legacy="legacy-session-token"
  expiry=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
  self.db.execute("INSERT INTO sessions(token,user_id,expires_at) VALUES(?,?,?)",(legacy,uid,expiry))
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   base=f"http://127.0.0.1:{server.server_address[1]}"
   with urllib.request.urlopen(urllib.request.Request(base+"/api/me",headers={"Cookie":f"hpoint_session={legacy}"}),timeout=3) as response:self.assertTrue(json.load(response)["ok"])
   upgraded=self.db.execute("SELECT token FROM sessions WHERE user_id=? AND token!=?",(uid,stored)).fetchone()["token"]
   self.assertNotEqual(upgraded,legacy)
   self.assertEqual(len(upgraded),64)
  finally:
   server.shutdown();thread.join(timeout=3);server.server_close()
 def test_account_deletion_requires_confirmation_and_revokes_session(self):
  uid=database.create_web_user("Erase Me","erase@example.com","hash");token=web.new_sess(uid)
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   base=f"http://127.0.0.1:{server.server_address[1]}";headers={"Content-Type":"application/json","Cookie":f"hpoint_session={token}"}
   bad=urllib.request.Request(base+"/api/auth/account/delete",data=json.dumps({"confirmation":"нет"}).encode(),headers=headers,method="POST")
   with self.assertRaises(urllib.error.HTTPError) as denied:urllib.request.urlopen(bad,timeout=3)
   self.assertEqual(denied.exception.code,400);denied.exception.close();self.assertIsNotNone(database.get_user(uid))
   good=urllib.request.Request(base+"/api/auth/account/delete",data=json.dumps({"confirmation":"УДАЛИТЬ"}).encode(),headers=headers,method="POST")
   with urllib.request.urlopen(good,timeout=3) as response:self.assertTrue(json.load(response)["ok"])
   self.assertIsNone(database.get_user(uid))
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
 def test_helper_is_offered_request_and_must_confirm(self):
  database.create_user(1,"Requester");database.create_user(2,"Helper")
  rid=services.create_request(1,{"what":"Нужна помощь с техникой","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"test"})
  requester_token=web.new_sess(1);token=web.new_sess(2)
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   base=f"http://127.0.0.1:{server.server_address[1]}";headers={"Cookie":f"hpoint_session={token}","Content-Type":"application/json"}
   with urllib.request.urlopen(urllib.request.Request(base+"/api/requests?open=1",headers=headers),timeout=3) as response:feed=json.load(response)["requests"]
   self.assertEqual([row["id"] for row in feed],[rid]);self.assertNotIn("details",feed[0])
   with urllib.request.urlopen(urllib.request.Request(base+"/api/helper/queue",data=b"{}",headers=headers,method="POST"),timeout=3) as response:claimed=json.load(response)
   self.assertFalse(claimed["matched"])
   request=database.get_request(rid);self.assertIsNone(request["helper_id"]);self.assertEqual(request["status"],"open")
   requester_headers={"Cookie":f"hpoint_session={requester_token}","Content-Type":"application/json"}
   offer=urllib.request.Request(base+"/api/smart-match/assign",data=json.dumps({"request_id":rid,"helper_id":2}).encode(),headers=requester_headers,method="POST")
   with urllib.request.urlopen(offer,timeout=3) as response:self.assertTrue(json.load(response)["offered"])
   self.assertEqual(database.get_request(rid)["status"],"open")
   with urllib.request.urlopen(urllib.request.Request(base+"/api/helper/offers",headers=headers),timeout=3) as response:self.assertEqual(json.load(response)["offers"][0]["request_id"],rid)
   response_request=urllib.request.Request(base+"/api/helper/offers/respond",data=json.dumps({"request_id":rid,"accept":True}).encode(),headers=headers,method="POST")
   with urllib.request.urlopen(response_request,timeout=3) as response:self.assertTrue(json.load(response)["accepted"])
   request=database.get_request(rid);self.assertEqual(request["helper_id"],2);self.assertEqual(request["status"],"in_progress")
   self.assertIsNotNone(web.chat_for_request(rid))
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
 def test_admin_dashboard_is_private_and_can_close_active_request(self):
  database.create_user(1,"Member");database.create_user(99,"Admin")
  self.db.execute("UPDATE users SET role='admin' WHERE user_id=99")
  rid=services.create_request(1,{"what":"Need help","place":"centre","time_needed":"today","urgency":"normal","details":"test"})
  member_token,admin_token=web.new_sess(1),web.new_sess(99)
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   base=f"http://127.0.0.1:{server.server_address[1]}"
   denied=urllib.request.Request(base+"/api/admin/dashboard",headers={"Cookie":f"hpoint_session={member_token}"})
   with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(denied,timeout=3)
   self.assertEqual(error.exception.code,403);error.exception.close()
   allowed=urllib.request.Request(base+"/api/admin/dashboard",headers={"Cookie":f"hpoint_session={admin_token}"})
   with urllib.request.urlopen(allowed,timeout=3) as response:dashboard=json.load(response)
   self.assertEqual(dashboard["summary"]["requests"]["open"],1)
   close=urllib.request.Request(base+"/api/admin/requests/cancel",data=json.dumps({"request_id":rid,"reason":"duplicate"}).encode(),headers={"Cookie":f"hpoint_session={admin_token}","Content-Type":"application/json"},method="POST")
   with urllib.request.urlopen(close,timeout=3) as response:self.assertTrue(json.load(response)["ok"])
   self.assertEqual(database.get_request(rid)["status"],"cancelled")
  finally:
   server.shutdown();thread.join(timeout=3);server.server_close()
if __name__=="__main__":unittest.main()
