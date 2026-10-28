"""The shared help taxonomy must work beyond its request-form labels."""
import json
import sqlite3
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from hpoint import billing, config, database, services, web


class CategorySuggestions(unittest.TestCase):
    def test_original_category_keys_and_useful_legacy_suggestions_are_retained(self):
        self.assertTrue({"carry", "shopping", "snow", "tools", "transport", "tech", "study", "other"}
                        <= set(config.CATEGORIES))
        for text, expected in [
            ("Помочь с компьютером", "tech"),
            ("Купить продукты в магазине", "shopping"),
            ("Перенести коробки при переезде", "carry"),
            ("Расчистить снег", "snow"),
            ("Одолжить дрель", "tools"),
            ("Подвезти на машине", "transport"),
            ("Помочь с математикой", "study"),
        ]:
            with self.subTest(text=text):
                self.assertEqual(services.infer_category(text), expected)

    def test_new_everyday_tasks_receive_a_specific_direction(self):
        for text, expected in [
            ("Уборка квартиры, помыть окна", "cleaning"),
            ("Повесить полку", "repairs"),
            ("Нужен ремонт смесителя", "plumbing"),
            ("Заменить розетку", "electric"),
            ("Собрать шкаф", "furniture"),
            ("Полить цветы и пересадить растения", "garden"),
            ("Забрать посылку", "delivery"),
            ("Выгулять собаку", "pets"),
            ("Помочь пожилому человеку", "elderly"),
            ("Присмотреть за ребёнком", "children"),
            ("Сопроводить в поездке", "accompany"),
            ("Помочь с английским языком", "languages"),
            ("Оформить резюме", "documents"),
            ("Сделать дизайн афиши", "design"),
            ("Партнёр для пробежки", "sport"),
            ("Приготовить ужин", "cooking"),
            ("Подшить брюки", "sewing"),
            ("Провести фотосъёмку", "photo"),
            ("Встретить гостей на мероприятии", "events"),
            ("Волонтёрская помощь приюту", "volunteering"),
        ]:
            with self.subTest(text=text):
                self.assertEqual(services.infer_category(text), expected)

    def test_specific_phrases_win_over_generic_legacy_nouns(self):
        for text, expected in [
            ("Собрать мебель и шкаф", "furniture"),
            ("Передать документы", "delivery"),
            ("Уборка территории во дворе", "snow"),
            ("Ремонт розетки", "electric"),
            ("Ремонт компьютера", "tech"),
        ]:
            with self.subTest(text=text):
                self.assertEqual(services.infer_category(text), expected)

    def test_keyword_matching_does_not_match_unrelated_substrings(self):
        for text, expected in [
            ("Ключевые слова для заявления", "documents"),
            ("Автоматический перевод текста", "languages"),
            ("Котировки", "other"),
            ("Есть необычная задача", "other"),
            ("", "other"),
        ]:
            with self.subTest(text=text):
                self.assertEqual(services.infer_category(text), expected)

    def test_catalog_is_json_safe_grouped_and_has_no_duplicate_or_missing_keys(self):
        catalog = json.loads(json.dumps(config.CATEGORY_CATALOG, ensure_ascii=False))
        self.assertGreaterEqual(len(catalog), 24)
        self.assertEqual(len(catalog), len({row["key"] for row in catalog}))
        self.assertEqual({row["key"] for row in catalog}, set(config.CATEGORIES))
        groups = {row["key"] for row in config.CATEGORY_GROUPS}
        for item in catalog:
            self.assertIn(item["group"], groups)
            self.assertTrue(item["label"] and item["icon"] and item["hint"])
            self.assertEqual(item["title"], config.CATEGORIES[item["key"]])
        self.assertEqual(catalog[-1]["key"], "other")


class CategoryMatching(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.patches = [patch.object(module, "db", self.connection) for module in (database, services)]
        for item in self.patches:
            item.start()
        database.init_db()
        for user_id in (1, 2, 3):
            database.create_user(user_id, "Synthetic category " + str(user_id), None)

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.connection.close()

    def create(self, what, category=None):
        payload = {"what": what, "place": "Synthetic", "time_needed": "Today",
                   "urgency": "Normal", "details": "No real people or location"}
        if category is not None:
            payload["category"] = category
        return services.create_request(1, payload)

    def test_new_preferences_are_saved_and_matching_respects_them_both_ways(self):
        services.save_helper_preferences(2, ["pets", "garden"], ready=True)
        services.save_helper_preferences(3, ["plumbing"], ready=True)
        self.assertEqual(services.get_helper_categories(2), ["pets", "garden"])
        pet = self.create("Выгулять собаку")
        garden = self.create("Полить растения", "garden")
        plumbing = self.create("Заменить смеситель", "plumbing")
        self.assertEqual([item["user_id"] for item in services.smart_match(pet)], [2])
        self.assertEqual([item["user_id"] for item in services.smart_match(plumbing)], [3])
        self.assertEqual({item["request"]["id"] for item in services.smart_requests_for_helper(2)}, {pet, garden})
        self.assertEqual({item["request"]["id"] for item in services.smart_requests_for_helper(3)}, {plumbing})

    def test_explicit_category_is_never_overridden_and_other_history_stays_other(self):
        old = self.create("Необычная задача", "other")
        explicit = self.create("Собрать шкаф", "carry")
        inferred = self.create("Собрать шкаф")
        self.assertEqual(database.get_request(old)["category"], "other")
        self.assertEqual(database.get_request(explicit)["category"], "carry")
        self.assertEqual(database.get_request(inferred)["category"], "furniture")

    def test_each_new_direction_is_accepted_in_helper_settings_and_request_storage(self):
        old = {"carry", "shopping", "snow", "tools", "transport", "tech", "study", "other"}
        for category in set(config.CATEGORIES) - old:
            with self.subTest(category=category):
                preferences = services.save_helper_preferences(2, [category], ready=False)
                self.assertEqual(preferences["helper_categories"], [category])
                request_id = self.create("Synthetic selected direction", category)
                self.assertEqual(database.get_request(request_id)["category"], category)


class CategoryHTTP(unittest.TestCase):
    """Real API requests ensure the expanded catalogue works for web users."""

    def setUp(self):
        self.connection = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.patches = [patch.object(module, "db", self.connection)
                        for module in (database, services, billing, web)]
        self.patches.append(patch.object(web, "notify_telegram_user", return_value=False))
        for item in self.patches:
            item.start()
        database.init_db()
        self.tokens = {}
        for user_id in (1, 2, 3):
            database.create_user(user_id, "Synthetic HTTP " + str(user_id),
                                 email=f"category{user_id}@example.test", password_hash="synthetic-unused")
            self.connection.execute("UPDATE users SET email_verified=1 WHERE user_id=?", (user_id,))
            self.tokens[user_id] = web.new_sess(user_id)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=3)
        self.server.server_close()
        for item in reversed(self.patches):
            item.stop()
        self.connection.close()

    def request(self, user_id, path, body=None):
        headers = {"Content-Type": "application/json", "Origin": web.WEB_PUBLIC_URL}
        if user_id is not None:
            headers["Cookie"] = "hpoint_session=" + self.tokens[user_id]
        request = urllib.request.Request(self.base + path, headers=headers,
                                         data=json.dumps(body).encode("utf-8") if body is not None else None)
        with urllib.request.urlopen(request, timeout=3) as response:
            return json.load(response)

    def payload(self, category):
        return {"what": "Synthetic help task", "place": "Private synthetic address",
                "time_needed": "Today", "urgency": "Normal", "details": "Private synthetic details",
                "category": category}

    def test_create_search_and_feed_preserve_new_direction_without_disclosing_private_fields(self):
        pet = self.request(1, "/api/requests", self.payload("pets"))["request_id"]
        self.request(1, "/api/requests", self.payload("garden"))
        found = self.request(2, "/api/search?category=pets")["requests"]
        self.assertEqual([row["id"] for row in found], [pet])
        self.assertEqual(found[0]["category"], "pets")
        self.assertEqual(found[0]["category_name"], config.CATEGORIES["pets"])
        self.assertNotIn("details", found[0])
        self.assertNotEqual(found[0].get("place"), self.payload("pets")["place"])
        self.assertIsNone(found[0].get("lat"))
        self.assertIsNone(found[0].get("lon"))
        mine = self.request(1, "/api/requests/mine")["requests"]
        self.assertEqual({row["category"] for row in mine}, {"pets", "garden"})

    def test_preferences_round_trip_new_directions_and_invalid_choice_does_not_partially_save(self):
        selected = ["pets", "garden", "electric", "languages", "volunteering"]
        result = self.request(2, "/api/helper/preferences",
                              {"categories": selected, "ready": True, "availability": "Synthetic evenings"})
        self.assertEqual(result["user"]["helper_categories"], selected)
        self.assertTrue(result["user"]["helper_ready"])
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.request(2, "/api/helper/preferences", {"categories": ["not-a-category"], "ready": False})
        with raised.exception as response:
            self.assertEqual(response.code, 400)
        user = self.request(2, "/api/me")["user"]
        self.assertEqual(user["helper_categories"], selected)
        self.assertTrue(user["helper_ready"])

    def test_blank_and_unknown_explicit_categories_cannot_create_a_request(self):
        for category in ("", "not-a-category", "<script>bad</script>"):
            with self.subTest(category=category):
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    self.request(1, "/api/requests", self.payload(category))
                with raised.exception as response:
                    self.assertEqual(response.code, 400)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM requests").fetchone()[0], 0)

    def test_new_categories_do_not_bypass_registration_or_email_verification(self):
        for user_id in (None, 3):
            if user_id == 3:
                self.connection.execute("UPDATE users SET email_verified=0 WHERE user_id=3")
            with self.subTest(user_id=user_id):
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    self.request(user_id, "/api/requests", self.payload("electric"))
                with raised.exception as response:
                    self.assertIn(response.code, (401, 403))
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM requests").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
