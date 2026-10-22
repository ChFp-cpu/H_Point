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
        while session["status"] == "active":
            state = json.loads(self.db.execute("SELECT state FROM game_sessions WHERE id=?", (session["id"],)).fetchone()["state"])
            choice = state["scenarios"][state["index"]]["correct"]
            self._allow_next_action(session["id"])
            session = games.action_game(1, session["id"], {"type": "answer", "choice": choice})
        return session

    def test_learning_content_is_versioned_frozen_and_keeps_answers_server_side(self):
        from hpoint.game_content import MISSION_SCENARIOS, SAFETY_SCENARIOS

        self.assertGreaterEqual(len(SAFETY_SCENARIOS), 20)
        self.assertGreaterEqual(len(MISSION_SCENARIOS), 20)
        self.assertTrue(all(item["id"] and item["version"] and item["published"] for item in SAFETY_SCENARIOS + MISSION_SCENARIOS))

        first = games.start_game(1, "safety")
        public_scene = first["game_state"]["scenario"]
        self.assertNotIn("correct", public_scene)
        self.assertNotIn("explanation", public_scene)
        stored = json.loads(self.db.execute("SELECT state FROM game_sessions WHERE id=?", (first["id"],)).fetchone()["state"])
        self.assertEqual(stored["content_version"], "2026.10")
        self.assertEqual(len(stored["scenario_ids"]), 6)
        self.assertEqual(len(set(stored["scenario_ids"])), 6)
        self.assertIn("correct", stored["scenarios"][0])
        games.abandon_game(1, first["id"])

        second = games.start_game(1, "safety")
        second_state = json.loads(self.db.execute("SELECT state FROM game_sessions WHERE id=?", (second["id"],)).fetchone()["state"])
        self.assertFalse(set(stored["scenario_ids"]) & set(second_state["scenario_ids"]))

    def test_crossing_clock_pause_and_collision_are_server_authoritative(self):
        session = games.start_game(1, "crossing")
        self.assertIn("server_time_ms", session["game_state"])
        self.assertIn("tick_ms", session["game_state"])
        paused = games.action_game(1, session["id"], {"type": "pause"})
        self.assertTrue(paused["game_state"]["paused"])
        resumed = games.action_game(1, session["id"], {"type": "resume"})
        self.assertFalse(resumed["game_state"]["paused"])

        state = json.loads(self.db.execute("SELECT state FROM game_sessions WHERE id=?", (session["id"],)).fetchone()["state"])
        state.update({"player": {"x": 0, "y": 0}, "elapsed_ms": 0, "clock_anchor_at": games._now_text(), "paused": False, "shield": 0})
        state["player"]["x"] = games._crossing_lane(state["seed"], 1, 0)[0]
        self.db.execute("UPDATE game_sessions SET state=? WHERE id=?", (json.dumps(state), session["id"]))
        self._allow_next_action(session["id"])
        collision = games.action_game(1, session["id"], {"direction": "up", "score": 999999})
        self.assertEqual(collision["status"], "completed")
        self.assertEqual(collision["result"]["outcome"], "Маршрут прерван")
        self.assertLess(collision["score"], 999999)

    def test_legacy_learning_sessions_keep_their_original_bank(self):
        self.assertEqual(games._learning_scenes({}, "safety"), list(games.LEGACY_SAFETY_SCENARIOS))
        self.assertEqual(games._learning_scenes({}, "mission"), list(games.LEGACY_MISSION_SCENARIOS))
        self.assertEqual(len(games._learning_scenes({}, "mission")), 5)

    def test_crossing_traffic_is_continuous_and_stationary_players_can_be_hit(self):
        from unittest.mock import patch

        start = datetime(2026, 10, 22, tzinfo=timezone.utc)
        with patch.object(games, "_now", return_value=start):
            state = games._make_crossing_state(1, set())
        state.update({"seed": 0, "player": {"x": 0, "y": 1}, "distance": 1})
        self.assertFalse(games._crossing_hit_between(state, 0, 1, 0, 0))
        self.assertTrue(games._crossing_hit_between(state, 0, 1, 0, 750))
        self.assertFalse(games._crossing_hit_between(state, 0, 0, 0, 100000))
        with patch.object(games, "_now", return_value=start + timedelta(milliseconds=750)):
            _, finished, result = games._crossing_action(state, {"type": "sync", "score": 999999})
        self.assertTrue(finished)
        self.assertEqual(result["outcome"], "Маршрут прерван")
        self.assertEqual(result["score"], 10)

    def test_crossing_pause_freezes_the_continuous_clock(self):
        from unittest.mock import patch

        start = datetime(2026, 10, 22, tzinfo=timezone.utc)
        with patch.object(games, "_now", return_value=start):
            state = games._make_crossing_state(1, set())
            games._crossing_action(state, {"type": "pause"})
        with patch.object(games, "_now", return_value=start + timedelta(seconds=20)):
            self.assertEqual(games._crossing_elapsed_ms(state), 0)
            games._crossing_action(state, {"type": "resume"})
        with patch.object(games, "_now", return_value=start + timedelta(seconds=21)):
            self.assertEqual(games._crossing_elapsed_ms(state), 1000)

    def test_old_crossing_sessions_upgrade_once_without_resetting_the_world(self):
        from unittest.mock import patch

        start = datetime(2026, 10, 22, tzinfo=timezone.utc)
        state = games._make_crossing_state(1, set())
        state.pop("clock_anchor_at")
        state.pop("elapsed_ms")
        state["ticks"] = 5
        seed = state["seed"]
        with patch.object(games, "_now", return_value=start):
            games._crossing_action(state, {"type": "sync"})
        with patch.object(games, "_now", return_value=start + timedelta(milliseconds=500)):
            games._crossing_action(state, {"type": "sync"})
            self.assertEqual(games._crossing_elapsed_ms(state), 4250)
        self.assertEqual(state["seed"], seed)

    def test_learning_rotation_starts_a_new_cycle_without_internal_duplicates(self):
        from hpoint.game_content import SAFETY_SCENARIOS
        batches = [games._select_learning_scenarios(1, "safety") for _ in range(4)]
        self.assertEqual(len({item["id"] for batch in batches[:3] for item in batch}), 18)
        self.assertEqual(len({item["id"] for batch in batches for item in batch}), len(SAFETY_SCENARIOS))
        self.assertTrue(all(len({item["id"] for item in batch}) == 6 for batch in batches))
        next_batch = games._select_learning_scenarios(1, "safety")
        self.assertFalse({item["id"] for item in batches[-1]} & {item["id"] for item in next_batch})

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

    def test_bot_keeps_core_actions_discoverable_without_becoming_a_second_site(self):
        from hpoint.config import (
            BTN_FIND_CANDIDATES, BTN_GAMES, BTN_HISTORY, BTN_NAVIGATOR,
            BTN_NEED_HELP, BTN_PROFILE, BTN_SETTINGS, BTN_WANT_HELP, BTN_WEBSITE,
        )
        from hpoint.handlers import BOT_GUIDE, BOT_START_OVERVIEW, onboarding_text
        from hpoint.keyboards import main_menu_kb

        labels = [button.text for row in main_menu_kb().keyboard for button in row]
        self.assertTrue({
            BTN_NEED_HELP, BTN_WANT_HELP, BTN_FIND_CANDIDATES, BTN_PROFILE,
            BTN_HISTORY, BTN_SETTINGS, BTN_GAMES, BTN_WEBSITE, BTN_NAVIGATOR,
        }.issubset(labels))
        self.assertLessEqual(len(labels), 11)
        self.assertIn("Бот и сайт используют общие профиль", BOT_GUIDE)
        self.assertIn("Сайт остаётся основным местом", BOT_GUIDE)
        self.assertIn("Нужна помощь", BOT_START_OVERVIEW)
        self.assertIn("Подобрать кандидатов", BOT_START_OVERVIEW)
        self.assertIn("Мои кандидаты", BOT_START_OVERVIEW)
        self.assertIn("H-Point+", BOT_START_OVERVIEW)
        self.assertIn("Как пользоваться", BOT_START_OVERVIEW)
        self.assertIn("Как вас зовут?", onboarding_text())

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
