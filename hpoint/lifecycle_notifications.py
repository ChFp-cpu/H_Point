"""Durable, subscription-independent notices for automatically closed help.

Queue in the closing transaction. Claim with a lease so concurrent web/bot
processes cannot send the same pending notice together. Telegram delivery is
at-least-once after a crash at the network boundary; normal retries are bounded.
"""
from datetime import datetime, timedelta, timezone
from html import escape
import secrets


def initialize_schema(db):
    serial="BIGSERIAL" if getattr(db,"is_postgres",False) else "INTEGER"
    integer="BIGINT" if getattr(db,"is_postgres",False) else "INTEGER"
    db.execute(f"""CREATE TABLE IF NOT EXISTS request_notification_outbox(
        id {serial} PRIMARY KEY,request_id {integer} NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
        recipient_id {integer} NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        event_type TEXT NOT NULL,title TEXT NOT NULL,reason TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,
        available_at TEXT NOT NULL,claimed_at TEXT,claim_token TEXT,last_error TEXT,
        UNIQUE(request_id,recipient_id,event_type))""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_request_notice_pending ON request_notification_outbox(status,available_at,id)")
    db.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES('request_lifecycle_notices_v1')")


def _now(value=None):
    return value or datetime.now(timezone.utc)


def queue_closed(db, request, event_type, reason):
    if event_type not in {"expired","reserve_expired"}:return
    recipients={request["requester_id"],request["helper_id"]}
    recipients.update(row["candidate_id"] for row in db.execute(
        "SELECT candidate_id FROM request_candidates WHERE request_id=? AND status IN ('pending','applied','offered','accepted')",
        (request["id"],)).fetchall())
    at=_now().isoformat()
    for uid in recipients-{None}:
        user=db.execute("SELECT tg_user_id,email,email_verified,is_blocked FROM users WHERE user_id=?",(uid,)).fetchone()
        if not user or not user["tg_user_id"] or not user["email"] or not user["email_verified"] or user["is_blocked"]:continue
        db.execute("""INSERT OR IGNORE INTO request_notification_outbox(request_id,recipient_id,event_type,title,reason,available_at)
            VALUES(?,?,?,?,?,?)""",(request["id"],uid,event_type,request["what"],reason,at))


def claim(db, now=None, limit=20):
    at=_now(now);stale=(at-timedelta(minutes=5)).isoformat()
    db.execute("BEGIN IMMEDIATE")
    try:
        lock=" FOR UPDATE SKIP LOCKED" if getattr(db,"is_postgres",False) else ""
        rows=db.execute("""SELECT * FROM request_notification_outbox WHERE attempts<5 AND
            ((status='pending' AND available_at<=?) OR (status='sending' AND claimed_at<=?))
            ORDER BY available_at,id LIMIT ?"""+lock,(at.isoformat(),stale,max(1,min(int(limit),50)))).fetchall()
        result=[]
        for row in rows:
            token=secrets.token_hex(16)
            db.execute("UPDATE request_notification_outbox SET status='sending',attempts=attempts+1,claimed_at=?,claim_token=? WHERE id=?",(at.isoformat(),token,row["id"]))
            result.append({**dict(row),"claim_token":token,"attempts":row["attempts"]+1})
        # A process that died during the final attempt must not leave a stuck lease.
        db.execute("UPDATE request_notification_outbox SET status='failed',last_error='delivery_unconfirmed' WHERE status='sending' AND attempts>=5 AND claimed_at<=?",(stale,))
        db.execute("COMMIT");return result
    except Exception:
        db.execute("ROLLBACK");raise


def finish(db, notice, delivered, now=None):
    at=_now(now)
    status="sent" if delivered else "failed" if notice["attempts"]>=5 else "pending"
    retry=at+timedelta(seconds=min(3600,30*2**notice["attempts"]))
    return db.execute("""UPDATE request_notification_outbox SET status=?,available_at=?,claim_token=NULL,
        last_error=? WHERE id=? AND status='sending' AND claim_token=?""",
        (status,retry.isoformat(),None if delivered else "telegram_delivery_failed",notice["id"],notice["claim_token"])).rowcount==1


def message(notice, site_url):
    return ("Помощь «"+escape(notice["title"])+"» автоматически закрыта.\n"+
            escape(notice["reason"])+".\nНовые отклики больше не принимаются.\n"+
            escape(site_url.rstrip('/')+"/#/help/mine"))
