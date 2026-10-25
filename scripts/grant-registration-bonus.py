"""One-time, idempotent RUB test credit for existing profiles. No personal output."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hpoint import database


def main():
    amount = database.REGISTRATION_BONUS_RUB
    if amount <= 0:
        raise SystemExit("REGISTRATION_BONUS_RUB must be positive")
    database.db.execute("BEGIN IMMEDIATE")
    try:
        lock = " FOR UPDATE" if getattr(database.db, "is_postgres", False) else ""
        users = database.db.execute("SELECT user_id FROM users ORDER BY user_id" + lock).fetchall()
        credited = sum(database.grant_registration_bonus(row["user_id"]) for row in users)
        database.db.execute("COMMIT")
    except Exception:
        database.db.execute("ROLLBACK")
        raise
    print(json.dumps({"profiles": len(users), "credited": credited, "amount_per_profile_rub": amount,
                      "total_credited_rub": credited * amount}))


if __name__ == "__main__":
    main()
