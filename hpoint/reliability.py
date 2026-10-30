"""Ledger provenance and lifecycle operations using the caller's database."""
from datetime import datetime, timedelta, timezone
from . import workflow


def migrate_wallet_sources(db):
    """Classify historical test credits and transfers without changing totals."""
    db.execute("BEGIN IMMEDIATE")
    try:
        if getattr(db, "is_postgres", False):
            db.execute("SELECT pg_advisory_xact_lock(78246006)")
        if db.execute("SELECT 1 FROM schema_migrations WHERE version='006_wallet_sources'").fetchone():
            db.execute("COMMIT")
            return
        balances, reserves = {}, {}
        # Older card payments carry an invoice on their reserve entry. They
        # must keep their real source even when a test bonus was also present.
        real_invoices = {r["id"] for r in db.execute("SELECT id FROM billing_invoices WHERE item_type='request_reward' AND currency='RUB'").fetchall()}
        for row in db.execute("SELECT * FROM wallet_transactions ORDER BY id").fetchall():
            uid, amount, kind, rid = row["user_id"], int(row["amount_rub"]), row["kind"], row["request_id"]
            test = 0
            if kind == "registration_bonus":
                test = amount
            elif amount < 0:
                card_reserve = kind == "reward_reserve" and row["invoice_id"] in real_invoices
                test = 0 if card_reserve else -min(-amount, max(0, balances.get(uid, 0)))
                if kind == "reward_reserve":
                    reserves[rid] = -test
            elif kind in ("reward_earned", "reward_refund"):
                test = min(amount, reserves.get(rid, 0))
            balances[uid] = balances.get(uid, 0) + test
            db.execute("UPDATE wallet_transactions SET test_amount_rub=? WHERE id=?", (test, row["id"]))
        for rid, amount in reserves.items():
            db.execute("UPDATE requests SET reward_test_rub=? WHERE id=?", (amount, rid))
        db.execute("INSERT INTO schema_migrations(version) VALUES('006_wallet_sources')")
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise


def wallet_balances(db, user_id):
    row = db.execute("SELECT COALESCE(SUM(amount_rub),0) total,COALESCE(SUM(test_amount_rub),0) test FROM wallet_transactions WHERE user_id=?", (user_id,)).fetchone()
    return int(row["total"]), int(row["test"])


def reconcile_closed_reserves(db, add_entry):
    """Recover reserves stranded by historical late callbacks, exactly once."""
    db.execute("BEGIN IMMEDIATE")
    try:
        if getattr(db,"is_postgres",False):
            db.execute("SELECT pg_advisory_xact_lock(78246007)")
        if db.execute("SELECT 1 FROM schema_migrations WHERE version='007_closed_reserves'").fetchone():
            db.execute("COMMIT")
            return
        suffix=" FOR UPDATE" if getattr(db,"is_postgres",False) else ""
        rows=db.execute("SELECT * FROM requests WHERE status='cancelled' AND reward_payment_status='paid' AND reward_rub>0"+suffix).fetchall()
        for row in rows:
            rid=row["id"]
            refund_locked_reserve(db, row, add_entry, "Возврат резерва ранее закрытой заявки")
            db.execute("UPDATE requests SET reward_payment_status='wallet_refunded' WHERE id=?",(rid,))
            db.execute("INSERT INTO request_events(request_id,event_type,message) VALUES(?,?,?)",(rid,"reserve_reconciled","Резерв закрытой заявки возвращён в кошелёк с сохранением типа средств."))
        db.execute("INSERT INTO schema_migrations(version) VALUES('007_closed_reserves')")
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise


def refund_locked_reserve(db, request, add_entry, reason):
    """Restore the entire agreed escrow and its source, once under a row lock."""
    rid = request["id"]
    total = workflow.reward_quote(request)["total_rub"]
    test = int(request["reward_test_rub"] or 0)
    if total <= 0 or not 0 <= test <= total:
        raise ValueError("invalid reserve source")
    reference = f"request:{rid}:refund"
    inserted = add_entry(request["requester_id"], total, "reward_refund", reason,
                         reference, rid, test_amount_rub=test)
    if not inserted:
        # Some historical rows had a ledger refund but retained a paid flag.
        # Accept only the exact prior obligation, never an unrelated collision.
        existing = db.execute("SELECT user_id,amount_rub,test_amount_rub,request_id,kind FROM wallet_transactions WHERE reference=?", (reference,)).fetchone()
        if not existing or tuple(existing[key] for key in ("user_id", "amount_rub", "test_amount_rub", "request_id", "kind")) != (request["requester_id"], total, test, rid, "reward_refund"):
            raise ValueError("refund snapshot changed")


def close_locked_request(db, request, actor_id, reason, event_type, add_entry):
    """Caller owns the transaction and request row lock. Refund a reserve once."""
    rid = request["id"]
    db.execute("UPDATE requests SET status='cancelled',cancel_reason=?,cancelled_at=CURRENT_TIMESTAMP WHERE id=?", (reason, rid))
    db.execute("UPDATE request_candidates SET status='withdrawn',updated_at=CURRENT_TIMESTAMP WHERE request_id=? AND status IN ('pending','applied','offered')", (rid,))
    if request["reward_payment_status"] == "paid" and int(request["reward_rub"] or 0):
        refund_locked_reserve(db, request, add_entry, reason)
        db.execute("UPDATE requests SET reward_payment_status='wallet_refunded' WHERE id=?", (rid,))
    db.execute("INSERT INTO request_events(request_id,actor_id,event_type,message) VALUES(?,?,?,?)", (rid, actor_id, event_type, reason))
    db.execute("UPDATE support_tickets SET status='resolved' WHERE request_id=? AND status IN ('open','answered')", (rid,))
    db.execute("UPDATE requests SET dispute_status='resolved' WHERE id=? AND dispute_status='open'", (rid,))


def pair_reward_available(db, first, second):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    row = db.execute("""SELECT completed_at FROM requests WHERE status='done' AND reward_rub=0 AND hp_settled=1
        AND ((requester_id=? AND helper_id=?) OR (requester_id=? AND helper_id=?))
        ORDER BY completed_at DESC LIMIT 1""", (first, second, second, first)).fetchone()
    if not row or not row["completed_at"]:
        return True
    completed = datetime.fromisoformat(row["completed_at"].replace("Z", "+00:00"))
    if completed.tzinfo is None:
        completed = completed.replace(tzinfo=timezone.utc)
    return completed <= cutoff


def funnel_metrics(db, days=30):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = db.execute("SELECT id,requester_id,status,created_at,completed_at FROM requests WHERE created_at>=?", (cutoff,)).fetchall()
    accepted = {row["request_id"]: row["at"] for row in db.execute("""SELECT request_id,MIN(created_at) at FROM request_events
        WHERE event_type IN ('helper_accepted','helper_assigned','offer_accepted') GROUP BY request_id""").fetchall()}
    timings, counts = [], {}
    for row in rows:
        counts[row["requester_id"]] = counts.get(row["requester_id"], 0) + 1
        if row["id"] in accepted:
            start = datetime.fromisoformat(row["created_at"])
            end = datetime.fromisoformat(accepted[row["id"]])
            start = start.replace(tzinfo=timezone.utc) if start.tzinfo is None else start
            end = end.replace(tzinfo=timezone.utc) if end.tzinfo is None else end
            timings.append(max(0, (end-start).total_seconds()/60))
    total = len(rows)
    return {"days": days, "requests": total, "accepted": len(timings),
            "acceptance_percent": round(100*len(timings)/total,1) if total else 0,
            "completion_percent": round(100*sum(r["status"]=='done' for r in rows)/total,1) if total else 0,
            "average_acceptance_minutes": round(sum(timings)/len(timings),1) if timings else None,
            "repeat_requester_percent": round(100*sum(n>1 for n in counts.values())/len(counts),1) if counts else 0}
