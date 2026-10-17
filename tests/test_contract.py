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
        self.assertIn("SESSION_COOKIE_SECURE", config)
        self.assertIn('secure = "; Secure" if SESSION_COOKIE_SECURE else ""', web)
        self.assertNotIn('"bot_configured"', web)
