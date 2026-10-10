"""Website RUB checkout via Robokassa; no in-Telegram digital sales."""
import json, uuid, hashlib, hmac
from urllib.parse import urlencode
from .config import *
from .database import db, get_invoice
from .services import grant_entitlement

def create_pending_invoice(user_id,item_type,metadata=None):
    item=MONETIZATION_ITEMS.get(item_type)
    if not item: raise ValueError("unknown billing item")
    payload=f"hpoint:v2:{uuid.uuid4().hex}"
    cur=db.execute("""INSERT INTO billing_invoices(user_id,item_type,amount_rub,currency,payload,metadata)
                      VALUES(?,?,?,?,?,?)""",(user_id,item_type,item["rub"],PAYMENT_CURRENCY,payload,json.dumps(metadata or {},ensure_ascii=False)))
    return cur.lastrowid,payload,item["rub"]

def _signature(value, password):
    try: digest=getattr(hashlib, ROBOKASSA_HASH_ALGORITHM.lower())
    except AttributeError: raise RuntimeError("Unsupported ROBOKASSA_HASH_ALGORITHM")
    return digest(f"{value}:{password}".encode()).hexdigest().upper()

def create_payment(invoice_id):
    inv=get_invoice(invoice_id)
    if not inv: raise ValueError("invoice not found")
    if inv["status"]!="pending": raise ValueError("invoice already processed")
    if not ROBOKASSA_MERCHANT_LOGIN or not ROBOKASSA_PASSWORD_1 or not ROBOKASSA_PASSWORD_2:
        raise RuntimeError("Robokassa is not configured: set ROBOKASSA_MERCHANT_LOGIN, ROBOKASSA_PASSWORD_1 and ROBOKASSA_PASSWORD_2")
    amount=f'{inv["amount_rub"]:.2f}'
    description=MONETIZATION_ITEMS[inv["item_type"]]["title"][:100]
    params={"MerchantLogin":ROBOKASSA_MERCHANT_LOGIN,"OutSum":amount,"InvId":str(invoice_id),
            "Description":description,"Culture":"ru","Encoding":"utf-8",
            "SignatureValue":_signature(f"{amount}:{invoice_id}",ROBOKASSA_PASSWORD_1),
            "SuccessURL":PAYMENT_SUCCESS_URL,"FailURL":PAYMENT_FAIL_URL}
    db.execute("UPDATE billing_invoices SET provider_payment_id=? WHERE id=?",(str(invoice_id),invoice_id))
    return "https://auth.robokassa.ru/Merchant/Index.aspx?"+urlencode(params),str(invoice_id)

def verify_robokassa_result(fields):
    """Validate ResultURL fields and return the matching invoice, if valid."""
    if not ROBOKASSA_PASSWORD_2: return None
    try:
        invoice_id=int(fields.get("InvId", "")); amount=f'{float(fields.get("OutSum", "")):.2f}'
    except (TypeError, ValueError): return None
    signature=fields.get("SignatureValue", "").upper()
    expected=_signature(f"{amount}:{invoice_id}",ROBOKASSA_PASSWORD_2)
    if not hmac.compare_digest(signature,expected): return None
    inv=get_invoice(invoice_id)
    if not inv or inv["currency"]!="RUB" or f'{inv["amount_rub"]:.2f}'!=amount: return None
    return inv

def fulfill_invoice(invoice_id,payment_id=None):
    inv=get_invoice(invoice_id)
    if not inv: return False,"invoice_not_found"
    if inv["status"]=="paid": return True,"already_paid"
    if payment_id and inv["provider_payment_id"] and payment_id != inv["provider_payment_id"]:
        return False,"payment_mismatch"
    meta=json.loads(inv["metadata"] or "{}")
    db.execute("BEGIN IMMEDIATE")
    try:
        inv=get_invoice(invoice_id)
        if inv["status"]=="paid":
            db.execute("ROLLBACK"); return True,"already_paid"
        db.execute("UPDATE billing_invoices SET status='paid',paid_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'",(invoice_id,))
        if db.execute("SELECT changes() n").fetchone()["n"]!=1:
            db.execute("ROLLBACK"); return False,"already_processed"
        db.execute("INSERT OR IGNORE INTO billing_events(invoice_id,event_type,provider_event_id,payload) VALUES(?,?,?,?)",
                   (invoice_id,"successful_payment",payment_id or inv["provider_payment_id"],json.dumps(meta,ensure_ascii=False)))
        grant_entitlement(inv["user_id"],inv["item_type"],request_id=meta.get("request_id"),ad_text=meta.get("ad_text"))
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK"); raise
    return True,inv["item_type"]
