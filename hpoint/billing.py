"""Website RUB checkout via Robokassa; no in-Telegram digital sales."""
import json, uuid, hashlib, hmac, math
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from .config import *
from .database import db, get_invoice, get_request, get_user, insert_id, wallet_add_entry
from .services import grant_entitlement
from .workflow import TEST_MONEY_ONLY
from . import workflow, personal


def _utc_date(value):
    """Read persisted access dates consistently, including legacy UTC dates."""
    if not value:
        return None
    try:
        date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def subscription_state(user_id, *, include_history=True, include_promotions=True):
    """Public access status uses the same entitlement date as actual matching.

    Invoice history is never treated as proof that a subscription is currently
    active. An expired term must stop displaying PRO immediately.
    """
    user = get_user(user_id)
    if not user:
        raise ValueError("user not found")
    now = datetime.now(timezone.utc)
    end = _utc_date(user["pro_until"])
    active = bool(end and end > now)
    item = MONETIZATION_ITEMS["pro"]
    pro = {
        "plan": "pro", "title": item["title"], "active": active,
        "status": "active" if active else "expired" if end else "inactive",
        "ends_at": end.isoformat() if end else None,
        "renewal_token": user["pro_until"],
        "days_remaining": max(0, math.ceil((end-now).total_seconds()/86400)) if end else 0,
        "auto_renew": False, "renewal_days": 30,
        "price_test_rub": int(item["rub"]), "price_hp": int(item["hp"]),
        "effects": {"helper_priority": 8 if active else 0, "request_priority": 10 if active else 0},
        "available_effects": {"helper_priority": 8, "request_priority": 10},
    }
    result = {"pro": pro, "usage": personal.usage(user_id, db_connection=db),
              "legacy_more_responses": {"sold": False, "historical_only": True, "replaced_by": "pro", "priority": 50}, "promotions": [], "history": []}
    if include_promotions:
        rows = db.execute("SELECT id,what,status,priority_boost,expires_at FROM requests WHERE requester_id=? AND priority_boost>0 ORDER BY id DESC LIMIT 50", (user_id,)).fetchall()
        for row in rows:
            expiry = _utc_date(row["expires_at"])
            result["promotions"].append({
                "request_id": row["id"], "title": row["what"], "status": row["status"],
                "priority": int(row["priority_boost"]),
                "active": row["status"] == "open" and (expiry is None or expiry > now),
                "source": "boost" if int(row["priority_boost"]) >= 100 else "more_responses",
            })
    if include_history:
        for row in db.execute("SELECT invoice_id,plan,starts_at,ends_at,provider FROM subscriptions WHERE user_id=? ORDER BY id DESC LIMIT 30", (user_id,)).fetchall():
            entry = dict(row)
            entry_end = _utc_date(row["ends_at"])
            entry_start = _utc_date(row["starts_at"])
            entry["status"] = "expired" if not entry_end or entry_end <= now else "scheduled" if entry_start and entry_start > now else "active"
            result["history"].append(entry)
    return result


def _record_subscription(invoice_id, user_id, item_type, provider):
    if item_type != "pro":
        return
    end = _utc_date(get_user(user_id)["pro_until"])
    if end:
        db.execute("""INSERT OR IGNORE INTO subscriptions(user_id,invoice_id,plan,status,starts_at,ends_at,provider)
            VALUES(?,?,'pro','active',?,?,?)""", (user_id,invoice_id,(end-timedelta(days=30)).isoformat(),end.isoformat(),provider))


def _check_replayed_purchase(existing, user_id, currency, item_type, metadata):
    if (existing["user_id"] != user_id or existing["currency"] != currency
            or existing["item_type"] != item_type or existing["status"] != "paid"
            or json.loads(existing["metadata"] or "{}") != metadata):
        raise ValueError("purchase key already used")

def _validate_active_purchase(user_id, item_type, metadata, lock=False):
    if item_type not in MONETIZATION_ITEMS:
        raise ValueError("item is no longer sold")
    if item_type == "pro":
        current = get_user(user_id)["pro_until"]
        end = _utc_date(current)
        if end and end > datetime.now(timezone.utc):
            if metadata.get("renew") is not True:
                raise ValueError("subscription already active")
            if metadata.get("expected_until") != current:
                raise ValueError("subscription changed")
        elif metadata.get("renew") is True and metadata.get("expected_until") != current:
            raise ValueError("subscription changed")
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
        quote=workflow.reward_quote(request)
        amount=int(quote["total_rub"])
        if amount<1:raise ValueError("reward is zero")
        rows=db.execute("SELECT * FROM billing_invoices WHERE item_type='request_reward' AND user_id=? AND status='pending' ORDER BY id DESC",(user_id,)).fetchall()
        existing=next((r for r in rows if json.loads(r["metadata"] or "{}").get("request_id")==request_id and r["amount_rub"]==amount and _reward_invoice_matches(r,request)),None)
        if existing:
            db.execute("COMMIT");return existing["id"],existing["payload"],amount
        payload=f"hpoint:reward:{uuid.uuid4().hex}"
        iid=insert_id("INSERT INTO billing_invoices(user_id,item_type,amount_rub,currency,payload,metadata) VALUES(?,?,?,?,?,?)",(user_id,'request_reward',amount,PAYMENT_CURRENCY,payload,json.dumps({'request_id':request_id,'reward_quote':quote})))
        db.execute("COMMIT");return iid,payload,amount
    except Exception:
        db.execute("ROLLBACK");raise


def _signature(value, password):
    try: digest=getattr(hashlib, ROBOKASSA_HASH_ALGORITHM.lower())
    except AttributeError: raise RuntimeError("Unsupported ROBOKASSA_HASH_ALGORITHM")
    return digest(f"{value}:{password}".encode()).hexdigest().upper()


def _reward_invoice_matches(invoice, request):
    """Match frozen agreement terms; never retrofit a legacy invoice."""
    quote=workflow.reward_quote(request)
    stored=json.loads(invoice["metadata"] or "{}").get("reward_quote")
    if int(invoice["amount_rub"])!=quote["total_rub"]:
        return False
    if stored is None:
        return quote["version"]==workflow.LEGACY_PRICING_VERSION
    return isinstance(stored,dict) and all(stored.get(key)==quote[key] for key in ("version","helper_rub","commission_rub","total_rub"))

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
        elif inv["item_type"] in LEGACY_MONETIZATION_ITEMS:
            # A previously issued invoice may still be paid. New issuance and
            # immediate purchases for every retired item are rejected elsewhere.
            pass
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
            # Historical real acquiring keeps its original full-amount terms.
            # New real acquiring is disabled; an unexpected verified callback
            # is credited to the real wallet instead of creating unsupported
            # mixed/new-pricing escrow or fabricating test funds.
            can_reserve=bool(active and request["reward_payment_status"]=="none"
                             and workflow.reward_quote(request)["version"]==workflow.LEGACY_PRICING_VERSION
                             and _reward_invoice_matches(inv,request))
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
            _record_subscription(invoice_id,inv["user_id"],inv["item_type"],"robokassa")
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
        if not isinstance(request_id, int) or isinstance(request_id, bool):
            raise ValueError("request_id required")
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
            _check_replayed_purchase(existing,user_id,"HP",item_type,metadata)
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
        _record_subscription(invoice_id,user_id,item_type,"points")
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
        if not isinstance(request_id, int) or isinstance(request_id, bool):
            raise ValueError("request_id required")
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
            _check_replayed_purchase(existing,user_id,"WALLET",item_type,metadata)
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
        _record_subscription(invoice_id,user_id,item_type,"test_wallet")
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
