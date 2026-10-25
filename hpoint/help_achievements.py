"""One-time HP awards based exclusively on completed, positively reviewed free help."""
from .config import STATUS_DONE

CATALOG = (
    dict(id="first_help", title="Первое доброе дело", reward_hp=10,
         description="Завершите бесплатную помощь и получите от автора 4–5 звёзд.", requirements={"completed":1}),
    dict(id="help_five", title="Надёжный помощник", reward_hp=25,
         description="Помогите 5 раз как минимум 3 разным людям с оценками 4–5.", requirements={"completed":5,"people":3}),
    dict(id="help_ten", title="Опора сообщества", reward_hp=50,
         description="Помогите 10 раз как минимум 5 разным людям с оценками 4–5.", requirements={"completed":10,"people":5}),
    dict(id="three_categories", title="Разные таланты", reward_hp=20,
         description="Помогите в 3 категориях как минимум 3 разным людям с оценками 4–5.", requirements={"categories":3,"people":3}),
    dict(id="five_thanks", title="Знак доверия", reward_hp=30,
         description="Получите за бесплатную помощь по 5 звёзд от 5 разных людей.", requirements={"thanks":5}),
)


def initialize_schema(db):
    integer="BIGINT" if getattr(db,"is_postgres",False) else "INTEGER"
    db.execute(f"""CREATE TABLE IF NOT EXISTS help_achievements(
        user_id {integer} NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        achievement_id TEXT NOT NULL,
        reward_hp {integer} NOT NULL CHECK(reward_hp>0),
        source_request_id {integer} REFERENCES requests(id) ON DELETE SET NULL,
        unlocked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(user_id,achievement_id))""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_help_achievement_requests ON requests(helper_id,status,requester_rating)")
    db.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(?)",("005_real_help_achievements",))


def migrate_profile_awards(db, source_id, target_id):
    """Move claim history inside the existing account migration transaction."""
    if source_id==target_id:return
    db.execute("""INSERT OR IGNORE INTO help_achievements(user_id,achievement_id,reward_hp,source_request_id,unlocked_at)
        SELECT ?,achievement_id,reward_hp,source_request_id,unlocked_at FROM help_achievements WHERE user_id=?""",(target_id,source_id))
    db.execute("DELETE FROM help_achievements WHERE user_id=?",(source_id,))


def _db():
    from .database import db
    return db


def _metrics(db, user_id):
    row=db.execute("""SELECT COUNT(*) completed,COUNT(DISTINCT requester_id) people,
        COUNT(DISTINCT category) categories,
        COUNT(DISTINCT CASE WHEN requester_rating=5 THEN requester_id END) thanks
        FROM requests WHERE helper_id=? AND requester_id!=? AND status=?
        AND requester_rating>=4 AND COALESCE(reward_rub,0)=0""",(user_id,user_id,STATUS_DONE)).fetchone()
    return {name:int(row[name] or 0) for name in ("completed","people","categories","thanks")}


def _qualifies(item, metrics):
    return all(metrics[name]>=goal for name,goal in item["requirements"].items())


def award_locked(db, user_id, source_request_id=None):
    """Caller owns the transaction and the user's row lock; never accept client scores."""
    user=db.execute("SELECT is_blocked FROM users WHERE user_id=?",(user_id,)).fetchone()
    if not user or user["is_blocked"]:return []
    metrics=_metrics(db,user_id)
    awarded=[]
    for item in CATALOG:
        if not _qualifies(item,metrics):continue
        created=db.execute("""INSERT OR IGNORE INTO help_achievements(user_id,achievement_id,reward_hp,source_request_id)
            VALUES(?,?,?,?)""",(user_id,item["id"],item["reward_hp"],source_request_id)).rowcount
        if created:awarded.append({k:item[k] for k in ("id","title","reward_hp")})
    if awarded:
        db.execute("UPDATE users SET balance=balance+? WHERE user_id=?",(sum(item["reward_hp"] for item in awarded),user_id))
    return awarded


def claim_earned(user_id):
    db=_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        lock=" FOR UPDATE" if getattr(db,"is_postgres",False) else ""
        db.execute("SELECT user_id FROM users WHERE user_id=?"+lock,(user_id,)).fetchone()
        awards=award_locked(db,user_id)
        db.execute("COMMIT")
        return awards
    except Exception:
        db.execute("ROLLBACK")
        raise


def achievement_state(user_id):
    db=_db();metrics=_metrics(db,user_id)
    unlocked={row["achievement_id"]:dict(row) for row in db.execute(
        "SELECT * FROM help_achievements WHERE user_id=?",(user_id,)).fetchall()}
    labels={"completed":"дел","people":"людей","categories":"категорий","thanks":"благодарностей"}
    items=[]
    for item in CATALOG:
        saved=unlocked.get(item["id"])
        item_progress=" · ".join(str(min(metrics[name],goal))+"/"+str(goal)+" "+labels[name] for name,goal in item["requirements"].items())
        items.append({k:item[k] for k in ("id","title","description","reward_hp")}|{
            "unlocked":bool(saved),"unlocked_at":saved["unlocked_at"] if saved else None,
            "reward_hp":int(saved["reward_hp"]) if saved else item["reward_hp"],
            "eligible":_qualifies(item,metrics),"progress_text":item_progress})
    return {"items":items,"unlocked_count":len(unlocked),"awarded_hp":sum(int(row["reward_hp"]) for row in unlocked.values()),
            "claimable_hp":sum(item["reward_hp"] for item in items if item["eligible"] and not item["unlocked"]),
            "rule":"Учитывается завершённая бесплатная помощь с оценкой автора 4–5. Каждая награда выдаётся один раз."}


def awards_for_request(user_id, request_id):
    titles={item["id"]:item["title"] for item in CATALOG}
    return [dict(row)|{"title":titles.get(row["achievement_id"],"Достижение за помощь")} for row in _db().execute(
        "SELECT achievement_id,reward_hp FROM help_achievements WHERE user_id=? AND source_request_id=?",(user_id,request_id)).fetchall()]


def reward_notice(user_id, request_id):
    awards=awards_for_request(user_id,request_id)
    return "" if not awards else "\n🏅 Достижения за помощь: "+"; ".join(item["title"]+" +"+str(item["reward_hp"])+" HP" for item in awards)+". Награды зачислены в общий баланс."
