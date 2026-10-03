"""RUB acquiring via YooKassa. Telegram Stars are not used."""
import json, uuid, base64
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
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

def _auth():
    if not YOOKASSA_SHOP_ID or not YOOKASSA_SECRET_KEY:
        raise RuntimeError("YooKassa is not configured: set YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY")
    token=base64.b64encode(f"{YOOKASSA_SHOP_ID}:{YOOKASSA_SECRET_KEY}".encode()).decode()
    return "Basic "+token

def create_payment(invoice_id):
    inv=get_invoice(invoice_id)
    if not inv: raise ValueError("invoice not found")
    if inv["status"]!="pending": raise ValueError("invoice already processed")
    meta=json.loads(inv["metadata"] or "{}")
    body={"amount":{"value":f'{inv["amount_rub"]:.2f}',"currency":"RUB"},"capture":True,
          "confirmation":{"type":"redirect","return_url":PAYMENT_RETURN_URL},
          "description":MONETIZATION_ITEMS[inv["item_type"]]["title"][:128],
          "metadata":{"hpoint_invoice_id":str(invoice_id),"item_type":inv["item_type"],**{k:str(v) for k,v in meta.items()}}}
    req=Request("https://api.yookassa.ru/v3/payments",data=json.dumps(body).encode(),
                headers={"Authorization":_auth(),"Idempotence-Key":str(uuid.uuid4()),"Content-Type":"application/json"},method="POST")
    try:
        with urlopen(req,timeout=20) as r: data=json.loads(r.read())
    except (HTTPError,URLError) as e:
        raise RuntimeError(f"YooKassa request failed: {e}")
    payment_id=data.get("id"); url=(data.get("confirmation") or {}).get("confirmation_url")
    if not payment_id or not url: raise RuntimeError("YooKassa did not return payment URL")
    db.execute("UPDATE billing_invoices SET provider_payment_id=? WHERE id=?",(payment_id,invoice_id))
    return url,payment_id

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

def check_payment(payment_id):
    if not payment_id: return None
    req=Request(f"https://api.yookassa.ru/v3/payments/{payment_id}",headers={"Authorization":_auth()},method="GET")
    with urlopen(req,timeout=20) as r: return json.loads(r.read())
