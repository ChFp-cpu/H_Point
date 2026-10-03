"""Бизнес-логика H-Point без Telegram UI."""
import json
from .config import *
from .database import db, get_request, get_user, get_active_help, save_request_candidates, get_request_candidates


def infer_category(what: str) -> str:
    text = what.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return category
    return "other"


def set_helper_categories(user_id: int, categories: list[str]) -> None:
    valid = [c for c in categories if c in CATEGORIES]
    db.execute("UPDATE users SET helper_categories = ? WHERE user_id = ?", (json.dumps(valid, ensure_ascii=False), user_id))


def get_helper_categories(user_id: int) -> list[str]:
    row = get_user(user_id)
    if not row or not row["helper_categories"]:
        return []
    try:
        value = json.loads(row["helper_categories"])
        return [c for c in value if c in CATEGORIES]
    except (TypeError, ValueError):
        return []


def create_request(user_id: int, data: dict) -> int:
    category = data.get("category") or infer_category(data["what"])
    cur = db.execute(
        """INSERT INTO requests
        (requester_id, category, what, place, time_needed, urgency, details, status, priority_boost, lat, lon)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
        (user_id, category, data["what"], data["place"], data["time_needed"], data["urgency"], data["details"], STATUS_OPEN,
         data.get("lat"), data.get("lon")),
    )
    return cur.lastrowid


def is_in_queue(user_id: int) -> bool:
    return db.execute("SELECT 1 FROM helper_queue WHERE user_id = ?", (user_id,)).fetchone() is not None


def add_to_queue(user_id: int) -> None:
    db.execute("INSERT OR IGNORE INTO helper_queue (user_id) VALUES (?)", (user_id,))


def remove_from_queue(user_id: int) -> None:
    db.execute("DELETE FROM helper_queue WHERE user_id = ?", (user_id,))


def find_best_open_request_for(helper_id: int):
    rows = db.execute(
        "SELECT * FROM requests WHERE status = ? AND requester_id != ? ORDER BY id ASC LIMIT 50",
        (STATUS_OPEN, helper_id),
    ).fetchall()
    if not rows:
        return None
    return max(rows, key=lambda row: match_score(row, helper_id))


def find_best_queued_helper(request):
    rows = db.execute(
        "SELECT user_id FROM helper_queue WHERE user_id != ? ORDER BY joined_at, rowid",
        (request["requester_id"],),
    ).fetchall()
    candidates = []
    for row in rows:
        helper_id = row["user_id"]
        if get_active_help(helper_id) is None:
            candidates.append(helper_id)
    if not candidates:
        return None
    return max(candidates, key=lambda uid: match_score(request, uid))


def try_assign_helper(request_id: int, helper_id: int) -> bool:
    """Атомарно назначает свободного помощника только на одну активную заявку."""
    cur = db.execute(
        """UPDATE requests SET helper_id = ?, status = ?
        WHERE id = ? AND status = ? AND helper_id IS NULL AND requester_id != ?
        AND NOT EXISTS (
            SELECT 1 FROM requests active
            WHERE active.helper_id = ? AND active.status = ?
        )""",
        (helper_id, STATUS_IN_PROGRESS, request_id, STATUS_OPEN, helper_id, helper_id, STATUS_IN_PROGRESS),
    )
    if cur.rowcount == 1:
        remove_from_queue(helper_id)
        return True
    return False


def complete_request(request_id: int, helper_id: int) -> bool:
    try:
        db.execute("BEGIN IMMEDIATE")
        req = db.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
        if req is None or req["status"] != STATUS_IN_PROGRESS or req["helper_id"] != helper_id:
            db.execute("ROLLBACK")
            return False
        requester = db.execute("SELECT balance FROM users WHERE user_id = ?", (req["requester_id"],)).fetchone()
        if requester is None or requester["balance"] < REQUEST_COST:
            db.execute("ROLLBACK")
            return False
        db.execute("UPDATE requests SET status = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?", (STATUS_DONE, request_id))
        db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (REQUEST_COST, req["requester_id"]))
        db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (HELPER_REWARD, helper_id))
        db.execute("COMMIT")
        return True
    except Exception:
        db.execute("ROLLBACK")
        raise


def set_rating(request_id: int, user_id: int, rating: int) -> bool:
    if not 1 <= rating <= 5:
        return False
    cur = db.execute(
        "UPDATE requests SET rating = ?, requester_rating = ? WHERE id = ? AND requester_id = ? AND status = ? AND requester_rating IS NULL",
        (rating, rating, request_id, user_id, STATUS_DONE),
    )
    return cur.rowcount == 1


def set_helper_rating(request_id: int, user_id: int, rating: int) -> bool:
    if not 1 <= rating <= 5:
        return False
    cur = db.execute(
        "UPDATE requests SET helper_rating = ? WHERE id = ? AND helper_id = ? AND status = ? AND helper_rating IS NULL",
        (rating, request_id, user_id, STATUS_DONE),
    )
    return cur.rowcount == 1


def set_review(request_id: int, user_id: int, review: str, side: str) -> bool:
    column = "requester_review" if side == "requester" else "helper_review" if side == "helper" else None
    id_column = "requester_id" if side == "requester" else "helper_id" if side == "helper" else None
    if not column or not id_column:
        return False
    cur = db.execute(
        f"UPDATE requests SET {column} = ? WHERE id = ? AND {id_column} = ? AND status = ?",
        (review, request_id, user_id, STATUS_DONE),
    )
    return cur.rowcount == 1


def cancel_request(request_id: int, user_id: int) -> bool:
    cur = db.execute(
        "UPDATE requests SET status = ? WHERE id = ? AND requester_id = ? AND status = ?",
        (STATUS_CANCELLED, request_id, user_id, STATUS_OPEN),
    )
    return cur.rowcount == 1


# --- Monetization / billing business logic ---
from datetime import datetime, timedelta, timezone

def _future_iso(days: int = 30) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

def is_pro(user_id: int) -> bool:
    row = get_user(user_id)
    if not row or not row["pro_until"]:
        return False
    return row["pro_until"] > datetime.now(timezone.utc).isoformat()

def is_verified(user_id: int) -> bool:
    row = get_user(user_id)
    return bool(row and row["verified_until"] and row["verified_until"] > datetime.now(timezone.utc).isoformat())

def is_business(user_id: int) -> bool:
    row = get_user(user_id)
    return bool(row and row["business_until"] and row["business_until"] > datetime.now(timezone.utc).isoformat())

def grant_entitlement(user_id: int, item_type: str, request_id: int | None = None, ad_text: str | None = None, subscription_until: int | None = None) -> None:
    if item_type == "pro":
        if subscription_until:
            until = datetime.fromtimestamp(subscription_until, tz=timezone.utc).isoformat()
        else:
            current = get_user(user_id)["pro_until"]
            base = datetime.fromisoformat(current) if current else datetime.now(timezone.utc)
            if base < datetime.now(timezone.utc): base = datetime.now(timezone.utc)
            until = (base + timedelta(days=30)).isoformat()
        db.execute("UPDATE users SET pro_until=? WHERE user_id=?", (until, user_id))
    elif item_type == "verification":
        db.execute("UPDATE users SET verified_until=? WHERE user_id=?", (_future_iso(365), user_id))
    elif item_type in ("business", "business_pro"):
        if subscription_until:
            until = datetime.fromtimestamp(subscription_until, tz=timezone.utc).isoformat()
        else:
            current = get_user(user_id)["business_until"]
            base = datetime.fromisoformat(current) if current else datetime.now(timezone.utc)
            if base < datetime.now(timezone.utc): base = datetime.now(timezone.utc)
            until = (base + timedelta(days=30)).isoformat()
        db.execute("UPDATE users SET business_until=? WHERE user_id=?", (until, user_id))
    elif item_type == "favorites":
        db.execute("UPDATE users SET favorite_slots = favorite_slots + 5 WHERE user_id=?", (user_id,))
    elif item_type in ("boost", "more_responses"):
        if request_id is None:
            raise ValueError("request_id required")
        if item_type == "boost":
            db.execute("UPDATE requests SET priority_boost = priority_boost + 100 WHERE id=? AND requester_id=? AND status=?", (request_id,user_id,STATUS_OPEN))
        else:
            db.execute("UPDATE requests SET priority_boost = priority_boost + 50 WHERE id=? AND requester_id=? AND status=?", (request_id,user_id,STATUS_OPEN))
    elif item_type == "ad":
        if not ad_text:
            raise ValueError("ad_text required")
        db.execute("INSERT INTO ads (user_id,text,expires_at) VALUES (?,?,?)", (user_id,ad_text,_future_iso(7)))

def create_commercial_order(user_id: int, title: str, gross_amount: int) -> int:
    if gross_amount <= 0:
        raise ValueError("gross_amount must be positive")
    commission = round(gross_amount * 10 / 100)
    cur = db.execute("INSERT INTO commercial_orders (user_id,title,gross_amount,commission_amount) VALUES (?,?,?,?)", (user_id,title,gross_amount,commission))
    return cur.lastrowid

def get_commercial_order(order_id: int):
    return db.execute("SELECT * FROM commercial_orders WHERE id=?", (order_id,)).fetchone()

def add_favorite(user_id: int, favorite_user_id: int) -> bool:
    if user_id == favorite_user_id: return False
    user = get_user(user_id)
    if not user: return False
    count = db.execute("SELECT COUNT(*) AS n FROM favorites WHERE user_id=?", (user_id,)).fetchone()["n"]
    if count >= user["favorite_slots"]: return False
    cur = db.execute("INSERT OR IGNORE INTO favorites(user_id,favorite_user_id) VALUES(?,?)", (user_id,favorite_user_id))
    return cur.rowcount == 1

def match_score(request, helper_id: int) -> int:
    score = 0
    categories = get_helper_categories(helper_id)
    if not categories or request["category"] in categories:
        score += 100
    if request["urgency"] == URGENCY_OPTIONS[0]: score += 15
    elif request["urgency"] == URGENCY_OPTIONS[1]: score += 10
    score += max(0, 20 - int(request["id"]) % 20)
    score += int(request["priority_boost"] or 0)
    if is_pro(request["requester_id"]): score += 10
    return score


def haversine_km(lat1, lon1, lat2, lon2):
    from math import radians, sin, cos, asin, sqrt
    if None in (lat1,lon1,lat2,lon2): return 999.0
    dlat=radians(lat2-lat1); dlon=radians(lon2-lon1)
    a=sin(dlat/2)**2+cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return 6371*2*asin(sqrt(a))

def smart_match(request_id, limit=20):
    req=get_request(request_id)
    if not req: return []
    rows=db.execute("""SELECT u.*, r.id request_id, r.category request_category, r.what, r.lat request_lat, r.lon request_lon
                       FROM users u CROSS JOIN (SELECT id,category,what,lat,lon FROM requests WHERE id=?) r
                       WHERE u.user_id != ? AND u.user_id IS NOT NULL""",(request_id,req["requester_id"])).fetchall()
    out=[]
    for u in rows:
        if get_active_help(u["user_id"]) is not None: continue
        cats=get_helper_categories(u["user_id"])
        category_bonus=100 if (not cats or req["category"] in cats) else 0
        distance=haversine_km(req["lat"],req["lon"],u["lat"],u["lon"])
        stats=db.execute("""SELECT AVG(helper_rating) avg,COUNT(*) n FROM requests
                            WHERE helper_id=? AND status=? AND helper_rating IS NOT NULL""",(u["user_id"],STATUS_DONE)).fetchone()
        rating=float(stats["avg"]) if stats["avg"] is not None else 0.0
        rating_bonus=rating*12
        verified_bonus=12 if is_verified(u["user_id"]) else 0
        pro_bonus=8 if is_pro(u["user_id"]) else 0
        distance_bonus=max(0,30-distance*3) if distance < 10 else 0
        score=category_bonus+rating_bonus+verified_bonus+pro_bonus+distance_bonus+int(req["priority_boost"] or 0)
        out.append({"user_id":u["user_id"],"name":u["name"],"username":u["username"],"rating":round(rating,1),
                    "reviews":int(stats["n"] or 0),"verified":is_verified(u["user_id"]),"distance_km":round(distance,2) if distance<999 else None,
                    "score":round(score,1),"lat":u["lat"],"lon":u["lon"]})
    out.sort(key=lambda x:(x["score"],x["rating"],-(x["distance_km"] or 999)),reverse=True)
    out = out[:limit]
    save_request_candidates(request_id, out)
    return out

def get_candidates_for_request(request_id, limit=20):
    """Return the same candidate pool used by the website and Telegram."""
    req = get_request(request_id)
    if not req:
        return []
    # Recalculate so Telegram never shows stale candidates after profiles,
    # ratings, queue state or location have changed.
    matches = smart_match(request_id, limit=limit)
    if matches:
        return matches
    return [dict(row) for row in get_request_candidates(request_id, limit)]

def smart_requests_for_helper(helper_id, limit=20):
    rows=db.execute("SELECT * FROM requests WHERE status=? AND requester_id!=? ORDER BY created_at DESC LIMIT 100",(STATUS_OPEN,helper_id)).fetchall()
    result=[]
    for r in rows:
        distance=haversine_km(r["lat"],r["lon"],get_user(helper_id)["lat"],get_user(helper_id)["lon"])
        score=match_score(r,helper_id)
        if distance<999: score += max(0,30-distance*3)
        result.append((score,r,distance))
    result.sort(key=lambda x:x[0],reverse=True)
    return [{"request":dict(r),"score":round(score,1),"distance_km":round(d,2) if d<999 else None} for score,r,d in result[:limit]]
