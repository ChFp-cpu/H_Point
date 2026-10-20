import json
import sqlite3
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer

from hpoint import database, services
import hpoint.billing as billing
import hpoint.games as games
import hpoint.web as web


class Games(unittest.TestCase):
    def setUp(self):
        self.old_database = database.db
        self.old_services = services.db
        self.old_billing = billing.db
        self.old_web = web.db
        self.db = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        database.db = self.db
        services.db = self.db
        billing.db = self.db
        web.database.db = self.db
        web.db = self.db
        database.init_db()
        database.create_user(1, "Игрок", None)
        self.db.execute("UPDATE users SET balance=100 WHERE user_id=1")

    def tearDown(self):
        database.db = self.old_database
        services.db = self.old_services
        billing.db = self.old_billing
        web.database.db = self.old_database
        web.db = self.old_web
        self.db.close()

    def _allow_next_action(self, session_id):
        stamp = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.db.execute("UPDATE game_sessions SET last_action_at=? WHERE id=?", (stamp, session_id))

    def _complete_safety(self):
        session = games.start_game(1, "safety")
        for choice in (1, 0, 1, 1, 0, 1):
            self._allow_next_action(session["id"])
            session = games.action_game(1, session["id"], {"type": "answer", "choice": choice})
        return session

    def test_safety_rewards_are_server_side_idempotent_and_capped(self):
        completed = self._complete_safety()
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["result"]["score"], 6)
        self.assertEqual(completed["result"]["reward_hp"], 7)
        self.assertEqual(database.get_user(1)["balance"], 107)
        daily = self.db.execute("SELECT awarded_hp,result_hp FROM game_daily_rewards WHERE user_id=1 AND game_code='safety'").fetchone()
        self.assertEqual((daily["awarded_hp"], daily["result_hp"]), (7, 3))

        # A second perfect result on the same title cannot mint reward HP again.
        replay = self._complete_safety()
        self.assertEqual(replay["result"]["reward_hp"], 0)
        self.assertEqual(database.get_user(1)["balance"], 107)
        self.assertEqual(self.db.execute("SELECT COUNT(*) amount FROM game_transactions WHERE user_id=1").fetchone()["amount"], 5)

    def test_actions_reject_client_scores_and_match_hint_is_server_generated(self):
        safety = games.start_game(1, "safety")
        self._allow_next_action(safety["id"])
        with self.assertRaises(ValueError):
            games.action_game(1, safety["id"], {"score": 999999})
        self.assertEqual(self.db.execute("SELECT score FROM game_sessions WHERE id=?", (safety["id"],)).fetchone()["score"], 0)

        bought = games.purchase_item(1, "match_hint", "games-test-purchase-0001")
        self.assertTrue(bought["created"])
        games.equip_item(1, "match_hint")
        match = games.start_game(1, "match")
        self._allow_next_action(match["id"])
        hinted = games.action_game(1, match["id"], {"type": "hint"})
        self.assertIn("hint", hinted["feedback"])
        self.assertEqual(hinted["score"], 0)

    def test_shop_purchase_is_idempotent_and_cannot_overdraw(self):
        self.db.execute("UPDATE users SET balance=5 WHERE user_id=1")
        first = games.purchase_item(1, "crossing_leaf_trail", "games-test-purchase-0002")
        self.assertTrue(first["created"])
        self.assertEqual(first["balance"], 0)
        same = games.purchase_item(1, "crossing_leaf_trail", "games-test-purchase-0002")
        self.assertFalse(same["created"])
        self.assertEqual(same["balance"], 0)
        with self.assertRaises(ValueError):
            games.purchase_item(1, "dispatch_signal", "games-test-purchase-0003")
        self.assertEqual(database.get_user(1)["balance"], 0)

    def test_telegram_bot_exposes_the_same_games_and_safe_callback_sizes(self):
        from hpoint.handlers import _games_menu_kb, _match_kb
        from hpoint.keyboards import main_menu_kb

        menu_callbacks = [button.callback_data for row in _games_menu_kb().inline_keyboard for button in row]
        self.assertIn("g:start:crossing", menu_callbacks)
        self.assertIn("g:start:mission", menu_callbacks)
        self.assertTrue(any("Игры H-Point" in button.text for row in main_menu_kb().keyboard for button in row))
        session = games.start_game(1, "match")
        callbacks = [button.callback_data for row in _match_kb(session).inline_keyboard for button in row]
        self.assertTrue(all(len(value.encode()) <= 64 for value in callbacks))

    def test_games_page_and_http_api_access_controls(self):
        self.assertIn("H-Point Games", web.GAMES_PAGE)
        self.assertIn("/api/games/action", web.GAMES_PAGE)
        server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        token = web.new_sess(1)
        headers = {"Content-Type": "application/json", "Cookie": f"hpoint_session={token}"}

        def post(path, payload, extra_headers=None):
            return urllib.request.urlopen(
                urllib.request.Request(
                    base + path,
                    data=json.dumps(payload).encode(),
                    headers=extra_headers or {"Content-Type": "application/json"},
                    method="POST",
                ),
                timeout=3,
            )

        try:
            with urllib.request.urlopen(base + "/api/games/state", timeout=3) as response:
                self.assertFalse(json.load(response)["authenticated"])
            with self.assertRaises(urllib.error.HTTPError) as unauthenticated:
                post("/api/games/start", {"game": "safety"})
            self.assertEqual(unauthenticated.exception.code, 401)
            unauthenticated.exception.close()
            with post("/api/games/start", {"game": "safety"}, headers) as response:
                session = json.load(response)
            self.assertEqual(session["game"], "safety")
            self._allow_next_action(session["id"])
            with self.assertRaises(urllib.error.HTTPError) as invalid:
                post("/api/games/action", {"session_id": session["id"], "action": {"score": 999999}}, headers)
            self.assertEqual(invalid.exception.code, 409)
            invalid.exception.close()
        finally:
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()


if __name__ == "__main__":
    unittest.main()
