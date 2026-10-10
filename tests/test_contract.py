import ast
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_python_parses():
 for p in (ROOT/"hpoint").glob("*.py"):ast.parse(p.read_text(encoding="utf-8"))
def test_external_rub_billing_contract():
 cfg=(ROOT/"hpoint/config.py").read_text(encoding="utf-8");bill=(ROOT/"hpoint/billing.py").read_text(encoding="utf-8");h=(ROOT/"hpoint/handlers.py").read_text(encoding="utf-8")
 assert 'PAYMENT_CURRENCY = "RUB"' in cfg
 assert "ROBOKASSA_MERCHANT_LOGIN" in bill
 assert "auth.robokassa.ru" in bill
 assert "YOOKASSA" not in bill
 assert "Stars" not in h or "Stars не используются" in h
 assert "/link" in h

def test_public_web_contract():
 cfg=(ROOT/"hpoint/config.py").read_text(encoding="utf-8");web=(ROOT/"hpoint/web.py").read_text(encoding="utf-8")
 assert "SESSION_COOKIE_SECURE" in cfg
 assert 'secure = "; Secure" if SESSION_COOKIE_SECURE else ""' in web
 assert '"bot_configured"' not in web
