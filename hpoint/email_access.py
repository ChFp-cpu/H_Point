"""Email is the sole account entry point; Telegram is an optional linked client."""
from datetime import datetime, timezone
import hashlib
import re

from . import reliability


def has_verified_email(user):
    return bool(user and user["email"] and str(user["email"]).strip() and user["email_verified"])


def link_owner_has_verified_email(db, code):
    code=str(code or "").strip().upper()
    if not re.fullmatch(r"(?:[A-F0-9]{8}|[A-F0-9]{32})",code):return False
    digest=hashlib.sha256(code.encode("utf-8")).hexdigest()
    row=db.execute("SELECT email,email_verified FROM users WHERE (verification_code_hash=? OR verification_code=?) AND verification_code_expires_at>?",(digest,code,datetime.now(timezone.utc).isoformat())).fetchone()
    return has_verified_email(row)


def telegram_cleanup_preview(db):
    """Only explicitly linked Telegram identities are eligible for deletion."""
    identities=db.execute("SELECT user_id,email,email_verified FROM users WHERE tg_user_id IS NOT NULL ORDER BY user_id").fetchall()
    return {"delete_user_ids":[r["user_id"] for r in identities if not has_verified_email(r)],"end_session_user_ids":[r["user_id"] for r in identities]}


def cleanup_telegram_only_accounts(db, add_wallet_entry, *, backup_confirmed=False):
    """Delete only confirmed Telegram-only accounts during a backed-up release.

    This function is never called on import. Workers must be stopped by the
    deployment procedure. Email profiles survive, including linked profiles.
    Legacy rows lacking a Telegram identity are outside this cleanup's scope.
    """
    if not backup_confirmed:raise ValueError("A verified database backup is required before deleting Telegram accounts")
    db.execute("BEGIN IMMEDIATE")
    try:
        if getattr(db,"is_postgres",False):db.execute("SELECT pg_advisory_xact_lock(78246008)")
        preview=telegram_cleanup_preview(db)
        targets=preview["delete_user_ids"]
        ended=tickets=cancelled=0
        for uid in preview["end_session_user_ids"]:
            ended+=db.execute("DELETE FROM sessions WHERE user_id=?",(uid,)).rowcount
            tickets+=db.execute("DELETE FROM web_login_tickets WHERE user_id=?",(uid,)).rowcount
            tickets+=db.execute("DELETE FROM telegram_auth_tickets WHERE user_id=?",(uid,)).rowcount
        for uid in targets:
            suffix=" FOR UPDATE" if getattr(db,"is_postgres",False) else ""
            rows=db.execute("SELECT * FROM requests WHERE (requester_id=? OR helper_id=?) AND status IN ('open','in_progress','assigned') ORDER BY id"+suffix,(uid,uid)).fetchall()
            for request in rows:
                reliability.close_locked_request(db,request,None,"Аккаунт Telegram удалён при переходе на регистрацию по email","email_access_cleanup",add_wallet_entry)
                cancelled+=1
            db.execute("UPDATE requests SET helper_id=NULL WHERE helper_id=?",(uid,))
            db.execute("DELETE FROM chats WHERE user_a_id=? OR user_b_id=?",(uid,uid))
            db.execute("DELETE FROM chat_messages WHERE user_id=?",(uid,))
            db.execute("UPDATE identity_verification_requests SET reviewer_id=NULL WHERE reviewer_id=?",(uid,))
            db.execute("UPDATE support_tickets SET replied_by=NULL WHERE replied_by=?",(uid,))
            db.execute("UPDATE request_events SET actor_id=NULL WHERE actor_id=?",(uid,))
            db.execute("DELETE FROM admin_audit_log WHERE admin_user_id=?",(uid,))
            db.execute("UPDATE admin_audit_log SET target_user_id=NULL WHERE target_user_id=?",(uid,))
            db.execute("DELETE FROM favorites WHERE user_id=? OR favorite_user_id=?",(uid,uid))
            db.execute("DELETE FROM helper_queue WHERE user_id=?",(uid,))
            db.execute("DELETE FROM request_candidates WHERE candidate_id=?",(uid,))
            db.execute("DELETE FROM ads WHERE user_id=?",(uid,))
            db.execute("DELETE FROM commercial_orders WHERE user_id=?",(uid,))
            db.execute("DELETE FROM subscriptions WHERE user_id=?",(uid,))
            db.execute("DELETE FROM billing_events WHERE invoice_id IN (SELECT id FROM billing_invoices WHERE user_id=?)",(uid,))
            db.execute("DELETE FROM billing_invoices WHERE user_id=?",(uid,))
            db.execute("DELETE FROM requests WHERE requester_id=?",(uid,))
            db.execute("DELETE FROM users WHERE user_id=?",(uid,))
        db.execute("COMMIT")
        return {"deleted_users":len(targets),"ended_sessions":ended,"removed_login_tickets":tickets,"cancelled_requests":cancelled}
    except Exception:
        db.execute("ROLLBACK")
        raise
