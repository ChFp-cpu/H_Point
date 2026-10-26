"""Test-money workflow and platform commission. No real acquiring is offered."""
from datetime import datetime, timedelta, timezone

TEST_MONEY_ONLY = True
COMMISSION_PERCENT = 15
RESERVE_MINUTES = 5


def initialize_schema(db):
    serial="BIGSERIAL" if getattr(db,"is_postgres",False) else "INTEGER"
    db.execute(f"""CREATE TABLE IF NOT EXISTS platform_commissions(
        id {serial} PRIMARY KEY,
        request_id INTEGER UNIQUE REFERENCES requests(id) ON DELETE SET NULL,
        gross_test_rub INTEGER NOT NULL,
        commission_test_rub INTEGER NOT NULL,
        helper_test_rub INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")

    if not db.execute("SELECT 1 FROM schema_migrations WHERE version='008_test_help_deadline'").fetchone():
        db.execute("UPDATE requests SET reserve_deadline_at=? WHERE status='open' AND reward_rub>0 AND reward_payment_status='none' AND reserve_deadline_at IS NULL",(reserve_deadline(),))
        db.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES('008_test_help_deadline')")


def reserve_deadline():
    return (datetime.now(timezone.utc)+timedelta(minutes=RESERVE_MINUTES)).isoformat()


def split_reward(amount):
    amount=int(amount)
    fee=(amount*COMMISSION_PERCENT+50)//100
    return fee, amount-fee


def record_commission(db, request_id, gross):
    fee,net=split_reward(gross)
    db.execute("INSERT OR IGNORE INTO platform_commissions(request_id,gross_test_rub,commission_test_rub,helper_test_rub) VALUES(?,?,?,?)",(request_id,gross,fee,net))
    return fee,net


def test_wallet_summary(summary):
    """Public wallet has only test funds. Historical real funds stay untouched."""
    transactions=[]
    for entry in summary["transactions"]:
        amount=int(entry["test_amount_rub"] or 0)
        if amount:transactions.append({**entry,"amount_rub":amount,"test_amount_rub":amount})
    return {"test_only":True,"balance_rub":summary["test_balance_rub"],"test_balance_rub":summary["test_balance_rub"],
        "available_total_rub":summary["test_balance_rub"],"reserved_rub":summary["test_reserved_rub"],
        "test_reserved_rub":summary["test_reserved_rub"],"incoming_rub":summary.get("test_incoming_net_rub",summary["test_incoming_rub"]),
        "test_incoming_rub":summary.get("test_incoming_net_rub",summary["test_incoming_rub"]),"transactions":transactions}


def platform_income(db):
    row=db.execute("SELECT COUNT(*) n,COALESCE(SUM(commission_test_rub),0) total FROM platform_commissions").fetchone()
    return {"test_only":True,"commission_percent":COMMISSION_PERCENT,"completed_paid_helps":int(row["n"]),"earned_test_rub":int(row["total"])}
