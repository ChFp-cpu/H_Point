"""Test-money workflow and platform commission. No real acquiring is offered."""
import sqlite3
from datetime import datetime, timedelta, timezone

TEST_MONEY_ONLY = True
COMMISSION_PERCENT = 15
LEGACY_COMMISSION_PERCENT = 15
RESERVE_MINUTES = 5
LEGACY_PRICING_VERSION = "legacy_v1"
REWARD_PRICING_VERSION = "top_up15_v1"


def _add_pricing_column(db, name, definition):
    if getattr(db, "is_postgres", False):
        db.execute(f"ALTER TABLE requests ADD COLUMN IF NOT EXISTS {name} {definition}")
    elif name not in {row["name"] for row in db.execute("PRAGMA table_info(requests)").fetchall()}:
        try:
            db.execute(f"ALTER TABLE requests ADD COLUMN {name} {definition}")
        except sqlite3.OperationalError as error:
            if "duplicate column" not in str(error).lower():
                raise


def initialize_schema(db):
    # Defaults classify pre-existing agreements without changing their amounts,
    # payments, wallet sources or already recorded commission/payout snapshots.
    _add_pricing_column(db, "reward_pricing_version", "TEXT NOT NULL DEFAULT 'legacy_v1'")
    _add_pricing_column(db, "reward_total_rub", "INTEGER NOT NULL DEFAULT 0")
    db.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES('request_reward_pricing_v2')")
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
    """The immutable legacy test-money deduction, in whole RUB, half up."""
    amount=int(amount)
    fee=(amount*LEGACY_COMMISSION_PERCENT+50)//100
    return fee, amount-fee


def quote_new_reward(amount):
    """A new agreement: the entered reward is the helper's whole-RUB payout."""
    if isinstance(amount, bool) or not isinstance(amount, (int, str)) or not str(amount).isdigit():
        raise ValueError("reward_rub")
    amount = int(amount)
    if not 0 <= amount <= 100_000:
        raise ValueError("reward_rub")
    fee = (amount * 15 + 50) // 100
    return {"version": REWARD_PRICING_VERSION, "pricing_version": REWARD_PRICING_VERSION, "reward_rub": amount,
            "helper_rub": amount, "helper_reward_rub": amount, "commission_rub": fee,
            "total_rub": amount + fee, "commission_percent": 15 if amount else 0,
            "currency": "TEST_RUB", "test_only": True, "helper_test_rub": amount,
            "rounding": "whole_rub_half_up"}


def reward_quote(request):
    """Read the terms of this agreement, never reprice a historical reserve.

    New snapshots are immutable. Legacy test reserves keep the old deduction;
    historical real/mixed reserves and payouts before commission snapshots keep
    their original full payout. Only new agreements use a fee above the reward.
    """
    keys = request.keys()
    value = lambda key, default=None: request[key] if key in keys else default
    amount = int(value("reward_rub", 0) or 0)
    version = value("reward_pricing_version") or LEGACY_PRICING_VERSION
    payment_status = value("reward_payment_status", "none")
    test = int(value("reward_test_rub", 0) or 0)
    if version == REWARD_PRICING_VERSION:
        total = int(value("reward_total_rub", 0) or 0)
        fee = int(value("commission_rub", 0) or 0)
        helper = int(value("helper_reward_rub", 0) or 0)
        if min(amount, total, fee, helper) < 0 or helper != amount or total != helper + fee:
            raise ValueError("invalid reward pricing snapshot")
    elif version == LEGACY_PRICING_VERSION:
        total = amount
        if payment_status == "released":
            fee = int(value("commission_rub", 0) or 0)
            helper = int(value("helper_reward_rub", 0) or 0) or amount - fee
        elif amount and (test == total or payment_status == "none"):
            # New reserves are test-only. A previously opened card callback
            # changes provenance to real before settlement, preserving its terms.
            fee, helper = split_reward(amount)
        else:
            fee, helper = 0, amount
    else:
        raise ValueError("unknown reward pricing version")
    if not amount:
        fee, helper, total = 0, 0, 0
    test_only = bool(total and (test == total or payment_status == "none"))
    helper_test = helper if test_only else min(test, helper)
    percentage = 15 if amount and (version == REWARD_PRICING_VERSION or fee or
        (test_only and (payment_status != "released" or int(value("helper_reward_rub", 0) or 0)))) else 0
    return {"version": version, "pricing_version": version, "reward_rub": amount,
            "helper_rub": helper, "helper_reward_rub": helper, "commission_rub": fee,
            "total_rub": total, "commission_percent": percentage,
            "currency": "TEST_RUB" if test_only or not amount else "RUB",
            "test_only": test_only, "helper_test_rub": helper_test,
            "rounding": "whole_rub_half_up"}


def record_commission(db, request_id, quote):
    # The integer overload is retained only for callers holding legacy terms.
    if not isinstance(quote, dict):
        fee, helper = split_reward(quote)
        total = int(quote)
    else:
        total, fee, helper = (int(quote[field]) for field in ("total_rub", "commission_rub", "helper_reward_rub"))
    if min(total, fee, helper) < 0 or total != fee + helper:
        raise ValueError("invalid commission snapshot")
    db.execute("INSERT OR IGNORE INTO platform_commissions(request_id,gross_test_rub,commission_test_rub,helper_test_rub) VALUES(?,?,?,?)",(request_id,total,fee,helper))
    stored = db.execute("SELECT gross_test_rub,commission_test_rub,helper_test_rub FROM platform_commissions WHERE request_id=?", (request_id,)).fetchone()
    if not stored or tuple(stored[key] for key in ("gross_test_rub", "commission_test_rub", "helper_test_rub")) != (total, fee, helper):
        raise ValueError("commission snapshot changed")
    return fee, helper


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
