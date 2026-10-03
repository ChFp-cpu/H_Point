import ast
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_python_parses():
 for p in (ROOT/"hpoint").glob("*.py"):ast.parse(p.read_text(encoding="utf-8"))
def test_no_stars_contract():
 cfg=(ROOT/"hpoint/config.py").read_text(encoding="utf-8");bill=(ROOT/"hpoint/billing.py").read_text(encoding="utf-8");h=(ROOT/"hpoint/handlers.py").read_text(encoding="utf-8")
 assert 'PAYMENT_CURRENCY = "RUB"' in cfg
 assert "YOOKASSA_SHOP_ID" in bill and "api.yookassa.ru" in bill
 assert "Stars" not in h or "Stars не используются" in h
 assert "/link" in h
