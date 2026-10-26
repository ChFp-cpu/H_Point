"""Website RUB checkout via Robokassa; no in-Telegram digital sales."""
import json, uuid, hashlib, hmac
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from urllib.parse import urlencode
from .config import *
from .database import db, get_invoice, get_request, get_user, insert_id, wallet_add_entry
from .services import grant_entitlement
from .workflow import TEST_MONEY_ONLY

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
        db.execute("SELECT user_id FROM users WHERE user_id=? FOR NO KEY UPDATE", (user_id,))

def create_pending_invoice(user_id,item_type,metadata=None):
    _validate_active_purchase(user_id, item_type, metadata or {})
    item=MONETIZATION_ITEMS.get(item_type)
    if not item: raise ValueError("unknown billing item")
    payload=f"hpoint:v2:{uuid.uuid4().hex}"
    invoice_id=insert_id("""INSERT INTO billing_invoices(user_id,item_type,amount_rub,currency,payload,metadata)
                          VALUES(?,?,?,?,?,?)""",(user_id,item_type,item["rub"],PAYMENT_CURRENCY,payload,json.dumps(metadata or {},ensure_ascii=False)))
    return invoice_id,payload,item["rub"]

def create_request_reward_invoice(user_id, request_id):
    db.execute("BEGIN IMMEDIATE")
    try:
        lock=" FOR UPDATE" if getattr(db,"is_postgres",False) else ""
        request=db.execute("SELECT * FROM requests WHERE id=?"+lock,(request_id,)).fetchone()
        if not request or request["requester_id"]!=user_id or request["status"]!="open" or request["reward_payment_status"]!="none":raise ValueError("request unavailable")
        amount=int(request["reward_rub"] or 0)
        if amount<1:raise ValueError("reward is zero")
        rows=db.execute("SELECT * FROM billing_invoices WHERE item_type='request_reward' AND user_id=? AND status='pending' ORDER BY id DESC",(user_id,)).fetchall()
        existing=next((r for r in rows if json.loads(r["metadata"] or "{}").get("request_id")==request_id and r["amount_rub"]==amount),None)
        if existing:
            db.execute("COMMIT");return existing["id"],existing["payload"],amount
        payload=f"hpoint:reward:{uuid.uuid4().hex}"
        iid=insert_id("INSERT INTO billing_invoices(user_id,item_type,amount_rub,currency,payload,metadata) VALUES(?,?,?,?,?,?)",(user_id,'request_reward',amount,PAYMENT_CURRENCY,payload,json.dumps({'request_id':request_id})))
        db.execute("COMMIT");return iid,payload,amount
    except Exception:
        db.execute("ROLLBACK");raise


def _signature(value, password):
    try: digest=getattr(hashlib, ROBOKASSA_HASH_ALGORITHM.lower())
    except AttributeError: raise RuntimeError("Unsupported ROBOKASSA_HASH_ALGORITHM")
    return digest(f"{value}:{password}".encode()).hexdigest().upper()

def create_payment(invoice_id):
    if TEST_MONEY_ONLY:raise ValueError("Сейчас доступны только тестовые средства.")
    inv=get_invoice(invoice_id)
    if not inv: raise ValueError("invoice not found")
    if inv["status"]!="pending": raise ValueError("invoice already processed")
    if not ROBOKASSA_MERCHANT_LOGIN or not ROBOKASSA_PASSWORD_1 or not ROBOKASSA_PASSWORD_2:
        raise RuntimeError("Robokassa is not configured: set ROBOKASSA_MERCHANT_LOGIN, ROBOKASSA_PASSWORD_1 and ROBOKASSA_PASSWORD_2")
    amount=f'{inv["amount_rub"]:.2f}'
    description=(MONETIZATION_ITEMS.get(inv["item_type"]) or LEGACY_MONETIZATION_ITEMS.get(inv["item_type"]) or {"title":"Вознаграждение за помощь"})["title"][:100]
    params={"MerchantLogin":ROBOKASSA_MERCHANT_LOGIN,"OutSum":amount,"InvId":str(invoice_id),
            "Description":description,"Culture":"ru","Encoding":"utf-8",
            "SignatureValue":_signature(f"{ROBOKASSA_MERCHANT_LOGIN}:{amount}:{invoice_id}",ROBOKASSA_PASSWORD_1),
            "SuccessURL":PAYMENT_SUCCESS_URL,"FailURL":PAYMENT_FAIL_URL}
    db.execute("BEGIN IMMEDIATE")
    try:
        lock=" FOR UPDATE" if getattr(db,"is_postgres",False) else ""
        inv=db.execute("SELECT * FROM billing_invoices WHERE id=?"+lock,(invoice_id,)).fetchone()
        if inv["status"]!="pending":raise ValueError("invoice already processed")
        meta=json.loads(inv["metadata"] or "{}")
        if inv["item_type"]=="request_reward":
            request=db.execute("SELECT * FROM requests WHERE id=?"+lock,(meta.get("request_id"),)).fetchone()
            if not request or request["status"]!="open" or request["reward_payment_status"]!="none" or request["requester_id"]!=inv["user_id"]:raise ValueError("request unavailable")
        else:_validate_active_purchase(inv["user_id"],inv["item_type"],meta,lock=True)
        db.execute("UPDATE billing_invoices SET provider_payment_id=? WHERE id=?",(str(invoice_id),invoice_id))
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK");raise
    return "https://auth.robokassa.ru/Merchant/Index.aspx?"+urlencode(params),str(invoice_id)

def verify_robokassa_result(fields):
    if not ROBOKASSA_PASSWORD_2:return None
    try:
        raw_amount=str(fields.get("OutSum",""));raw_id=str(fields.get("InvId",""))
        if len(raw_amount)>40 or not raw_id.isdigit():return None
        amount=Decimal(raw_amount);invoice_id=int(raw_id)
        if not amount.is_finite() or amount<=0:return None
        expected=_signature(f"{raw_amount}:{raw_id}",ROBOKASSA_PASSWORD_2)
        if not hmac.compare_digest(str(fields.get("SignatureValue","")).upper(),expected):return None
    except (InvalidOperation,TypeError,ValueError):return None
    inv=get_invoice(invoice_id)
    if not inv or inv["currency"]!="RUB" or Decimal(inv["amount_rub"])!=amount:return None
    return inv


def fulfill_invoice(invoice_id,payment_id=None):
    db.execute("BEGIN IMMEDIATE")
    try:
        lock=" FOR UPDATE" if getattr(db,"is_postgres",False) else ""
        inv=db.execute("SELECT * FROM billing_invoices WHERE id=?"+lock,(invoice_id,)).fetchone()
        if not inv:
            db.execute("ROLLBACK");return False,"invoice_not_found"
        if payment_id and inv["provider_payment_id"] and payment_id!=inv["provider_payment_id"]:
            db.execute("ROLLBACK");return False,"payment_mismatch"
        if inv["status"]=="paid":
            db.execute("COMMIT");return True,"already_paid"
        if inv["status"]!="pending" or inv["currency"]!="RUB":
            db.execute("ROLLBACK");return False,"already_processed"
        meta=json.loads(inv["metadata"] or "{}")
        rid=meta.get("request_id");request=None
        if rid is not None:request=db.execute("SELECT * FROM requests WHERE id=?"+lock,(rid,)).fetchone()
        _lock_buyer(inv["user_id"])
        amount=int(inv["amount_rub"])
        active=bool(request and request["requester_id"]==inv["user_id"] and request["status"]=="open" and (not request["expires_at"] or request["expires_at"]>datetime.now(timezone.utc).isoformat()))
        fallback=False
        if inv["item_type"]=="request_reward":
            wallet_add_entry(inv["user_id"],amount,"payment","Оплата вознаграждения",f"invoice:{invoice_id}:payment",rid if request else None,invoice_id,test_amount_rub=0)
            can_reserve=active and request["reward_payment_status"]=="none" and int(request["reward_rub"])==amount
            if can_reserve:
                inserted=wallet_add_entry(inv["user_id"],-amount,"reward_reserve","Резерв вознаграждения",f"request:{rid}:reserve",rid,invoice_id,test_amount_rub=0)
                if not inserted:raise ValueError("reserve already exists")
                db.execute("UPDATE requests SET reward_payment_status='paid',reward_test_rub=0 WHERE id=?",(rid,))
            else:fallback=True
        elif inv["item_type"] in ("boost","more_responses") and (not active or (inv["item_type"]=="boost" and int(request["priority_boost"] or 0)>=100) or (int(request["reward_rub"] or 0)>0 and request["reward_payment_status"]!="paid")):
            wallet_add_entry(inv["user_id"],amount,"payment_credit","Платёж за недоступное продвижение зачислен в реальный баланс",f"invoice:{invoice_id}:credit",rid if request else None,invoice_id,test_amount_rub=0)
            fallback=True
        else:
            grant_entitlement(inv["user_id"],inv["item_type"],request_id=rid,ad_text=meta.get("ad_text"))
        db.execute("UPDATE billing_invoices SET status='paid',paid_at=CURRENT_TIMESTAMP WHERE id=?",(invoice_id,))
        db.execute("INSERT OR IGNORE INTO billing_events(invoice_id,event_type,provider_event_id,payload) VALUES(?,?,?,?)",(invoice_id,"successful_payment",payment_id or inv["provider_payment_id"],json.dumps(meta)))
        if fallback:
            db.execute("INSERT OR IGNORE INTO billing_events(invoice_id,event_type,provider_event_id,payload) VALUES(?,?,?,?)",(invoice_id,"credited_to_wallet",f"invoice:{invoice_id}:credit",json.dumps({"reason":"request_unavailable","amount_rub":amount})))
        db.execute("COMMIT")
        return True,"credited_to_wallet" if fallback else inv["item_type"]
    except Exception:
        db.execute("ROLLBACK");raise


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
        if item_type=="boost":
            suffix=" FOR UPDATE" if getattr(db,"is_postgres",False) else ""
            db.execute("SELECT id FROM requests WHERE id=?"+suffix,(metadata.get("request_id"),)).fetchone()
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
        if item_type=="boost":
            suffix=" FOR UPDATE" if getattr(db,"is_postgres",False) else ""
            db.execute("SELECT id FROM requests WHERE id=?"+suffix,(metadata.get("request_id"),)).fetchone()
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
            "SELECT COALESCE(SUM(test_amount_rub), 0) AS balance FROM wallet_transactions WHERE user_id=?",
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
            f"wallet-purchase:{key}", invoice_id=invoice_id, test_amount_rub=-price,
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
