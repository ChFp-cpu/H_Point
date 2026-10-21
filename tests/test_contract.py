import ast
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def test_python_parses(self):
        for path in (ROOT / "hpoint").glob("*.py"):
            ast.parse(path.read_text(encoding="utf-8"))

    def test_external_rub_billing_contract(self):
        config = (ROOT / "hpoint/config.py").read_text(encoding="utf-8")
        billing = (ROOT / "hpoint/billing.py").read_text(encoding="utf-8")
        handlers = (ROOT / "hpoint/handlers.py").read_text(encoding="utf-8")
        self.assertIn('PAYMENT_CURRENCY = "RUB"', config)
        self.assertIn("ROBOKASSA_MERCHANT_LOGIN", billing)
        self.assertIn("auth.robokassa.ru", billing)
        self.assertNotIn("YOOKASSA", billing)
        self.assertNotIn("Stars", handlers)
        self.assertIn("/link", handlers)

    def test_public_web_contract(self):
        config = (ROOT / "hpoint/config.py").read_text(encoding="utf-8")
        web = (ROOT / "hpoint/web.py").read_text(encoding="utf-8")
        caddy = (ROOT / "Caddyfile").read_text(encoding="utf-8")
        self.assertIn("SESSION_COOKIE_SECURE", config)
        self.assertIn('secure = "; Secure" if SESSION_COOKIE_SECURE else ""', web)
        self.assertIn("session_token_hash", web)
        self.assertNotIn("unsafe-eval", web)
        self.assertIn("header_up X-Forwarded-For {remote_host}", caddy)
        self.assertNotIn('"bot_configured"', web)

    def test_vulnerable_runtime_dependencies_are_pinned(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("aiohttp==3.14.4", requirements)
        self.assertIn("certifi==2026.10.19", requirements)
        self.assertIn('"pip>=26.2"', dockerfile)
