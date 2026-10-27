"""Search metadata and crawler access for the public site only."""
from http.server import ThreadingHTTPServer
import threading
import unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from xml.etree import ElementTree
from unittest.mock import patch

from hpoint import seo


class SearchResources(unittest.TestCase):
    def test_canonical_strips_query_fragment_and_subpath(self):
        self.assertEqual(seo.canonical_url("https://example.test/?action=request#help"),"https://example.test/")
        for invalid in ("file:///tmp/test","https://person:secret@example.test/"):
            with self.assertRaises(ValueError):seo.canonical_url(invalid)
    def test_only_public_root_enters_sitemap_and_games_remains_crawlable(self):
        root=ElementTree.fromstring(seo.sitemap_xml("https://example.test"))
        self.assertEqual([x.text for x in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")],["https://example.test/"])
        robots=seo.robots_txt("https://example.test")
        self.assertIn("Disallow: /api/",robots)
        self.assertNotIn("Disallow: /games",robots)
        self.assertNotIn("Disallow: /assets",robots)
        self.assertIn("Sitemap: https://example.test/sitemap.xml",robots)
    def test_metadata_describes_current_email_product(self):
        head=seo.head_metadata("https://example.test")
        self.assertIn('rel="canonical" href="https://example.test/"',head)
        self.assertIn("email",head)
        self.assertNotIn("Games",head)
        gone=seo.removed_section_document("https://example.test")
        self.assertIn('name="robots" content="noindex,nofollow"',gone)
        self.assertNotIn("H-Point Games",gone)


class SearchHTTP(unittest.TestCase):
    def setUp(self):
        from hpoint import web
        self.web=web
        self.switch=patch.object(web,"GAMES_ENABLED",False);self.switch.start()
        self.server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f"http://127.0.0.1:{self.server.server_port}"
    def tearDown(self):
        self.server.shutdown();self.thread.join(timeout=3);self.server.server_close();self.switch.stop()
    def fetch(self,path,method="GET"):
        try:return urlopen(Request(self.base+path,method=method),timeout=3)
        except HTTPError as error:return error
    def test_robots_sitemap_and_icons_are_public_to_crawlers(self):
        for path in ("/robots.txt","/sitemap.xml","/favicon.ico","/assets/favicon-192.png"):
            with self.fetch(path) as response:
                self.assertEqual(response.status,200,path)
            with self.fetch(path,"HEAD") as response:self.assertEqual(response.status,200,path)
        with self.fetch("/robots.txt") as response:
            text=response.read().decode()
            self.assertNotIn("Disallow: /games",text)
            self.assertIn("Sitemap:",text)
        with self.fetch("/sitemap.xml") as response:
            self.assertNotIn(b"games",response.read())
    def test_removed_games_returns_gone_with_noindex_for_get_and_head(self):
        for path in ("/games","/games/","/games?game=crossing"):
            for method in ("GET","HEAD"):
                with self.fetch(path,method) as response:
                    self.assertEqual(response.status,410,(path,method))
                    self.assertIn("noindex",response.headers.get("X-Robots-Tag",""))
                    if method=="GET":self.assertNotIn(b"H-Point Games",response.read())
