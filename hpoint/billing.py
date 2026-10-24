"""Website RUB checkout via Robokassa; no in-Telegram digital sales."""
import json, uuid, hashlib, hmac
from urllib.parse import urlencode
from .config import *
from .database import db, get_invoice, get_request, get_user, insert_id, wallet_add_entry
from .services import grant_entitlement

def _validate_active_purchase(user_id, item_type, metadata, lock=False):
    if item_type not in MONETIZATION_ITEMS:
        raise ValueError("item is no longer sold")
    if item_type == "boost":
        request_id = metadata.get("request_id")
        if not isinstance(request_id, int) or isinstance(request_id, bool):
            raise ValueError("request_id required")
        suffix = " FOR UPDATE" if lock and getattr(db, "is_postgres", False) else ""
        request = db.execute("SELECT * FROM requests WHERE id=?" + suffix, (request_id,)).fetchone()
        if not request or request["requester_id"] != user_id or request["status"] != "open":
            raise ValueError("request is unavailable")
        if int(request["priority_boost"] or 0) >= 100:
            raise ValueError("request already promoted")
        if int(request["reward_rub"] or 0) and request["reward_payment_status"] != "paid":
            raise ValueError("request reward unpaid")

def _lock_buyer(user_id):
    if getattr(db, "is_postgres", False):
        db.execute("SELECT user_id FROM users WHERE user_id=? FOR UPDATE", (user_id,))

def create_pending_invoice(user_id,item_type,metadata=None):
    _validate_active_purchase(user_id, item_type, metadata or {})
    item=MONETIZATION_ITEMS.get(item_type)
    if not item: raise ValueError("unknown billing item")
    payload=f"hpoint:v2:{uuid.uuid4().hex}"
    invoice_id=insert_id("""INSERT INTO billing_invoices(user_id,item_type,amount_rub,currency,payload,metadata)
                          VALUES(?,?,?,?,?,?)""",(user_id,item_type,item["rub"],PAYMENT_CURRENCY,payload,json.dumps(metadata or {},ensure_ascii=False)))
    return invoice_id,payload,item["rub"]

def create_request_reward_invoice(user_id, request_id):
    request=get_request(request_id)
    if not request or request["requester_id"]!=user_id or request["status"]!="open": raise ValueError("request unavailable")
    amount=int(request["reward_rub"] or 0)
    if amount<1: raise ValueError("reward is zero")
    existing=db.execute("SELECT * FROM billing_invoices WHERE item_type='request_reward' AND user_id=? AND metadata LIKE ? AND status='pending' ORDER BY id DESC LIMIT 1",(user_id,f'%\"request_id\": {request_id}%')).fetchone()
    if existing:return existing["id"],existing["payload"],amount
    payload=f"hpoint:reward:{uuid.uuid4().hex}"
    invoice_id=insert_id("INSERT INTO billing_invoices(user_id,item_type,amount_rub,currency,payload,metadata) VALUES(?,?,?,?,?,?)",(user_id,'request_reward',amount,PAYMENT_CURRENCY,payload,json.dumps({'request_id':request_id},ensure_ascii=False)))
    return invoice_id,payload,amount

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
    description=(MONETIZATION_ITEMS.get(inv["item_type"]) or LEGACY_MONETIZATION_ITEMS.get(inv["item_type"]) or {"title":"Вознаграждение за помощь"})["title"][:100]
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
        changed = db.execute("UPDATE billing_invoices SET status='paid',paid_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'",(invoice_id,)).rowcount
        if changed != 1:
            db.execute("ROLLBACK"); return False,"already_processed"
        db.execute("INSERT OR IGNORE INTO billing_events(invoice_id,event_type,provider_event_id,payload) VALUES(?,?,?,?)",
                   (invoice_id,"successful_payment",payment_id or inv["provider_payment_id"],json.dumps(meta,ensure_ascii=False)))
        if inv["item_type"]=="request_reward":
            request_id = meta.get("request_id")
            request = get_request(request_id)
            if not request or request["requester_id"] != inv["user_id"]:
                db.execute("ROLLBACK"); return False,"request_unavailable"
            amount = int(inv["amount_rub"] or 0)
            db.execute("UPDATE requests SET reward_payment_status='paid' WHERE id=? AND requester_id=?",(request_id,inv["user_id"]))
            wallet_add_entry(inv["user_id"], amount, "payment", "Оплата вознаграждения за помощь", f"invoice:{invoice_id}:payment", request_id, invoice_id)
            wallet_add_entry(inv["user_id"], -amount, "reward_reserve", "Вознаграждение зарезервировано до завершения заявки", f"request:{request_id}:reserve", request_id, invoice_id)
        else:
            grant_entitlement(inv["user_id"],inv["item_type"],request_id=meta.get("request_id"),ad_text=meta.get("ad_text"))
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK"); raise
    return True,inv["item_type"]

def purchase_with_points(user_id, item_type, metadata=None, idempotency_key=None):
    """Atomically exchange earned H-Points for a real entitlement.

    A client retry uses the same idempotency key and returns the original
    invoice without charging the balance a second time.
    """
    item = MONETIZATION_ITEMS.get(item_type)
    if not item or "hp" not in item:
        raise ValueError("unknown billing item")
    metadata = dict(metadata or {})
    key = str(idempotency_key or "").strip()
    if not key or len(key) > 100:
        raise ValueError("invalid purchase key")
    payload = f"hpoint:hp:{key}"
    price = int(item["hp"])

    # Validate inputs before taking a balance lock.  The entitlement function
    # then applies the same mutation inside the transaction below.
    if item_type in ("boost", "more_responses"):
        request_id = metadata.get("request_id")
        if not isinstance(request_id, int):
            raise ValueError("request_id required")
        request = get_request(request_id)
        if not request or request["requester_id"] != user_id or request["status"] != "open":
            raise ValueError("request is unavailable")
    if item_type == "verification" and not get_user(user_id)["tg_user_id"]:
        raise ValueError("telegram link required")
    if item_type == "ad" and not str(metadata.get("ad_text", "")).strip():
        raise ValueError("ad_text required")

    db.execute("BEGIN IMMEDIATE")
    try:
        _lock_buyer(user_id)
        existing = db.execute("SELECT * FROM billing_invoices WHERE payload=?", (payload,)).fetchone()
        if existing:
            if existing["user_id"] != user_id or existing["currency"] != "HP":
                db.execute("ROLLBACK")
                raise ValueError("purchase key already used")
            db.execute("COMMIT")
            return existing["id"], False
        _validate_active_purchase(user_id, item_type, metadata, lock=True)
        changed = db.execute(
            "UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",
            (price, user_id, price),
        ).rowcount
        if changed != 1:
            db.execute("ROLLBACK")
            raise ValueError("insufficient_points")
        invoice_id = insert_id(
            """INSERT INTO billing_invoices(user_id,item_type,amount_rub,currency,payload,metadata,status,paid_at)
               VALUES(?,?,?,?,?,?, 'paid', CURRENT_TIMESTAMP)""",
            (user_id, item_type, price, "HP", payload, json.dumps(metadata, ensure_ascii=False)),
        )
        grant_entitlement(user_id, item_type, request_id=metadata.get("request_id"), ad_text=metadata.get("ad_text"))
        db.execute(
            "INSERT OR IGNORE INTO billing_events(invoice_id,event_type,provider_event_id,payload) VALUES(?,?,?,?)",
            (invoice_id, "points_purchase", payload, json.dumps(metadata, ensure_ascii=False)),
        )
        db.execute("COMMIT")
        return invoice_id, True
    except Exception:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        raise

def purchase_with_wallet(user_id, item_type, metadata=None, idempotency_key=None):
    """Pay for an H-Point+ entitlement from the user's RUB wallet.

    Wallet entries are an append-only ledger, so the available balance is
    checked and the debit is recorded in the same write transaction as the
    entitlement.  Retrying a request with the same key is safe.
    """
    item = MONETIZATION_ITEMS.get(item_type)
    if not item or "rub" not in item:
        raise ValueError("unknown billing item")
    metadata = dict(metadata or {})
    key = str(idempotency_key or "").strip()
    if not key or len(key) > 100:
        raise ValueError("invalid purchase key")
    payload = f"hpoint:wallet:{key}"
    price = int(item["rub"])

    if item_type in ("boost", "more_responses"):
        request_id = metadata.get("request_id")
        if not isinstance(request_id, int):
            raise ValueError("request_id required")
        request = get_request(request_id)
        if not request or request["requester_id"] != user_id or request["status"] != "open":
            raise ValueError("request is unavailable")
    if item_type == "verification" and not get_user(user_id)["tg_user_id"]:
        raise ValueError("telegram link required")
    if item_type == "ad" and not str(metadata.get("ad_text", "")).strip():
        raise ValueError("ad_text required")

    db.execute("BEGIN IMMEDIATE")
    try:
        _lock_buyer(user_id)
        existing = db.execute("SELECT * FROM billing_invoices WHERE payload=?", (payload,)).fetchone()
        if existing:
            if existing["user_id"] != user_id or existing["currency"] != "WALLET":
                db.execute("ROLLBACK")
                raise ValueError("purchase key already used")
            db.execute("COMMIT")
            return existing["id"], False
        _validate_active_purchase(user_id, item_type, metadata, lock=True)
        balance = db.execute(
            "SELECT COALESCE(SUM(amount_rub), 0) AS balance FROM wallet_transactions WHERE user_id=?",
            (user_id,),
        ).fetchone()["balance"]
        if int(balance or 0) < price:
            db.execute("ROLLBACK")
            raise ValueError("insufficient_wallet")
        invoice_id = insert_id(
            """INSERT INTO billing_invoices(user_id,item_type,amount_rub,currency,payload,metadata,status,paid_at)
               VALUES(?,?,?,?,?,?, 'paid', CURRENT_TIMESTAMP)""",
            (user_id, item_type, price, "WALLET", payload, json.dumps(metadata, ensure_ascii=False)),
        )
        wallet_add_entry(
            user_id, -price, "hpoint_purchase", f"Оплата H-Point+: {item['title']}",
            f"wallet-purchase:{key}", invoice_id=invoice_id,
        )
        grant_entitlement(user_id, item_type, request_id=metadata.get("request_id"), ad_text=metadata.get("ad_text"))
        db.execute(
            "INSERT OR IGNORE INTO billing_events(invoice_id,event_type,provider_event_id,payload) VALUES(?,?,?,?)",
            (invoice_id, "wallet_purchase", payload, json.dumps(metadata, ensure_ascii=False)),
        )
        db.execute("COMMIT")
        return invoice_id, True
    except Exception:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        raise
