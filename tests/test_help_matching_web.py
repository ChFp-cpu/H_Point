"""Public HTTP contracts: helpers consent, requester selects, chats stay private."""
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch

from hpoint import web, services, database, chat_threads
from test_invitations import InvitationData


class MatchingWeb(InvitationData, unittest.TestCase):
    def setUp(self):
        self.prepare()
        self.tokens={uid:web.new_sess(uid) for uid in (1,2,3,4)}
        self.notifications=patch.object(web,'notify_telegram_user')
        self.notifications.start()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),web.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.thread.join(3);self.server.server_close()
        self.notifications.stop();self.close()

    def call(self,uid,path,data=None):
        headers={'Content-Type':'application/json'}
        if uid:headers['Cookie']='hpoint_session='+self.tokens[uid]
        req=Request('http://127.0.0.1:'+str(self.server.server_port)+path,
            headers=headers,data=json.dumps(data).encode() if data is not None else None)
        try:
            with urlopen(req,timeout=3) as response:return response.status,json.load(response)
        except HTTPError as response:
            with response:return response.status,json.load(response)

    def ok(self,uid,path,data=None):
        status,result=self.call(uid,path,data)
        self.assertEqual(status,200,result)
        return result

    def test_multiple_invitations_consents_private_chats_and_author_choice(self):
        for uid in (2,3):self.ok(1,'/api/smart-match/assign',dict(request_id=self.rid,helper_id=uid))
        self.assertEqual(len(self.ok(1,'/api/assistant/candidates',dict(request_id=self.rid))['offers']),2)
        chats={}
        for uid in (2,3):
            offer=self.ok(uid,'/api/helper/offers')['offers'][0]
            response=self.ok(uid,'/api/helper/offers/respond',dict(request_id=self.rid,accept=True,offer_token=offer['offer_token']))
            self.assertFalse(response['matched']);chats[uid]=response['chat_id']
        self.assertNotEqual(chats[2],chats[3])
        self.assertEqual(database.get_request(self.rid)['status'],'open')
        self.assertEqual(self.call(3,'/api/chats?chat_id='+str(chats[2]))[0],403)
        self.ok(2,'/api/chats/send',dict(request_id=self.rid,chat_id=chats[2],text='Private candidate discussion'))
        matches=self.ok(1,'/api/assistant/candidates',dict(request_id=self.rid))['matches']
        chosen=next(row for row in matches if row['user_id']==2)
        self.assertTrue(chosen['can_select'])
        # A stale invitation button must never turn into author selection.
        self.assertEqual(self.call(1,'/api/smart-match/assign',dict(request_id=self.rid,helper_id=2))[0],409)
        payload=dict(request_id=self.rid,helper_id=2,application_token=chosen['application_token'])
        self.assertEqual(self.call(3,'/api/requests/response/accept',payload)[0],409)
        selected=self.ok(1,'/api/smart-match/assign',payload)
        self.assertTrue(selected['matched']);self.assertEqual(selected['chat_id'],chats[2])
        self.assertEqual(database.get_request(self.rid)['helper_id'],2)
        self.assertFalse(chat_threads.read_chat(self.db,3,chat_id=chats[3])['can_send'])
        self.assertEqual(len(chat_threads.read_chat(self.db,1,chat_id=chats[2])['messages']),1)
        self.assertTrue(services.is_in_queue(2))

    def test_legacy_accept_only_sends_response_and_never_assigns(self):
        for uid in (2,3):
            result=self.ok(uid,'/api/requests/accept',dict(request_id=self.rid))
            self.assertFalse(result['matched']);self.assertTrue(result['chat_id'])
        self.assertIsNone(database.get_request(self.rid)['helper_id'])
        self.assertEqual(len(self.ok(1,'/api/sync')['applications']),2)

    def test_pausing_preserves_preferences_responses_and_existing_chat(self):
        result=self.ok(2,'/api/requests/apply',dict(request_id=self.rid))
        self.ok(2,'/api/helper/preferences',dict(categories=['tech'],availability='Evening',radius_km=12,ready=False))
        profile=self.ok(2,'/api/sync')['user']
        self.assertFalse(profile['helper_ready']);self.assertEqual(profile['helper_radius_km'],12)
        self.assertEqual(len(self.ok(2,'/api/sync')['my_applications']),1)
        self.assertTrue(self.ok(2,'/api/chats?chat_id='+str(result['chat_id']))['chats'][0]['can_send'])
        self.ok(2,'/api/helper/queue',{})
        profile=self.ok(2,'/api/sync')['user']
        self.assertTrue(profile['helper_ready']);self.assertEqual(profile['helper_radius_km'],12)

    def test_guest_can_discover_but_cannot_act_or_read_private_state(self):
        self.assertTrue(self.ok(None,'/api/guest')['guest'])
        for path in ('/api/sync','/api/chats','/api/helper/offers','/api/requests?open=1'):
            self.assertEqual(self.call(None,path)[0],401,path)
        for path,data in (('/api/helper/queue',{}),('/api/requests/apply',dict(request_id=self.rid)),
                ('/api/smart-match/assign',dict(request_id=self.rid,helper_id=2)),
                ('/api/requests/response/accept',dict(request_id=self.rid,helper_id=2,application_token='stale'))):
            self.assertEqual(self.call(None,path,data)[0],401,path)
        self.assertIsNone(database.get_request(self.rid)['helper_id'])


if __name__=='__main__':unittest.main()
