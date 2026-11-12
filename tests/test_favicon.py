"""Real raster favicons for browser tabs and search-result compatibility."""
from http.server import ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
import threading
import unittest
import urllib.request

from PIL import Image


ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets"


class FaviconAssets(unittest.TestCase):
    def test_square_png_variants_have_real_brand_pixels(self):
        for size in (48, 192):
            with Image.open(ASSET_ROOT / f"favicon-{size}.png") as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.size, (size, size))
                self.assertEqual(image.mode, "RGBA")
                colors = image.convert("RGB").getcolors(size * size)
                self.assertGreater(len(colors), 100)
                self.assertEqual(image.getpixel((0, 0))[3], 0)

    def test_ico_contains_small_and_high_density_tab_sizes(self):
        with Image.open(ASSET_ROOT / "favicon.ico") as image:
            self.assertEqual(image.format, "ICO")
            self.assertTrue({(16, 16), (32, 32), (48, 48), (192, 192), (256, 256)} <= image.ico.sizes())
            for size in ((16, 16), (32, 32), (48, 48)):
                self.assertEqual(image.ico.getimage(size).size, size)


class FaviconRoutes(unittest.TestCase):
    def setUp(self):
        from hpoint import web
        self.web = web
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=3)
        self.server.server_close()

    def test_head_announces_public_png_and_ico_choices(self):
        page = self.web.PAGE
        self.assertIn('href="/favicon.ico"', page)
        self.assertIn('href="/assets/favicon-192.png"', page)
        self.assertIn('sizes="192x192"', page)

    def test_get_and_head_serve_favicons_without_an_account(self):
        for path, expected in (("/favicon.ico", "ICO"), ("/assets/favicon.ico", "ICO"),
                               ("/assets/favicon-48.png", "PNG"), ("/assets/favicon-192.png", "PNG")):
            request = urllib.request.Request(self.base + path, headers={"User-Agent": "Googlebot-Image/1.0"})
            with urllib.request.urlopen(request, timeout=3) as response:
                self.assertEqual(response.status, 200)
                payload = response.read()
                length = int(response.headers["Content-Length"])
                self.assertEqual(length, len(payload))
                self.assertTrue(response.headers["Content-Type"].startswith("image/"))
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                self.assertNotIn("Set-Cookie", response.headers)
                with Image.open(BytesIO(payload)) as image:
                    self.assertEqual(image.format, expected)
            head = urllib.request.Request(self.base + path, method="HEAD")
            with urllib.request.urlopen(head, timeout=3) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(int(response.headers["Content-Length"]), length)
                self.assertEqual(response.read(), b"")
