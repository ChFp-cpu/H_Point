"""Бизнес-логика H-Point без Telegram UI."""
import json, re, secrets
from datetime import datetime, timedelta, timezone
from .config import *
from .help_achievements import award_locked
from .database import db, get_request, get_user, get_active_help, save_request_candidates, get_request_candidates, insert_id, request_identity_verification, wallet_add_entry, get_or_create_chat_for_request


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
    hours = max(1, min(int(data.get("expires_in_hours", 48)), 168))
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    reward = int(data.get("reward_rub") or 0)
    if not 0 <= reward <= 100_000:
        raise ValueError("reward_rub")
    request_id = insert_id(
        """INSERT INTO requests
        (requester_id, category, what, place, time_needed, urgency, details, status, priority_boost, lat, lon, expires_at, reward_rub)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)""",
        (user_id, category, data["what"], data["place"], data["time_needed"], data["urgency"], data["details"], STATUS_OPEN,
         data.get("lat"), data.get("lon"), expires_at, reward),
    )
    db.execute(
        "INSERT INTO request_events(request_id,actor_id,event_type,message) VALUES(?,?,?,?)",
        (request_id, user_id, "created", "Заявка опубликована и ожидает помощника."),
    )
    return request_id

def expire_open_requests() -> None:
    """Close only unassigned requests whose chosen publication term ended."""
    expired = db.execute(
        "SELECT id,requester_id,reward_rub,reward_payment_status FROM requests WHERE status=? AND expires_at IS NOT NULL AND expires_at<=?",
        (STATUS_OPEN, datetime.now(timezone.utc).isoformat()),
    ).fetchall()
    if not expired:
        return
    ids = [row["id"] for row in expired]
    marks = ",".join("?" for _ in ids)
    db.execute(
        f"UPDATE requests SET status=?,cancel_reason=?,cancelled_at=CURRENT_TIMESTAMP WHERE id IN ({marks})",
        (STATUS_CANCELLED, "Срок публикации истёк", *ids),
    )
    for row in expired:
        request_id = row["id"]
        if row["reward_payment_status"] == "paid" and int(row["reward_rub"] or 0) > 0:
            amount = int(row["reward_rub"])
            wallet_add_entry(row["requester_id"], amount, "reward_refund", "Вознаграждение возвращено в кошелёк: срок заявки истёк", f"request:{request_id}:expiry-refund", request_id)
            db.execute("UPDATE requests SET reward_payment_status='wallet_refunded' WHERE id=?", (request_id,))
        db.execute(
            "INSERT INTO request_events(request_id,event_type,message) VALUES(?,?,?)",
            (request_id, "expired", "Срок публикации истёк. Заявка закрыта."),
        )


def is_in_queue(user_id: int) -> bool:
    return db.execute("SELECT 1 FROM helper_queue WHERE user_id = ?", (user_id,)).fetchone() is not None


def add_to_queue(user_id: int) -> None:
    db.execute("INSERT OR IGNORE INTO helper_queue (user_id) VALUES (?)", (user_id,))


def remove_from_queue(user_id: int) -> None:
    db.execute("DELETE FROM helper_queue WHERE user_id = ?", (user_id,))
    db.execute("UPDATE request_candidates SET status='withdrawn',updated_at=CURRENT_TIMESTAMP WHERE candidate_id=? AND status='applied'", (user_id,))


def accept_open_request(request_id: int, helper_id: int, author_id: int | None = None, application_token: str | None = None) -> str:
    """An explicit response to a published request is consent, not another application."""
    try:
        db.execute("BEGIN IMMEDIATE")
        lock = " FOR UPDATE" if getattr(db,"is_postgres",False) else ""
        helper = db.execute("SELECT * FROM users WHERE user_id=?" + lock,(helper_id,)).fetchone()
        request = db.execute("SELECT * FROM requests WHERE id=?" + lock,(request_id,)).fetchone()
        if not helper or helper["is_blocked"] or not request or request["requester_id"] == helper_id:
            db.execute("ROLLBACK");return "unavailable"
        if author_id is not None:
            application=db.execute("SELECT status,offer_token FROM request_candidates WHERE request_id=? AND candidate_id=?"+lock,(request_id,helper_id)).fetchone()
            if request["requester_id"] != author_id or not application or application["status"] != "applied" or application["offer_token"] != application_token:
                db.execute("ROLLBACK");return "unavailable"
        if request["status"] == STATUS_IN_PROGRESS and request["helper_id"] == helper_id:
            get_or_create_chat_for_request(request_id)
            db.execute("COMMIT");return "existing"
        if request["status"] != STATUS_OPEN or request["helper_id"] is not None or get_active_help(helper_id):
            db.execute("ROLLBACK");return "unavailable"
        if int(request["reward_rub"] or 0) > 0 and request["reward_payment_status"] != "paid":
            db.execute("ROLLBACK");return "awaiting_funds"
        db.execute("UPDATE requests SET helper_id=?,status=? WHERE id=?",(helper_id,STATUS_IN_PROGRESS,request_id))
        remove_from_queue(helper_id)
        db.execute("""INSERT INTO request_candidates(request_id,candidate_id,score,status,offer_token,updated_at)
                      VALUES(?,?,0,'accepted',NULL,CURRENT_TIMESTAMP)
                      ON CONFLICT(request_id,candidate_id) DO UPDATE SET status='accepted',offer_token=NULL,updated_at=CURRENT_TIMESTAMP""",(request_id,helper_id))
        db.execute("UPDATE request_candidates SET status='withdrawn',updated_at=CURRENT_TIMESTAMP WHERE request_id=? AND candidate_id!=? AND status IN ('pending','applied','offered')",(request_id,helper_id))
        db.execute("UPDATE request_candidates SET status='withdrawn',updated_at=CURRENT_TIMESTAMP WHERE candidate_id=? AND request_id!=? AND status IN ('applied','offered')",(helper_id,request_id))
        get_or_create_chat_for_request(request_id)
        db.execute("INSERT INTO request_events(request_id,actor_id,event_type,message) VALUES(?,?,?,?)",(request_id,helper_id,"helper_accepted","Помощник принял опубликованную заявку. Чат создан без повторного выбора кандидата."))
        db.execute("COMMIT");return "created"
    except Exception:
        db.execute("ROLLBACK");raise


def apply_to_request(request_id: int, helper_id: int) -> str:
    """Record real, request-specific interest; queue membership alone is not an application."""
    try:
        db.execute("BEGIN IMMEDIATE")
        lock = " FOR UPDATE" if getattr(db, "is_postgres", False) else ""
        helper = db.execute("SELECT * FROM users WHERE user_id=?" + lock, (helper_id,)).fetchone()
        request = db.execute("SELECT * FROM requests WHERE id=?" + lock, (request_id,)).fetchone()
        if not helper or helper["is_blocked"] or not request or request["status"] != STATUS_OPEN or request["requester_id"] == helper_id or get_active_help(helper_id):
            db.execute("ROLLBACK")
            return "unavailable"
        existing = db.execute("SELECT * FROM request_candidates WHERE request_id=? AND candidate_id=?" + lock, (request_id, helper_id)).fetchone()
        if existing and existing["status"] in ("applied", "offered"):
            db.execute("ROLLBACK")
            return existing["status"]
        add_to_queue(helper_id)
        db.execute("""INSERT INTO request_candidates(request_id,candidate_id,score,status,offer_token,seen_at,updated_at)
                      VALUES(?,?,?,'applied',?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                      ON CONFLICT(request_id,candidate_id) DO UPDATE SET score=excluded.score,status='applied',offer_token=excluded.offer_token,updated_at=CURRENT_TIMESTAMP""",
                   (request_id, helper_id, match_score(request, helper_id), secrets.token_hex(8)))
        db.execute("INSERT INTO request_events(request_id,actor_id,event_type,message) VALUES(?,?,?,?)", (request_id, helper_id, "helper_applied", "Помощник откликнулся на заявку. Автор может выбрать его в подборе."))
        db.execute("COMMIT")
        return "created"
    except Exception:
        db.execute("ROLLBACK")
        raise


def get_request_applications(requester_id: int, limit: int = 100):
    return db.execute("""SELECT rc.request_id,rc.candidate_id helper_id,rc.offer_token application_token,
                         u.name helper_name,r.what,r.requester_id,rc.updated_at
                         FROM request_candidates rc JOIN requests r ON r.id=rc.request_id
                         JOIN users u ON u.user_id=rc.candidate_id
                         WHERE r.requester_id=? AND r.status=? AND rc.status='applied' AND u.is_blocked=0
                         AND NOT EXISTS(SELECT 1 FROM requests busy WHERE busy.helper_id=rc.candidate_id AND busy.status=?)
                         ORDER BY rc.updated_at DESC,rc.request_id DESC LIMIT ?""", (requester_id, STATUS_OPEN, STATUS_IN_PROGRESS, limit)).fetchall()


def get_helper_applications(helper_id: int):
    return db.execute("""SELECT rc.request_id,rc.candidate_id helper_id,rc.offer_token application_token,
                         r.what,u.name requester_name FROM request_candidates rc
                         JOIN requests r ON r.id=rc.request_id JOIN users u ON u.user_id=r.requester_id
                         WHERE rc.candidate_id=? AND rc.status='applied' AND r.status=?
                         ORDER BY rc.updated_at DESC LIMIT 100""", (helper_id, STATUS_OPEN)).fetchall()


def cancel_request_application(request_id: int, helper_id: int, actor_id: int, token: str) -> bool:
    try:
        db.execute("BEGIN IMMEDIATE")
        lock = " FOR UPDATE" if getattr(db, "is_postgres", False) else ""
        if lock: db.execute("SELECT user_id FROM users WHERE user_id=? FOR UPDATE", (helper_id,)).fetchone()
        request = db.execute("SELECT * FROM requests WHERE id=?" + lock, (request_id,)).fetchone()
        application = db.execute("SELECT * FROM request_candidates WHERE request_id=? AND candidate_id=? AND status='applied'" + lock, (request_id, helper_id)).fetchone()
        if not request or request["status"] != STATUS_OPEN or actor_id not in (helper_id, request["requester_id"]) or not application or (application["offer_token"] or "") != token:
            db.execute("ROLLBACK")
            return False
        status = "withdrawn" if actor_id == helper_id else "declined"
        db.execute("UPDATE request_candidates SET status=?,updated_at=CURRENT_TIMESTAMP WHERE request_id=? AND candidate_id=? AND status='applied'", (status, request_id, helper_id))
        db.execute("INSERT INTO request_events(request_id,actor_id,event_type,message) VALUES(?,?,?,?)", (request_id, actor_id, "application_" + status, "Отклик отозван помощником." if status == "withdrawn" else "Автор отклонил отклик помощника."))
        db.execute("COMMIT")
        return True
    except Exception:
        db.execute("ROLLBACK")
        raise


def get_current_helper_offer(request_id: int):
    """Return the one helper currently deciding on a request, if any."""
    return db.execute(
        """SELECT rc.request_id, rc.candidate_id, rc.status, rc.updated_at, rc.offer_token,
                  u.name, u.username, u.tg_user_id
           FROM request_candidates rc
           JOIN users u ON u.user_id = rc.candidate_id
           JOIN requests r ON r.id = rc.request_id
           WHERE rc.request_id = ? AND rc.status = 'offered' AND r.status = ?
           ORDER BY rc.updated_at DESC LIMIT 1""",
        (request_id, STATUS_OPEN),
    ).fetchone()


def get_helper_offers(helper_id: int, limit: int = 20):
    """Offers awaiting a helper's answer; used by both the site and the bot."""
    return db.execute(
        """SELECT rc.request_id, rc.updated_at, rc.offer_token, r.category, r.what, r.place,
                  r.time_needed, r.urgency, r.details, r.requester_id, r.reward_rub, r.reward_payment_status,
                  requester.name requester_name, requester.username requester_username
           FROM request_candidates rc
           JOIN requests r ON r.id = rc.request_id
           JOIN users requester ON requester.user_id = r.requester_id
           WHERE rc.candidate_id = ? AND rc.status = 'offered' AND r.status = ?
           ORDER BY rc.updated_at DESC LIMIT ?""",
        (helper_id, STATUS_OPEN, limit),
    ).fetchall()


def offer_helper(request_id: int, helper_id: int, replace_offer_token: str | None = None) -> bool:
    """Let a requester invite one available volunteer without assigning them yet."""
    try:
        db.execute("BEGIN IMMEDIATE")
        lock = " FOR UPDATE" if getattr(db, "is_postgres", False) else ""
        if lock:
            db.execute("SELECT user_id FROM users WHERE user_id=? FOR UPDATE", (helper_id,)).fetchone()
        request = db.execute("SELECT * FROM requests WHERE id = ?" + lock, (request_id,)).fetchone()
        available = db.execute("SELECT 1 FROM helper_queue q JOIN users u ON u.user_id=q.user_id WHERE q.user_id=? AND u.is_blocked=0" + lock, (helper_id,)).fetchone()
        busy = db.execute(
            "SELECT 1 FROM requests WHERE helper_id = ? AND status = ?" + lock,
            (helper_id, STATUS_IN_PROGRESS),
        ).fetchone()
        categories = get_helper_categories(helper_id)
        applied = db.execute("SELECT 1 FROM request_candidates WHERE request_id=? AND candidate_id=? AND status='applied'", (request_id, helper_id)).fetchone()
        if not request or request["status"] != STATUS_OPEN or request["requester_id"] == helper_id or not available or busy or (categories and request["category"] not in categories and not applied):
            db.execute("ROLLBACK")
            return False

        current = get_current_helper_offer(request_id)
        # A stale tab must not silently replace an invitation the author did
        # not see. Replacing one requires its exact confirmed token.
        if current:
            if current["candidate_id"] == helper_id or replace_offer_token is None or (current["offer_token"] or "") != replace_offer_token:
                db.execute("ROLLBACK")
                return False
        elif replace_offer_token is not None:
            db.execute("ROLLBACK")
            return False
        db.execute(
            "UPDATE request_candidates SET status='withdrawn', updated_at=CURRENT_TIMESTAMP "
            "WHERE request_id=? AND status='offered' AND candidate_id!=?",
            (request_id, helper_id),
        )
        db.execute(
            """INSERT INTO request_candidates(request_id,candidate_id,score,status,offer_token,seen_at,updated_at)
               VALUES(?,?,?,'offered',?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
               ON CONFLICT(request_id,candidate_id) DO UPDATE SET
                 score=excluded.score,status='offered',offer_token=excluded.offer_token,updated_at=CURRENT_TIMESTAMP""",
            (request_id, helper_id, match_score(request, helper_id), secrets.token_hex(8)),
        )
        db.execute(
            "INSERT INTO request_events(request_id,actor_id,event_type,message) VALUES(?,?,?,?)",
            (request_id, request["requester_id"], "helper_invited", "Помощнику отправлено предложение подтвердить участие."),
        )
        db.execute("COMMIT")
        return True
    except Exception:
        db.execute("ROLLBACK")
        raise


def withdraw_helper_offer(request_id: int, requester_id: int, helper_id: int, offer_token: str) -> bool:
    """Revoke only this pending invitation, not the request or an active match."""
    try:
        db.execute("BEGIN IMMEDIATE")
        lock = " FOR UPDATE" if getattr(db, "is_postgres", False) else ""
        if lock:
            db.execute("SELECT user_id FROM users WHERE user_id=? FOR UPDATE", (helper_id,)).fetchone()
        request = db.execute("SELECT * FROM requests WHERE id=?" + lock, (request_id,)).fetchone()
        offer = db.execute(
            "SELECT * FROM request_candidates WHERE request_id=? AND candidate_id=? AND status='offered'" + lock,
            (request_id, helper_id),
        ).fetchone()
        if not request or request["requester_id"] != requester_id or request["status"] != STATUS_OPEN or not offer or (offer["offer_token"] or "") != offer_token:
            db.execute("ROLLBACK")
            return False
        db.execute("UPDATE request_candidates SET status='withdrawn',updated_at=CURRENT_TIMESTAMP WHERE request_id=? AND candidate_id=? AND status='offered'", (request_id, helper_id))
        db.execute("INSERT INTO request_events(request_id,actor_id,event_type,message) VALUES(?,?,?,?)", (request_id, requester_id, "helper_invitation_withdrawn", "Автор отозвал приглашение помощнику. Заявка остаётся открытой."))
        db.execute("COMMIT")
        return True
    except Exception:
        db.execute("ROLLBACK")
        raise


def respond_to_helper_offer(request_id: int, helper_id: int, accept: bool, offer_token: str | None = None) -> bool:
    """Accept or decline an invitation atomically, keeping the queue shared."""
    try:
        db.execute("BEGIN IMMEDIATE")
        lock = " FOR UPDATE" if getattr(db, "is_postgres", False) else ""
        if lock:
            db.execute("SELECT user_id FROM users WHERE user_id=? FOR UPDATE", (helper_id,)).fetchone()
        request = db.execute("SELECT * FROM requests WHERE id=?" + lock, (request_id,)).fetchone()
        offer = db.execute(
            "SELECT * FROM request_candidates WHERE request_id=? AND candidate_id=? AND status='offered'" + lock,
            (request_id, helper_id),
        ).fetchone()
        reward_ready = (int(request["reward_rub"] or 0) == 0 or request["reward_payment_status"] == "paid") if request else False
        if not offer or not request or request["status"] != STATUS_OPEN or (accept and not reward_ready) or (offer_token is not None and (offer["offer_token"] or "") != offer_token):
            db.execute("ROLLBACK")
            return False
        if not accept:
            db.execute(
                "UPDATE request_candidates SET status='declined', updated_at=CURRENT_TIMESTAMP "
                "WHERE request_id=? AND candidate_id=? AND status='offered'",
                (request_id, helper_id),
            )
            db.execute(
                "INSERT INTO request_events(request_id,actor_id,event_type,message) VALUES(?,?,?,?)",
                (request_id, helper_id, "helper_declined", "Помощник отказался от предложения."),
            )
            db.execute("COMMIT")
            return True

        current = db.execute(
            """UPDATE requests SET helper_id=?, status=?
               WHERE id=? AND status=? AND helper_id IS NULL AND requester_id!=?
               AND NOT EXISTS (
                 SELECT 1 FROM requests active
                 WHERE active.helper_id=? AND active.status=?
               )""",
            (helper_id, STATUS_IN_PROGRESS, request_id, STATUS_OPEN, helper_id, helper_id, STATUS_IN_PROGRESS),
        )
        if current.rowcount != 1:
            db.execute("ROLLBACK")
            return False
        remove_from_queue(helper_id)
        db.execute(
            "UPDATE request_candidates SET status='accepted', updated_at=CURRENT_TIMESTAMP "
            "WHERE request_id=? AND candidate_id=?",
            (request_id, helper_id),
        )
        db.execute(
            "UPDATE request_candidates SET status='withdrawn', updated_at=CURRENT_TIMESTAMP "
            "WHERE request_id=? AND candidate_id!=? AND status IN ('pending','applied','offered')",
            (request_id, helper_id),
        )
        db.execute(
            "UPDATE request_candidates SET status='withdrawn', updated_at=CURRENT_TIMESTAMP "
            "WHERE candidate_id=? AND request_id!=? AND status IN ('applied','offered')",
            (helper_id, request_id),
        )
        get_or_create_chat_for_request(request_id)
        db.execute("COMMIT")
        db.execute(
            "INSERT INTO request_events(request_id,actor_id,event_type,message) VALUES(?,?,?,?)",
            (request_id, helper_id, "helper_accepted", "Помощник подтвердил участие. Заявка в работе."),
        )
        return True
    except Exception:
        db.execute("ROLLBACK")
        raise


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
        "SELECT user_id FROM helper_queue WHERE user_id != ? ORDER BY joined_at, user_id",
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
    try:
        db.execute("BEGIN IMMEDIATE")
        if getattr(db, "is_postgres", False):
            # Serialize assignments for one helper across distinct requests.
            if not db.execute("SELECT user_id FROM users WHERE user_id=? FOR UPDATE", (helper_id,)).fetchone():
                db.execute("ROLLBACK")
                return False
        cur = db.execute(
            """UPDATE requests SET helper_id = ?, status = ?
            WHERE id = ? AND status = ? AND helper_id IS NULL AND requester_id != ?
            AND (reward_rub = 0 OR reward_payment_status = 'paid')
            AND NOT EXISTS (
                SELECT 1 FROM requests active
                WHERE active.helper_id = ? AND active.status = ?
            )""",
            (helper_id, STATUS_IN_PROGRESS, request_id, STATUS_OPEN, helper_id, helper_id, STATUS_IN_PROGRESS),
        )
        if cur.rowcount == 1:
            remove_from_queue(helper_id)
            db.execute("COMMIT")
            db.execute(
                "INSERT INTO request_events(request_id,actor_id,event_type,message) VALUES(?,?,?,?)",
                (request_id, helper_id, "helper_assigned", "Помощник назначен. Заявка в работе."),
            )
            return True
        db.execute("ROLLBACK")
        return False
    except Exception:
        db.execute("ROLLBACK")
        raise


def request_reward_note(request) -> str:
    amount = int(request["reward_rub"] or 0)
    if not amount:
        return ""
    if request["reward_payment_status"] == "released":
        return f"{amount} ₽ зачислено помощнику в кошелёк H-Point."
    if request["reward_payment_status"] == "paid":
        return f"{amount} ₽ зарезервировано в кошельке H-Point. Выплата — после помощи и подтверждения автора."
    return f"{amount} ₽ через кошелёк H-Point после помощи. Сумма пока не зарезервирована: перед началом автор должен создать резерв."


def reserve_request_reward(request_id: int, requester_id: int, expected_amount: int) -> bool:
    """Hold real wallet funds, without paying the helper or changing H-Points."""
    try:
        db.execute("BEGIN IMMEDIATE")
        lock = " FOR UPDATE" if getattr(db, "is_postgres", False) else ""
        if lock:
            db.execute("SELECT user_id FROM users WHERE user_id=? FOR NO KEY UPDATE", (requester_id,)).fetchone()
        request = db.execute("SELECT * FROM requests WHERE id=?" + lock, (request_id,)).fetchone()
        if not request or request["requester_id"] != requester_id or request["status"] != STATUS_OPEN:
            raise ValueError("request unavailable")
        amount = int(request["reward_rub"] or 0)
        if amount <= 0 or amount != expected_amount:
            raise ValueError("reward changed")
        if request["reward_payment_status"] == "paid":
            db.execute("COMMIT")
            return False
        if request["reward_payment_status"] != "none":
            raise ValueError("request unavailable")
        # An already opened acquiring session must not race wallet funding.
        invoices = db.execute("SELECT metadata FROM billing_invoices WHERE user_id=? AND item_type='request_reward' AND status='pending' AND provider_payment_id IS NOT NULL", (requester_id,)).fetchall()
        if any(json.loads(row["metadata"] or "{}").get("request_id") == request_id for row in invoices):
            raise ValueError("external payment pending")
        balance = db.execute("SELECT COALESCE(SUM(amount_rub),0) amount FROM wallet_transactions WHERE user_id=?", (requester_id,)).fetchone()["amount"]
        if int(balance or 0) < amount:
            raise ValueError("insufficient wallet")
        if not wallet_add_entry(requester_id, -amount, "reward_reserve", "Вознаграждение зарезервировано до подтверждения помощи автором", f"request:{request_id}:reserve", request_id):
            raise ValueError("reserve already recorded")
        db.execute("UPDATE requests SET reward_payment_status='paid' WHERE id=?", (request_id,))
        db.execute("INSERT INTO request_events(request_id,actor_id,event_type,message) VALUES(?,?,?,?)", (request_id, requester_id, "reward_reserved", f"В кошельке зарезервировано {amount} ₽. Выплата — после помощи и подтверждения автора."))
        db.execute("COMMIT")
        return True
    except Exception:
        db.execute("ROLLBACK")
        raise


def request_help_completion(request_id: int, helper_id: int) -> str:
    """Paid work needs the author's confirmation before any RUB transfer."""
    request = get_request(request_id)
    if not request or request["status"] != STATUS_IN_PROGRESS or request["helper_id"] != helper_id:
        return "unavailable"
    if not int(request["reward_rub"] or 0):
        return "completed" if complete_request(request_id, helper_id) else "unavailable"
    try:
        db.execute("BEGIN IMMEDIATE")
        lock = " FOR UPDATE" if getattr(db, "is_postgres", False) else ""
        request = db.execute("SELECT * FROM requests WHERE id=?" + lock, (request_id,)).fetchone()
        if not request or request["status"] != STATUS_IN_PROGRESS or request["helper_id"] != helper_id or request["reward_payment_status"] != "paid":
            db.execute("ROLLBACK")
            return "unavailable"
        if request["completion_requested_at"]:
            db.execute("COMMIT")
            return "pending"
        db.execute("UPDATE requests SET completion_requested_at=CURRENT_TIMESTAMP WHERE id=?", (request_id,))
        db.execute("INSERT INTO request_events(request_id,actor_id,event_type,message) VALUES(?,?,?,?)", (request_id, helper_id, "completion_requested", "Помощник сообщил о выполнении. Ожидается подтверждение автора для выплаты из резерва."))
        db.execute("COMMIT")
        return "created"
    except Exception:
        db.execute("ROLLBACK")
        raise


def complete_request(request_id: int, helper_id: int, confirmed_by: int | None = None) -> bool:
    try:
        db.execute("BEGIN IMMEDIATE")
        lock = " FOR UPDATE" if getattr(db, "is_postgres", False) else ""
        req = db.execute("SELECT * FROM requests WHERE id = ?" + lock, (request_id,)).fetchone()
        if req is None or req["status"] != STATUS_IN_PROGRESS or req["helper_id"] != helper_id:
            db.execute("ROLLBACK")
            return False
        paid_request = int(req["reward_rub"] or 0) > 0
        if paid_request and (req["reward_payment_status"] != "paid" or confirmed_by != req["requester_id"] or not req["completion_requested_at"]):
            db.execute("ROLLBACK")
            return False
        # H-Points are the incentive only for free neighbourly help.  A request
        # with a RUB reward is settled exclusively through the wallet ledger.
        # Loading and checking point balances for such requests used to make a
        # RUB job fail or alter HP despite the advertised payment method.
        if not paid_request:
            user_rows = db.execute(
                "SELECT user_id,balance FROM users WHERE user_id IN (?,?) ORDER BY user_id" + lock,
                (req["requester_id"], helper_id),
            ).fetchall()
            balances = {row["user_id"]: row["balance"] for row in user_rows}
            requester_balance = balances.get(req["requester_id"])
            if requester_balance is None or helper_id not in balances or requester_balance < REQUEST_COST:
                db.execute("ROLLBACK")
                return False
        db.execute("UPDATE requests SET status = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?", (STATUS_DONE, request_id))
        if not paid_request:
            db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (REQUEST_COST, req["requester_id"]))
            db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (HELPER_REWARD, helper_id))
        if req["reward_payment_status"] == "paid" and int(req["reward_rub"] or 0) > 0:
            amount = int(req["reward_rub"])
            wallet_add_entry(helper_id, amount, "reward_earned", "Вознаграждение за завершённую заявку", f"request:{request_id}:earned", request_id)
            db.execute("UPDATE requests SET reward_payment_status='released' WHERE id=?", (request_id,))
        db.execute(
            "INSERT INTO request_events(request_id,actor_id,event_type,message) VALUES(?,?,?,?)",
            (request_id, confirmed_by if paid_request else helper_id, "completed", "Автор подтвердил помощь и выплату из резерва. Можно оставить отзыв." if paid_request else "Помощник отметил заявку как завершённую. Можно оставить отзыв."),
        )
        db.execute("COMMIT")
        return True
    except Exception:
        db.execute("ROLLBACK")
        raise


def set_rating(request_id: int, user_id: int, rating: int) -> bool:
    if not 1 <= rating <= 5:
        return False
    request=get_request(request_id)
    if not request or request["requester_id"]!=user_id or request["status"]!=STATUS_DONE or not request["helper_id"]:
        return False
    try:
        db.execute("BEGIN IMMEDIATE")
        lock=" FOR UPDATE" if getattr(db,"is_postgres",False) else ""
        db.execute("SELECT user_id FROM users WHERE user_id=?"+lock,(request["helper_id"],)).fetchone()
        cur=db.execute(
            "UPDATE requests SET rating = ?, requester_rating = ? WHERE id = ? AND requester_id = ? AND status = ? AND requester_rating IS NULL",
            (rating,rating,request_id,user_id,STATUS_DONE))
        if cur.rowcount!=1:
            db.execute("ROLLBACK")
            return False
        award_locked(db,request["helper_id"],source_request_id=request_id)
        db.execute("COMMIT")
        return True
    except Exception:
        db.execute("ROLLBACK")
        raise


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


def cancel_request(request_id: int, user_id: int, reason: str = "") -> bool:
    reason = str(reason).strip()[:300] or "Отменено автором заявки"
    try:
        db.execute("BEGIN IMMEDIATE")
        request = db.execute("SELECT requester_id,reward_rub,reward_payment_status FROM requests WHERE id=?", (request_id,)).fetchone()
        if not request or request["requester_id"] != user_id or request["reward_payment_status"] not in ("none", "paid", "wallet_refunded"):
            db.execute("ROLLBACK")
            return False
        cur = db.execute(
            "UPDATE requests SET status=?,cancel_reason=?,cancelled_at=CURRENT_TIMESTAMP WHERE id=? AND requester_id=? AND status=?",
            (STATUS_CANCELLED, reason, request_id, user_id, STATUS_OPEN),
        )
        if cur.rowcount != 1:
            db.execute("ROLLBACK")
            return False
        db.execute(
            "UPDATE request_candidates SET status='withdrawn',updated_at=CURRENT_TIMESTAMP WHERE request_id=? AND status IN ('pending','applied','offered')",
            (request_id,),
        )
        if request["reward_payment_status"] == "paid" and int(request["reward_rub"] or 0) > 0:
            amount = int(request["reward_rub"])
            wallet_add_entry(user_id, amount, "reward_refund", "Вознаграждение возвращено в кошелёк после отмены заявки", f"request:{request_id}:cancel-refund", request_id)
            db.execute("UPDATE requests SET reward_payment_status='wallet_refunded' WHERE id=?", (request_id,))
        db.execute(
            "INSERT INTO request_events(request_id,actor_id,event_type,message) VALUES(?,?,?,?)",
            (request_id, user_id, "cancelled", f"Автор отменил заявку. Причина: {reason}"),
        )
        db.execute("COMMIT")
        return True
    except Exception:
        db.execute("ROLLBACK")
        raise


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
        # A completed payment may cover a manual review, but it must never
        # itself assert that a real person's identity was checked.
        request_identity_verification(user_id)
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
    return insert_id("INSERT INTO commercial_orders (user_id,title,gross_amount,commission_amount) VALUES (?,?,?,?)", (user_id,title,gross_amount,commission))

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

def _query_terms(query):
    return {word for word in re.findall(r"[\wа-яё-]{3,}", (query or "").lower())}

def smart_match(request_id, limit=20, query=""):
    req=get_request(request_id)
    if not req: return []
    rows=db.execute("""SELECT u.*, r.id request_id, r.category request_category, r.what, r.lat request_lat, r.lon request_lon
                       FROM users u
                       JOIN helper_queue q ON q.user_id=u.user_id
                       CROSS JOIN (SELECT id,category,what,lat,lon FROM requests WHERE id=?) r
                       WHERE u.user_id != ? AND u.user_id IS NOT NULL AND u.is_blocked=0
                       """,(request_id,req["requester_id"])).fetchall()
    applied_ids = {row["candidate_id"] for row in db.execute("SELECT candidate_id FROM request_candidates WHERE request_id=? AND status='applied'", (request_id,)).fetchall()}
    unavailable_for_request = {
        row["candidate_id"] for row in db.execute(
            "SELECT candidate_id FROM request_candidates WHERE request_id=? AND status IN ('declined','offered')",
            (request_id,),
        ).fetchall()
    }
    out=[]
    terms = _query_terms(query)
    for u in rows:
        if u["user_id"] in unavailable_for_request or get_active_help(u["user_id"]) is not None: continue
        cats=get_helper_categories(u["user_id"])
        if cats and req["category"] not in cats and u["user_id"] not in applied_ids: continue
        category_bonus=100 if (not cats or req["category"] in cats) else 0
        distance=haversine_km(req["lat"],req["lon"],u["lat"],u["lon"])
        stats=db.execute("""SELECT AVG(requester_rating) avg,COUNT(*) n FROM requests
                            WHERE helper_id=? AND status=? AND requester_rating IS NOT NULL""",(u["user_id"],STATUS_DONE)).fetchone()
        rating=float(stats["avg"]) if stats["avg"] is not None else 0.0
        rating_bonus=rating*12
        verified_bonus=12 if is_verified(u["user_id"]) else 0
        pro_bonus=8 if is_pro(u["user_id"]) else 0
        distance_bonus=max(0,30-distance*3) if distance < 10 else 0
        profile_text=" ".join(str(u.get(field) or "") if isinstance(u, dict) else str(u[field] or "") for field in ("name","username","city","bio","helper_categories")).lower()
        query_bonus=min(25, 8 * sum(term in profile_text for term in terms))
        score=category_bonus+rating_bonus+verified_bonus+pro_bonus+distance_bonus+query_bonus+int(req["priority_boost"] or 0)
        reasons=[]
        if u["user_id"] in applied_ids: reasons.append("откликнулся на вашу заявку")
        if category_bonus: reasons.append("подходит по категории")
        if distance_bonus: reasons.append("рядом")
        if rating_bonus: reasons.append("есть рейтинг")
        if verified_bonus: reasons.append("Telegram подтверждён")
        if query_bonus: reasons.append("соответствует уточнению")
        out.append({"user_id":u["user_id"],"name":u["name"],"username":u["username"],"rating":round(rating,1),
                    "reviews":int(stats["n"] or 0),"verified":is_verified(u["user_id"]),"distance_km":round(distance,2) if distance<999 else None,
                    "score":round(score,1),"applied":u["user_id"] in applied_ids,
                    # A requester only needs the distance to compare helpers.
                    # Publishing even rounded coordinates would expose a
                    # helper's neighbourhood before they accept the task.
                    "lat":None,"lon":None,"availability":u["helper_availability"] or "По договорённости","reasons":reasons})
    out.sort(key=lambda x:(x["applied"],x["score"],x["rating"],-(x["distance_km"] or 999)),reverse=True)
    out = out[:limit]
    save_request_candidates(request_id, out)
    return out

def get_candidates_for_request(request_id, limit=20):
    """Return the same candidate pool used by the website and Telegram."""
    req = get_request(request_id)
    if not req:
        return []
    # Recalculate from helper_queue every time. The bot and the site use one
    # database, so a person entering or leaving either queue is visible at once.
    return smart_match(request_id, limit=limit)

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
