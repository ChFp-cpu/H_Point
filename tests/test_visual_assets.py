"""The visual redesign must use real licensed local assets and public fields."""
from copy import deepcopy
import hashlib
from html.parser import HTMLParser
import unittest

from PIL import Image

from hpoint import organization_page, visuals


class Tags(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def public_profile(**changes):
    profile = {
        "title": "Тестовая студия",
        "kind": "trainer",
        "kind_title": "Тренер",
        "description": "Индивидуальные тренировки по опубликованным условиям.",
        "contact": "Публичный контакт организации",
        "address": "Публичный район работы",
        "url": "/organizations/synthetic-studio",
        "services": [{"title": "Разбор техники упражнений", "description": "По договорённости.",
                      "price_rub": 1200, "duration_minutes": 45}],
        "currency": "TEST_RUB",
    }
    profile.update(changes)
    return profile


class LocalPhotoAssets(unittest.TestCase):
    def test_every_photo_has_a_unique_licensed_source_and_responsive_variants(self):
        manifest = visuals.MANIFEST
        self.assertEqual(manifest["count"], 16)
        self.assertEqual(len(manifest["photos"]), 16)
        self.assertEqual(manifest["license"]["url"], "https://www.pexels.com/license/")
        self.assertEqual(len({item["pexels_id"] for item in manifest["photos"].values()}), 16)
        for key, photo in manifest["photos"].items():
            with self.subTest(key=key):
                self.assertTrue(photo["source_url"].startswith("https://www.pexels.com/photo/"))
                self.assertTrue(photo["download_url"].startswith("https://images.pexels.com/"))
                self.assertEqual(photo["license_url"], manifest["license"]["url"])
                self.assertTrue(photo["photographer"])
                self.assertTrue(photo["alt"])
                self.assertTrue(photo["not_a_user_photo"])
                self.assertEqual(photo["purpose"], "thematic_illustration")
                self.assertEqual([item["width"] for item in photo["sources"]],
                                 [480, 960, 1600] if key in {"help", "home"} else [480, 960])

    def test_optimized_bytes_dimensions_hashes_and_metadata_match_manifest(self):
        total = 0
        variants = []
        for key, photo in visuals.MANIFEST["photos"].items():
            for item in photo["sources"]:
                with self.subTest(key=key, width=item["width"]):
                    self.assertRegex(item["path"], r"^photos/[a-z]+-(480|960|1600)\.webp$")
                    path = visuals.ASSET_ROOT / item["path"]
                    self.assertEqual(path.resolve().parent, (visuals.ASSET_ROOT / "photos").resolve())
                    body = path.read_bytes()
                    self.assertEqual(len(body), item["bytes"])
                    self.assertEqual(hashlib.sha256(body).hexdigest(), item["sha256"])
                    with Image.open(path) as image:
                        self.assertEqual(image.format, "WEBP")
                        self.assertEqual(image.size, (item["width"], item["height"]))
                        self.assertFalse(image.getexif())
                    variants.append(path.name)
                    total += len(body)
        self.assertEqual(len(variants), 34)
        self.assertEqual(len(set(variants)), 34)
        self.assertEqual(total, visuals.MANIFEST["total_bytes"])
        self.assertLess(total, 1_700_000)
        self.assertEqual(set(visuals.assets()), set(variants))

    def test_photo_markup_is_local_responsive_and_escapes_user_facing_overrides(self):
        html = visuals.photo("trainer", class_name='sample" onclick="bad()', alt='Photo <script>bad()</script> "x"')
        image = next(attrs for tag, attrs in Tags(html).tags if tag == "img")
        self.assertEqual(image["alt"], 'Photo <script>bad()</script> "x"')
        self.assertEqual(image["loading"], "lazy")
        self.assertEqual((image["width"], image["height"]), ("960", "640"))
        self.assertTrue(image["src"].startswith("/assets/"))
        self.assertIn("trainer-480.webp 480w", image["srcset"])
        self.assertIn("trainer-960.webp 960w", image["srcset"])
        self.assertIn("max-width:700px", image["sizes"])
        self.assertNotIn("<script>", html)
        self.assertFalse(any("onclick" in attrs for _, attrs in Tags(html).tags))


class PublicOrganizationVisuals(unittest.TestCase):
    def test_all_real_professions_use_their_direction_photo_with_honest_caption(self):
        for kind in ("trainer", "foreman", "tutor", "beauty", "repair", "events", "studio", "organization", "other"):
            with self.subTest(kind=kind):
                html = organization_page.document(public_profile(kind=kind), "https://example.test")
                images = [attrs for tag, attrs in Tags(html).tags if tag == "img"]
                self.assertEqual(len(images), 2)  # Actual site logo and one direction illustration.
                image = next(attrs for attrs in images if "hpPhotoImage" in attrs.get("class", ""))
                self.assertIn(visuals.kind_photo(kind) + "-480.webp", image["src"])
                self.assertEqual(image["loading"], "eager")
                self.assertTrue(image["alt"])
                self.assertIn("Фото направления", html)
                self.assertIn("не портфолио организации", html)
                self.assertIn('class="orgMark" aria-hidden="true"', html)
                self.assertNotIn("verified", html)
                self.assertNotIn("<form", html)

    def test_real_services_contact_and_test_prices_are_preserved_without_invented_checkout(self):
        profile = public_profile()
        before = deepcopy(profile)
        html = organization_page.document(profile, "https://example.test")
        self.assertIn("Разбор техники упражнений", html)
        self.assertIn("1 200 тест. ₽", html)
        self.assertIn("45 мин.", html)
        self.assertIn("Публичный контакт организации", html)
        self.assertIn("Публичный район работы", html)
        self.assertIn('href="#orgContacts"', html)
        self.assertIn('href="https://example.test/organizations/synthetic-studio"', html)
        self.assertIn("оплата через эту страницу не проводится", html)
        self.assertEqual(profile, before)
        self.assertNotIn("/api/payments", html)

    def test_empty_page_is_useful_without_fake_people_activity_services_or_contacts(self):
        html = organization_page.document(public_profile(services=[], contact="", address=""), "https://example.test")
        self.assertIn("Пока нет опубликованных услуг", html)
        self.assertNotIn('id="orgContacts"', html)
        self.assertNotIn('href="#orgContacts"', html)
        self.assertNotIn('class="orgService"', html)
        self.assertNotIn("1 200", html)
        self.assertIn('href="/#/profile"', html)

    def test_only_public_allowlist_fields_are_rendered_and_html_is_escaped(self):
        profile = public_profile(
            title='Public <script>alert("title")</script>',
            description='Text <script>alert("description")</script>',
            contact='Contact <img src=x onerror="alert(1)">',
            address='Area <iframe src="x"></iframe>',
            clients=[{"name": "PRIVATE CRM CLIENT"}],
            notes="PRIVATE HEALTH NOTE",
            staff_email="private@example.test",
            services=[{"title": 'Service <script>alert("service")</script>',
                       "description": "<b>Public description</b>", "price_rub": 700, "duration_minutes": 60,
                       "private_notes": "PRIVATE SERVICE NOTE"}],
        )
        html = organization_page.document(profile, "https://example.test")
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>alert", html)
        self.assertNotIn("<iframe", html)
        self.assertFalse(any("onerror" in attrs for _, attrs in Tags(html).tags))
        for private in ("PRIVATE CRM CLIENT", "PRIVATE HEALTH NOTE", "private@example.test", "PRIVATE SERVICE NOTE"):
            self.assertNotIn(private, html)

    def test_shared_font_native_themes_reduced_motion_and_local_editorial_styles_are_retained(self):
        html = organization_page.document(public_profile(), "https://example.test")
        self.assertIn("Manrope", html)
        self.assertIn("prefers-color-scheme:dark", html)
        self.assertIn("prefers-reduced-motion:reduce", html)
        self.assertIn("@media(max-width:640px)", html)
        self.assertIn('/assets/hpoint-editorial.css?v=20261030-visual2', html)
        self.assertIn('name="viewport"', html)
        self.assertIn('href="/#/activities"', html)
        self.assertNotIn("fonts.googleapis.com", html)


if __name__ == "__main__":
    unittest.main()
