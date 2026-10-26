import unittest,sqlite3,urllib.request,urllib.error,json,threading
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from hpoint import database,services
import hpoint.billing as billing
import hpoint.web as web
class Web(unittest.TestCase):
 def setUp(self):
  self.old=database.db;self.db=sqlite3.connect(":memory:",isolation_level=None,check_same_thread=False);self.db.row_factory=sqlite3.Row
  database.db=self.db;services.db=self.db;billing.db=self.db;web.database.db=self.db;web.db=self.db;database.init_db();self.notification_patch=patch.object(web,"notify_telegram_user",return_value=False);self.notification_patch.start()
 def tearDown(self):self.notification_patch.stop();database.db=self.old;services.db=self.old;billing.db=self.old;web.database.db=self.old;web.db=self.old;self.db.close()
 def add_user(self,user_id,name,username=None,**options):
  """A normal web participant has a confirmed synthetic email."""
  database.create_user(user_id,name,username,**options)
  self.db.execute("UPDATE users SET email=COALESCE(email,?),email_verified=1,password_hash=COALESCE(password_hash,?) WHERE user_id=?",(f"participant{user_id}@example.test",web.ph("SyntheticPass1"),user_id))
  return database.get_user(user_id)
 def test_web_shares_logic(self):
  self.add_user(42,"Web",None);rid=services.create_request(42,{"what":"Помочь с компьютером","place":"x","time_needed":"x","urgency":"x","details":"x"})
  self.assertEqual(database.get_request(rid)["category"],"tech")
 def test_health_get_and_head_report_database_outage(self):
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   with patch.object(database,"db") as unavailable:
    unavailable.execute.side_effect=RuntimeError("Synthetic database outage")
    for method in ("GET","HEAD"):
     request=urllib.request.Request(f"http://127.0.0.1:{server.server_port}/api/health",method=method)
     with self.assertRaises(urllib.error.HTTPError) as raised:urllib.request.urlopen(request,timeout=3)
     self.assertEqual(raised.exception.code,503)
     raised.exception.close()
  finally:server.shutdown();thread.join(timeout=3);server.server_close()
 def test_request_promotion_uses_catalog_prices_without_creating_a_purchase(self):
  self.add_user(42,"Web",tg_user_id=42,web_verified=True);token=web.new_sess(42)
  before=database.get_user(42)["balance"]
  catalog={**web.MONETIZATION_ITEMS,"boost":{**web.MONETIZATION_ITEMS["boost"],"rub":63,"hp":29}}
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   with patch.object(web,"MONETIZATION_ITEMS",catalog):
    request=urllib.request.Request(f"http://127.0.0.1:{server.server_port}/api/sync",headers={"Cookie":"hpoint_session="+token})
    with urllib.request.urlopen(request,timeout=3) as response:promotion=json.load(response)["request_promotion"]
   self.assertEqual((promotion["item_type"],promotion["rub"],promotion["hp"]),("boost",63,29))
   self.assertEqual(database.get_user(42)["balance"],before)
   self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM billing_invoices").fetchone()["n"],0)
  finally:server.shutdown();thread.join(timeout=3);server.server_close()
 def test_helper_preferences_and_two_sided_offer_notifications(self):
  self.add_user(11,"Author",tg_user_id=11,web_verified=True)
  self.add_user(22,"Helper",tg_user_id=22,web_verified=True)
  payload={"what":"Настроить компьютер","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"test","category":"tech"}
  rid=services.create_request(11,payload);services.create_request(22,payload)
  tokens={uid:web.new_sess(uid) for uid in (11,22)}
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  def request(uid,path,data=None):
   headers={"Cookie":"hpoint_session="+tokens[uid],"Content-Type":"application/json"}
   req=urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}"+path,headers=headers,data=json.dumps(data).encode() if data is not None else None)
   with urllib.request.urlopen(req,timeout=3) as response:return json.load(response)
  try:
   prefs=request(22,"/api/helper/preferences",{"categories":["tech"],"availability":"После 18:00","ready":True})
   self.assertTrue(prefs["user"]["helper_ready"]);self.assertEqual(prefs["user"]["helper_availability"],"После 18:00")
   matches=request(11,"/api/assistant/candidates",{"request_id":rid})["matches"]
   self.assertEqual(matches[0]["user_id"],22)
   with patch.object(web,"notify_telegram_user") as notify:
    self.assertTrue(request(11,"/api/smart-match/assign",{"request_id":rid,"helper_id":22})["offered"])
    self.assertEqual({call.args[0] for call in notify.call_args_list},{11,22})
   self.assertEqual(request(22,"/api/helper/offers")["offers"][0]["request_id"],rid)
   self.assertEqual(request(11,"/api/sync")["outgoing_offers"][0]["helper_name"],"Helper")
   with patch.object(web,"notify_telegram_user") as notify:
    self.assertTrue(request(22,"/api/helper/offers/respond",{"request_id":rid,"accept":True,"offer_token":services.get_current_helper_offer(rid)["offer_token"]})["accepted"])
    self.assertEqual({call.args[0] for call in notify.call_args_list},{11,22})
   self.assertEqual(request(11,"/api/sync")["outgoing_offers"],[])
   self.assertEqual(len(request(22,"/api/chats")["chats"]),1)
   web_uid=database.create_web_user("Email member","league@example.test","hash")
   self.assertLess(web_uid,0)
   public=request(11,"/api/community/profile?id="+str(web_uid))["profile"]
   self.assertEqual(public["id"],web_uid);self.assertEqual(public["stats"]["helped"],0)
  finally:server.shutdown();thread.join(timeout=3);server.server_close()
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
 def test_site_navigation_has_three_primary_routes_and_keeps_tools_reachable(self):
  self.assertIn('SITE_NAV_UI',web.__dict__)
  self.assertIn('sitePrimaryNav',web.PAGE)
  self.assertIn('Главная',web.SITE_NAV_UI)
  self.assertIn('Помощь',web.SITE_NAV_UI)
  self.assertIn('Игры',web.SITE_NAV_UI)
  self.assertIn("legacyHead.remove()",web.SITE_NAV_UI)
  self.assertIn("['requests'",web.SITE_NAV_UI)
  self.assertIn("['match'",web.SITE_NAV_UI)
  self.assertIn("['chat'",web.SITE_NAV_UI)
  self.assertIn("['map'",web.SITE_NAV_UI)
  self.assertIn("['history'",web.SITE_NAV_UI)
  self.assertIn("['wallet'",web.SITE_NAV_UI)
  self.assertIn("['billing'",web.SITE_NAV_UI)
  self.assertIn("window.history.pushState",web.SITE_NAV_UI)
  self.assertNotIn(".tabs{display:none",web.SITE_NAV_CSS)
 def test_workspace_shell_uses_real_data_without_a_card_catalog(self):
  self.assertIn('WORKSPACE_SHELL_UI',web.__dict__)
  self.assertIn('workspaceHelpGrid',web.WORKSPACE_SHELL_CSS)
  self.assertIn('workspaceMapSlot',web.WORKSPACE_SHELL_UI)
  self.assertIn("/api/sync",web.WORKSPACE_SHELL_UI)
  self.assertIn("/api/requests?open=1",web.WORKSPACE_SHELL_UI)
  self.assertIn("/api/assistant/candidates",web.WORKSPACE_SHELL_UI)
  self.assertIn("/api/chats/send",web.WORKSPACE_SHELL_UI)
  self.assertIn("/api/wallet",web.WORKSPACE_SHELL_UI)
  self.assertIn("/api/billing",web.WORKSPACE_SHELL_UI)
  self.assertIn("openWorkspaceChat",web.WORKSPACE_SHELL_UI)
  self.assertIn("state.profileDetails",web.WORKSPACE_SHELL_UI)
  self.assertIn('@media(max-width:900px)',web.WORKSPACE_HEADER_CSS)
  self.assertIn('@media(max-width:380px)',web.WORKSPACE_HEADER_CSS)
  self.assertIn('.workspaceSectionTabs{display:grid',web.WORKSPACE_HEADER_CSS)
  self.assertIn('font-size:0!important',web.WORKSPACE_HEADER_CSS)
  self.assertNotIn("Что ещё доступно",web.WORKSPACE_SHELL_UI)
  self.assertNotIn("Всё готово",web.WORKSPACE_SHELL_UI)
 def test_games_page_uses_server_clock_for_smooth_crossing(self):
  self.assertIn("requestAnimationFrame(drawCars)",web.GAMES_PAGE)
  self.assertIn("elapsed_ms",web.GAMES_PAGE)
  self.assertIn("performance.now()",web.GAMES_PAGE)
  self.assertIn("anchorCrossingClock",web.GAMES_PAGE)
  self.assertIn("type:'pause'",web.GAMES_PAGE)
  self.assertIn("visibilitychange",web.GAMES_PAGE)
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
   delivered=[]
   with patch.object(web,"email_delivery_configured",return_value=True),patch.object(web,"send_email_verification_code",side_effect=lambda address,code:delivered.append(code) or True):
    with post("/api/auth/register",{"name":"New User","email":"new@example.com","password":password,"password_confirm":password}) as response:
     created=json.load(response);pending=response.headers["Set-Cookie"].split(";",1)[0]
   self.assertTrue(created["ok"])
   self.assertTrue(created["verification_required"])
   with self.assertRaises(urllib.error.HTTPError) as unconfirmed:
    urllib.request.urlopen(urllib.request.Request(base+"/api/me",headers={"Cookie":pending}),timeout=3)
   self.assertEqual(unconfirmed.exception.code,401);unconfirmed.exception.close()
   with post("/api/auth/email/verify",{"code":delivered[0]},pending) as response:
    self.assertTrue(json.load(response)["verified"]);cookie=response.headers["Set-Cookie"].split(";",1)[0]
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
  self.add_user(1,"Requester")
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
 def test_public_wallet_only_returns_test_funds(self):
  self.add_user(1,"Email member")
  database.grant_registration_bonus(1,500)
  database.wallet_add_entry(1,350,"payment","Preserved private real funds","synthetic-real-credit",test_amount_rub=0)
  token=web.new_sess(1)
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   request=urllib.request.Request(f"http://127.0.0.1:{server.server_port}/api/wallet",headers={"Cookie":"hpoint_session="+token})
   with urllib.request.urlopen(request,timeout=3) as response:wallet=json.load(response)["wallet"]
   self.assertTrue(wallet["test_only"])
   self.assertEqual(wallet["balance_rub"],500);self.assertEqual(wallet["test_balance_rub"],500)
   self.assertEqual(wallet["available_total_rub"],500)
   self.assertNotIn("real_balance_rub",wallet)
   self.assertNotIn("Preserved private real funds",str(wallet))
   self.assertEqual(database.wallet_summary(1)["balance_rub"],350)
  finally:server.shutdown();thread.join(timeout=3);server.server_close()
 def test_user_payload_includes_safe_telegram_summary(self):
  self.add_user(7,"Telegram Person","tgperson")
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
   self.assertEqual(blocked.exception.code,401);blocked.exception.close()
   with self.assertRaises(urllib.error.HTTPError) as wrong:
    post("/api/auth/email/verify",{"code":"000000"},cookie)
   self.assertEqual(wrong.exception.code,400);wrong.exception.close()
   with post("/api/auth/email/verify",{"code":delivered[0][1]},cookie) as response:
    self.assertTrue(json.load(response)["verified"]);cookie=response.headers["Set-Cookie"].split(";",1)[0]
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
    register({"name":"Short User","email":"short@example.com","password":"Aa123","password_confirm":"Aa123"})
   self.assertEqual(short.exception.code,400);short.exception.close()
   with self.assertRaises(urllib.error.HTTPError) as mismatch:
    register({"name":"Mismatch User","email":"mismatch@example.com","password":"SecurePass123A","password_confirm":"SecurePass123B"})
   self.assertEqual(mismatch.exception.code,400);mismatch.exception.close()
  finally:
   server.shutdown();thread.join(timeout=3);server.server_close()
 def test_unconfigured_sms_does_not_send_or_create_a_verification_code(self):
  self.add_user(77,"Проверка контактов",tg_user_id=77,web_verified=True)
  self.db.execute("UPDATE users SET phone='+79990000000',email_verified=1 WHERE user_id=77")
  token=web.new_sess(77)
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   base=f"http://127.0.0.1:{server.server_address[1]}"
   headers={"Content-Type":"application/json","Cookie":f"hpoint_session={token}"}
   with patch.object(web,"sms_delivery_configured",return_value=False),patch.object(web,"send_phone_verification_code") as send:
    with self.assertRaises(urllib.error.HTTPError) as unavailable:
     urllib.request.urlopen(urllib.request.Request(base+"/api/profile/phone/send-code",data=b"{}",headers=headers,method="POST"),timeout=3)
    self.assertEqual(unavailable.exception.code,503)
    result=json.load(unavailable.exception);unavailable.exception.close()
    self.assertNotIn("code",result);send.assert_not_called()
    self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM phone_verification_codes WHERE user_id=77").fetchone()["n"],0)
    user=web.user_payload(database.get_user(77))
    self.assertTrue(user["tg_linked"]);self.assertTrue(user["email_verified"])
    self.assertFalse(user["sms_delivery_configured"])
  finally:
   server.shutdown();thread.join(timeout=3);server.server_close()
 def test_telegram_registration_routes_are_gone_without_accounts_or_sessions(self):
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   base=f"http://127.0.0.1:{server.server_port}"
   routes=[urllib.request.Request(base+"/api/auth/telegram/start",data=b"{}",headers={"Content-Type":"application/json"},method="POST"),urllib.request.Request(base+"/api/auth/telegram/complete?ticket=legacy-ticket")]
   with patch.object(database,"complete_telegram_auth_ticket") as complete:
    for request in routes:
     with self.assertRaises(urllib.error.HTTPError) as denied:urllib.request.urlopen(request,timeout=3)
     with denied.exception as response:
      self.assertEqual(response.code,410);self.assertFalse(response.headers.get_all("Set-Cookie"));self.assertIn("email",json.load(response)["error"])
    complete.assert_not_called()
   self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM users").fetchone()["n"],0)
   self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM sessions").fetchone()["n"],0)
  finally:server.shutdown();thread.join(timeout=3);server.server_close()

 def test_map_and_search_do_not_leak_exact_coordinates_or_details(self):
  self.add_user(1,"Requester");self.add_user(2,"Viewer")
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
 def test_public_open_feed_preserves_status_and_excludes_history_and_own_requests(self):
  for uid in (1,2,3):self.add_user(uid,f"User {uid}",tg_user_id=uid,web_verified=True)
  payload={"what":"Помочь с техникой","place":"Скрытый адрес","time_needed":"сегодня","urgency":"обычная","details":"Личные сведения","lat":55.75,"lon":37.62}
  opened=services.create_request(1,payload)
  done=services.create_request(1,payload);self.assertTrue(services.try_assign_helper(done,3));self.assertTrue(services.complete_request(done,3,confirmed_by=1))
  active=services.create_request(1,payload);self.assertTrue(services.try_assign_helper(active,3))
  cancelled=services.create_request(1,payload);self.assertTrue(services.cancel_request(cancelled,1,"test"))
  own=services.create_request(2,payload)
  token=web.new_sess(2);server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   for path in ("/api/requests?open=1","/api/search"):
    request=urllib.request.Request(f"http://127.0.0.1:{server.server_port}"+path,headers={"Cookie":"hpoint_session="+token})
    with urllib.request.urlopen(request,timeout=3) as response:rows=json.load(response)["requests"]
    self.assertEqual([row["id"] for row in rows],[opened])
    self.assertEqual(rows[0]["status"],"open");self.assertEqual(rows[0]["status_title"],"Ожидает помощника")
    self.assertNotIn("details",rows[0]);self.assertIsNone(rows[0]["lat"]);self.assertIsNone(rows[0]["lon"]);self.assertNotEqual(rows[0]["place"],payload["place"])
   self.assertEqual([database.get_request(rid)["status"] for rid in (opened,done,active,cancelled,own)],["open","done","in_progress","cancelled","open"])
  finally:server.shutdown();thread.join(timeout=3);server.server_close()
 def test_helper_location_updates_distance_and_active_map_stays_private(self):
  self.add_user(1,"Requester");self.add_user(2,"Helper")
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
 def test_legacy_telegram_ticket_cannot_create_a_web_session(self):
  database.create_user(42,"Legacy Telegram",tg_user_id=42)
  ticket="one-time-test-ticket";database.create_web_login_ticket(42,ticket)
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   base=f"http://127.0.0.1:{server.server_port}"
   for _ in range(2):
    with self.assertRaises(urllib.error.HTTPError) as denied:urllib.request.urlopen(base+"/auth/telegram?ticket="+ticket,timeout=3)
    with denied.exception as response:
     self.assertEqual(response.code,410);self.assertIsNone(response.headers.get("Location"));self.assertFalse(response.headers.get_all("Set-Cookie"))
   self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM sessions").fetchone()["n"],0)
   self.assertFalse(database.get_user(42)["email_verified"])
  finally:server.shutdown();thread.join(timeout=3);server.server_close()

 def test_bot_link_preserves_email_identity_and_syncs_without_merging_accounts(self):
  self.add_user(42,"Separate Telegram profile",tg_user_id=42)
  legacy_request=services.create_request(42,{"what":"Помощь другого профиля","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"Separate data"})
  web_uid=database.create_web_user("Site","site@example.test",web.ph("SyntheticPass1"))
  self.db.execute("UPDATE users SET email_verified=1 WHERE user_id=?",(web_uid,))
  site_request=services.create_request(web_uid,{"what":"Помощь до привязки","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"site"})
  conflict_code=database.create_link_code(web_uid)
  self.assertFalse(database.link_by_code(conflict_code,42,"separate")[0])
  self.assertEqual(database.get_request(legacy_request)["requester_id"],42)
  token=web.new_sess(web_uid);code=database.create_link_code(web_uid)
  self.assertEqual(database.link_by_code(code,142,"linked_client"),(True,"linked"))
  self.assertEqual(database.get_user_by_tg(142)["user_id"],web_uid)
  self.assertIsNotNone(database.get_user(42))
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   base=f"http://127.0.0.1:{server.server_port}"
   request=urllib.request.Request(base+"/api/requests/mine",headers={"Cookie":f"hpoint_session={token}"})
   with urllib.request.urlopen(request,timeout=3) as response:initial=json.load(response)
   self.assertEqual(initial["current_user_id"],web_uid)
   self.assertEqual({r["id"] for r in initial["requests"]},{site_request})
   bot_request=services.create_request(database.get_user_by_tg(142)["user_id"],{"what":"Помощь через привязанный бот","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"bot"})
   with urllib.request.urlopen(request,timeout=3) as response:refreshed=json.load(response)
   self.assertEqual({r["id"] for r in refreshed["requests"]},{site_request,bot_request})
   self.assertNotIn(legacy_request,{r["id"] for r in refreshed["requests"]})
  finally:server.shutdown();thread.join(timeout=3);server.server_close()

 def test_parallel_sessions_keep_other_device_signed_in(self):
  uid=database.create_web_user("Parallel","parallel@example.com","hash")
  self.db.execute("UPDATE users SET email_verified=1 WHERE user_id=?",(uid,))
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
  self.db.execute("UPDATE users SET email_verified=1 WHERE user_id=?",(uid,))
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
  self.db.execute("UPDATE users SET email_verified=1 WHERE user_id=?",(uid,))
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
  for uid,name in ((1,"Requester"),(2,"Helper"),(3,"Outsider")):self.add_user(uid,name)
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
   with patch.object(web,"notify_telegram_user") as notice:
    with request("/api/chats/send","POST",{"request_id":rid,"text":"Здравствуйте! <b>Текст</b> & детали\nВторая строка"},1) as response:
     self.assertEqual(json.load(response)["messages"][-1]["text"],"Здравствуйте! <b>Текст</b> & детали\nВторая строка")
    notice.assert_called_once()
    self.assertEqual(notice.call_args.args[0],2)
    self.assertIn("Здравствуйте! &lt;b&gt;Текст&lt;/b&gt; &amp; детали\nВторая строка",notice.call_args.args[1])
    self.assertIn("Нужна помощь",notice.call_args.args[1]);self.assertIn(f"/#/help/chat/{rid}",notice.call_args.args[1]);self.assertNotIn("заявка №",notice.call_args.args[1])
   with request(f"/api/chats?request_id={rid}",uid=2) as response:
    chat=json.load(response)["chats"][0]
   self.assertEqual(chat["messages"][-1]["text"],"Здравствуйте! <b>Текст</b> & детали\nВторая строка")
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
  self.add_user(1,"User")
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
 def test_telegram_chat_notice_keeps_full_text_and_escapes_html(self):
  from html import unescape
  from hpoint.chat_notifications import chat_notification
  text="<&>\n🙂"*200
  body=chat_notification(31,"<Автор>",text,"Помощь <рядом>")
  self.assertIn(text,unescape(body))
  self.assertIn("&lt;Автор&gt;",body)
  self.assertIn("Помощь &lt;рядом&gt;",body);self.assertIn("/#/help/chat/31",body);self.assertNotIn("заявка №",body)
  self.assertLess(len(unescape(body)),4096)
 def test_bot_reply_targets_the_notified_request_and_rejects_outsiders(self):
  import asyncio
  from types import SimpleNamespace
  from unittest.mock import AsyncMock
  from hpoint import handlers
  for uid in (1,2,3):self.add_user(uid,f"Участник {uid}")
  payload={"what":"Чат заявки","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"test"}
  old=services.create_request(1,payload);self.assertTrue(services.try_assign_helper(old,2));services.complete_request(old,2,confirmed_by=1)
  current=services.create_request(3,payload);self.assertTrue(services.try_assign_helper(current,2))
  text="Ответ <с деталями> & второй строкой\nСпасибо!"
  message=SimpleNamespace(chat=SimpleNamespace(type="private"),from_user=SimpleNamespace(id=2),text=f"/chat #{old} {text}",answer=AsyncMock())
  bot=SimpleNamespace(send_message=AsyncMock())
  with patch.object(handlers,"db",self.db),patch.object(handlers,"ensure_registered",AsyncMock(return_value=True)):
   asyncio.run(handlers.cmd_chat(message,None,bot))
   self.assertEqual(bot.send_message.call_args.args[0],1)
   self.assertIn("Ответ &lt;с деталями&gt; &amp; второй строкой",bot.send_message.call_args.args[1])
   saved=self.db.execute("SELECT m.text,c.request_id FROM chat_messages m JOIN chats c ON c.id=m.chat_id").fetchall()
   self.assertEqual([(row["request_id"],row["text"]) for row in saved],[(old,text)])
   message.from_user.id=3;bot.send_message.reset_mock()
   asyncio.run(handlers.cmd_chat(message,None,bot));bot.send_message.assert_not_called()
   self.assertEqual(self.db.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0],1)
 def test_legacy_telegram_login_never_redirects_even_with_a_known_destination(self):
  self.add_user(1,"Email member")
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  from urllib.parse import urlencode
  try:
   for index,target in enumerate(("/games?game=crossing","https://example.test","//example.test")):
    ticket=f"game-destination-{index}";database.create_web_login_ticket(1,ticket)
    with self.assertRaises(urllib.error.HTTPError) as denied:urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/auth/telegram?"+urlencode({"ticket":ticket,"next":target}),timeout=3)
    with denied.exception as response:
     self.assertEqual(response.code,410);self.assertIsNone(response.headers.get("Location"));self.assertFalse(response.headers.get_all("Set-Cookie"))
   self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM sessions").fetchone()["n"],0)
  finally:server.shutdown();thread.join(timeout=3);server.server_close()

 def test_helper_is_offered_request_and_must_confirm(self):
  self.add_user(1,"Requester");self.add_user(2,"Helper")
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
   response_request=urllib.request.Request(base+"/api/helper/offers/respond",data=json.dumps({"request_id":rid,"accept":True,"offer_token":services.get_current_helper_offer(rid)["offer_token"]}).encode(),headers=headers,method="POST")
   with urllib.request.urlopen(response_request,timeout=3) as response:self.assertTrue(json.load(response)["accepted"])
   request=database.get_request(rid);self.assertEqual(request["helper_id"],2);self.assertEqual(request["status"],"in_progress")
   self.assertIsNotNone(web.chat_for_request(rid))
  finally:
   server.shutdown();thread.join(timeout=3);server.server_close()
 def test_helper_with_own_request_can_accept_another_request(self):
  self.add_user(1,"Requester");self.add_user(2,"Busy helper")
  target=services.create_request(1,{"what":"Нужна помощь","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"test"})
  services.create_request(2,{"what":"Моя активная заявка","place":"центр","time_needed":"сегодня","urgency":"обычная","details":"test"})
  token=web.new_sess(2)
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   base=f"http://127.0.0.1:{server.server_address[1]}";headers={"Cookie":f"hpoint_session={token}","Content-Type":"application/json"}
   req=urllib.request.Request(base+"/api/requests/accept",data=json.dumps({"request_id":target}).encode(),headers=headers,method="POST")
   with urllib.request.urlopen(req,timeout=3) as response:self.assertTrue(json.load(response)["matched"])
   self.assertFalse(services.is_in_queue(2))
   self.assertEqual(database.get_request(target)["status"],"in_progress")
   self.assertEqual(database.get_request(target)["helper_id"],2)
   self.assertIsNotNone(web.chat_for_request(target))
  finally:
   server.shutdown();thread.join(timeout=3);server.server_close()
 def test_points_purchase_and_device_profile_switching(self):
  self.add_user(1,"First");self.add_user(2,"Second")
  self.db.execute("UPDATE users SET balance=1000 WHERE user_id=1")
  device="shared-device";first=web.new_sess(1,device);web.new_sess(2,device)
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  base=f"http://127.0.0.1:{server.server_address[1]}";cookie=f"hpoint_session={first}; hpoint_device={device}"
  try:
   def post(path,payload,cookie_value=cookie):
    return urllib.request.urlopen(urllib.request.Request(base+path,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json","Cookie":cookie_value},method="POST"),timeout=3)
   with post("/api/payments/hp",{"item_type":"pro","purchase_key":"test-hp-one"}) as response:self.assertTrue(json.load(response)["created"])
   self.assertEqual(database.get_user(1)["balance"],910)
   with urllib.request.urlopen(urllib.request.Request(base+"/api/profiles",headers={"Cookie":cookie}),timeout=3) as response:self.assertEqual(len(json.load(response)["profiles"]),2)
   with post("/api/profiles/switch",{"user_id":2}) as response: switched=response.headers["Set-Cookie"].split(";",1)[0]
   with urllib.request.urlopen(urllib.request.Request(base+"/api/me",headers={"Cookie":switched+"; hpoint_device="+device}),timeout=3) as response:self.assertEqual(json.load(response)["user"]["id"],2)
  finally:
   server.shutdown();thread.join(timeout=3);server.server_close()
 def test_unlink_telegram_preserves_website_data(self):
  self.add_user(77,"Linked",tg_user_id=77,web_verified=True);self.db.execute("UPDATE users SET email='linked@example.com',password_hash='hash',email_verified=1,balance=333 WHERE user_id=77")
  token=web.new_sess(77,"unlink-device")
  server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   base=f"http://127.0.0.1:{server.server_address[1]}";headers={"Content-Type":"application/json","Cookie":f"hpoint_session={token}; hpoint_device=unlink-device"}
   with urllib.request.urlopen(urllib.request.Request(base+"/api/profile/telegram/unlink",data=b"{}",headers=headers,method="POST"),timeout=3) as response:new_cookie=response.headers["Set-Cookie"].split(";",1)[0]
   with urllib.request.urlopen(urllib.request.Request(base+"/api/me",headers={"Cookie":new_cookie+"; hpoint_device=unlink-device"}),timeout=3) as response:site_user=json.load(response)["user"]
   self.assertEqual(site_user["id"],77);self.assertEqual(site_user["balance"],333);self.assertFalse(site_user["tg_linked"])
   self.assertIsNone(database.get_user(77)["tg_user_id"]);self.assertEqual(database.get_user(77)["balance"],333);self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM users").fetchone()["n"],1)
  finally:
   server.shutdown();thread.join(timeout=3);server.server_close()
 def test_admin_dashboard_is_private_and_can_close_active_request(self):
  self.add_user(1,"Member");self.add_user(99,"Admin")
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
