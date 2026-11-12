"""Set existing accounts' available test wallets to one target, once per batch.

Run from the application directory with ``python - --target 10000
--batch-key UNIQUE_KEY < scripts/set_test_balances.py`` or invoke this file
normally. Existing ledger rows, real money and request reserves are preserved.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys


# Serialize administrative balance batches, including batches with different keys.
_ADVISORY_LOCK = 724091131649494


def set_test_balances(db, wallet_add_entry, target=10000, batch_key=None):
    """Append test-only corrections atomically using the supplied DB and writer.

    ``wallet_add_entry`` must write on ``db`` in this transaction. Reusing a
    completed batch key returns its original summary without adjusting balances
    again, even after spending or the creation of additional accounts.
    """
    if isinstance(target, bool) or not isinstance(target, int) or target < 0:
        raise ValueError("target must be a nonnegative integer")
    if not isinstance(batch_key, str) or not batch_key.strip() or len(batch_key) > 200:
        raise ValueError("batch_key must contain 1 to 200 characters")
    batch_key = batch_key.strip()
    postgres = bool(getattr(db, "is_postgres", False))
    db.execute("BEGIN" if postgres else "BEGIN IMMEDIATE")
    try:
        if postgres:
            db.execute("SELECT pg_advisory_xact_lock(?)", (_ADVISORY_LOCK,))
        db.execute("""CREATE TABLE IF NOT EXISTS test_balance_batches(
            batch_key TEXT PRIMARY KEY, target_rub BIGINT NOT NULL,
            users_count BIGINT NOT NULL, adjusted_count BIGINT NOT NULL,
            credited_rub BIGINT NOT NULL, debited_rub BIGINT NOT NULL,
            created_at TEXT NOT NULL)""")
        previous = db.execute("SELECT * FROM test_balance_batches WHERE batch_key=?", (batch_key,)).fetchone()
        if previous:
            if int(previous["target_rub"]) != target:
                raise ValueError("batch_key was already used with a different target")
            result = dict(previous)
            result.update(applied=False, already_applied=True)
            db.execute("COMMIT")
            return result

        # Match normal spending's user-first lock order. The subsequent table
        # lock also excludes legacy ledger writers that do not lock a user.
        suffix = " FOR NO KEY UPDATE" if postgres else ""
        users = db.execute("SELECT user_id FROM users ORDER BY user_id" + suffix).fetchall()
        if postgres:
            db.execute("LOCK TABLE wallet_transactions IN EXCLUSIVE MODE")
        balances = {int(row["user_id"]): (int(row["total"]), int(row["test"]))
                    for row in db.execute("""SELECT user_id, COALESCE(SUM(amount_rub),0) total,
                    COALESCE(SUM(test_amount_rub),0) test FROM wallet_transactions GROUP BY user_id""").fetchall()}
        adjusted = credited = debited = 0
        digest = hashlib.sha256(batch_key.encode("utf-8")).hexdigest()
        for user in users:
            uid = int(user["user_id"])
            total, test = balances.get(uid, (0, 0))
            delta = target - test
            if delta:
                inserted = wallet_add_entry(uid, delta, "test_balance_adjustment",
                    "Корректировка доступного тестового баланса до " + str(target) + " ₽",
                    "test-balance-adjustment:" + digest + ":" + str(uid), test_amount_rub=delta)
                if not inserted:
                    raise RuntimeError("test balance adjustment was not inserted for user " + str(uid))
                adjusted += 1
                credited += max(0, delta)
                debited += max(0, -delta)
            after = db.execute("""SELECT COALESCE(SUM(amount_rub),0) total,
                COALESCE(SUM(test_amount_rub),0) test FROM wallet_transactions WHERE user_id=?""", (uid,)).fetchone()
            if int(after["test"]) != target or int(after["total"]) - int(after["test"]) != total - test:
                raise RuntimeError("test-only balance verification failed for user " + str(uid))
        result = dict(batch_key=batch_key, target_rub=target, users_count=len(users),
                      adjusted_count=adjusted, credited_rub=credited, debited_rub=debited,
                      created_at=datetime.now(timezone.utc).isoformat())
        db.execute("""INSERT INTO test_balance_batches
            (batch_key,target_rub,users_count,adjusted_count,credited_rub,debited_rub,created_at)
            VALUES(?,?,?,?,?,?,?)""", tuple(result[key] for key in
            ("batch_key", "target_rub", "users_count", "adjusted_count", "credited_rub", "debited_rub", "created_at")))
        db.execute("COMMIT")
        result.update(applied=True, already_applied=False)
        return result
    except BaseException:
        db.execute("ROLLBACK")
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=int, required=True)
    parser.add_argument("--batch-key", required=True)
    args = parser.parse_args(argv)
    # stdin execution has __file__='<stdin>'; deployment runs it from app root.
    source = Path(globals().get("__file__", "<stdin>"))
    root = source.resolve().parents[1] if source.name != "<stdin>" else Path.cwd()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from hpoint import database
    print(json.dumps(set_test_balances(database.db, database.wallet_add_entry,
                                      target=args.target, batch_key=args.batch_key), ensure_ascii=False))


if __name__ == "__main__":
    main()
