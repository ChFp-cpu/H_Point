"""Database persistence with SQLite development and PostgreSQL production support."""
import sqlite3, hashlib, re, threading, json, secrets
from datetime import datetime, timedelta, timezone
from .config import DATABASE_URL, DB_PATH, START_BALANCE, STATUS_OPEN, STATUS_IN_PROGRESS, STATUS_DONE, ADMIN_TELEGRAM_IDS, TELEGRAM_AUTH_TTL_SECONDS, TELEGRAM_LINK_TTL_SECONDS, EMAIL_VERIFICATION_TTL_SECONDS, PHONE_VERIFICATION_TTL_SECONDS, AUTH_ATTEMPT_LIMIT, AUTH_ATTEMPT_WINDOW_SECONDS, CATEGORIES


class PostgresConnection:
    """Small compatibility layer so existing parameterized SQL works on PostgreSQL."""
    is_postgres = True

    def __init__(self, url):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("DATABASE_URL requires the psycopg package. Install requirements.txt.") from exc
        self._psycopg = psycopg
        self._dict_row = dict_row
        self._url = url
        self._local = threading.local()

    def _connection(self):
        conn = getattr(self._local, "connection", None)
        if conn is None or conn.closed:
            conn = self._psycopg.connect(self._url, autocommit=True, row_factory=self._dict_row, connect_timeout=10)
            self._local.connection = conn
        return conn

    @staticmethod
    def _sql(sql):
        sql = sql.strip()
        if sql.upper() == "BEGIN IMMEDIATE":
            return "BEGIN"
        ignored_insert = bool(re.search(r"INSERT\s+OR\s+IGNORE\s+INTO", sql, flags=re.I))
        sql = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", sql, flags=re.I)
        if ignored_insert and "ON CONFLICT" not in sql.upper():
            sql += " ON CONFLICT DO NOTHING"
        sql = re.sub(r"\bCURRENT_TIMESTAMP\b", "CURRENT_TIMESTAMP::text", sql, flags=re.I)
        return sql.replace("?", "%s")

    def execute(self, sql, params=None):
        return self._connection().execute(self._sql(sql), params or ())

    def executescript(self, script):
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def close(self):
        connection = getattr(self._local, "connection", None)
        if connection is not None and not connection.closed:
            connection.close()

class SQLiteConnection:
    """One SQLite connection per thread, avoiding cross-request transaction sharing."""
    is_postgres = False

    def __init__(self, path):
        self._path = path
        self._local = threading.local()

    def _connection(self):
        conn = getattr(self._local, "connection", None)
        if conn is None:
            conn = sqlite3.connect(self._path, isolation_level=None, timeout=15)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=15000")
            self._local.connection = conn
        return conn

    def execute(self, sql, params=None):
        return self._connection().execute(sql, params or ())

    def executescript(self, script):
        return self._connection().executescript(script)

    def close(self):
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            self._local.connection = None

def db_connect():
    if DATABASE_URL:
        return PostgresConnection(DATABASE_URL)
    return SQLiteConnection(DB_PATH)
db=db_connect()

def _columns(table):
    if getattr(db, "is_postgres", False):
        rows = db.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=?", (table,)).fetchall()
        return {r["column_name"] for r in rows}
    return {r["name"] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}
def _add_column(table,name,definition):
    # Migrations must be safe to run against every older H-Point database.
    # Some SQLite/legacy databases may already contain the column even when
    # the migration snapshot is stale, so treat SQLite's duplicate-column
    # error as an already-applied migration rather than crashing startup.
    if name in _columns(table):
        return
    if getattr(db, "is_postgres", False):
        db.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {definition}")
        return
    try:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise

def init_db():
    schema = """
    CREATE TABLE IF NOT EXISTS users(
      user_id INTEGER PRIMARY KEY, name TEXT NOT NULL, username TEXT, email TEXT UNIQUE,
      password_hash TEXT, balance INTEGER NOT NULL DEFAULT 0, helper_categories TEXT NOT NULL DEFAULT '',
      helper_availability TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, pro_until TEXT, verified_until TEXT,
      business_until TEXT, favorite_slots INTEGER NOT NULL DEFAULT 3,
      tg_user_id INTEGER UNIQUE, verification_code TEXT, verification_code_hash TEXT, verification_code_expires_at TEXT, web_verified INTEGER NOT NULL DEFAULT 0,
      email_verified INTEGER NOT NULL DEFAULT 0,
      full_name TEXT DEFAULT '', birth_date TEXT, phone TEXT, phone_verified INTEGER NOT NULL DEFAULT 0,
      lat REAL, lon REAL, city TEXT DEFAULT '', bio TEXT DEFAULT '',
      role TEXT NOT NULL DEFAULT 'user', is_blocked INTEGER NOT NULL DEFAULT 0, blocked_reason TEXT,
      last_seen_at TEXT
    );
    CREATE TABLE IF NOT EXISTS sessions(
      token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      expires_at TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, device_id TEXT
    );
    CREATE TABLE IF NOT EXISTS identity_verification_requests(
      user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
      status TEXT NOT NULL DEFAULT 'pending', submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      reviewed_at TEXT, reviewer_id INTEGER REFERENCES users(user_id), note TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS web_login_tickets(
      token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      expires_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS telegram_auth_tickets(
      token_hash TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
      expires_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS auth_attempts(
      action TEXT NOT NULL, subject_hash TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
      expires_at TEXT NOT NULL, PRIMARY KEY(action,subject_hash)
    );
    CREATE TABLE IF NOT EXISTS email_verification_codes(
      user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
      code_hash TEXT NOT NULL, expires_at TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS phone_verification_codes(
      user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
      phone TEXT NOT NULL, code_hash TEXT NOT NULL, expires_at TEXT NOT NULL,
      attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS requests(
      id INTEGER PRIMARY KEY AUTOINCREMENT, requester_id INTEGER NOT NULL REFERENCES users(user_id),
      helper_id INTEGER REFERENCES users(user_id), category TEXT NOT NULL DEFAULT 'other',
      what TEXT NOT NULL, place TEXT NOT NULL, time_needed TEXT NOT NULL, urgency TEXT NOT NULL,
      details TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', rating INTEGER,
      requester_rating INTEGER, requester_review TEXT, helper_rating INTEGER, helper_review TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, completed_at TEXT,
      priority_boost INTEGER NOT NULL DEFAULT 0, lat REAL, lon REAL,
      expires_at TEXT, views INTEGER NOT NULL DEFAULT 0, reward_rub INTEGER NOT NULL DEFAULT 0,
      reward_payment_status TEXT NOT NULL DEFAULT 'none'
    );
    CREATE TABLE IF NOT EXISTS helper_queue(user_id INTEGER PRIMARY KEY REFERENCES users(user_id), joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS billing_invoices(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(user_id),
      item_type TEXT NOT NULL, amount_rub INTEGER NOT NULL DEFAULT 0, currency TEXT NOT NULL DEFAULT 'RUB',
      payload TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'pending', metadata TEXT NOT NULL DEFAULT '{}',
      provider_payment_id TEXT UNIQUE, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, paid_at TEXT
    );
    CREATE TABLE IF NOT EXISTS billing_events(id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER REFERENCES billing_invoices(id),
      event_type TEXT NOT NULL, provider_event_id TEXT UNIQUE, payload TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS wallet_transactions(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      amount_rub INTEGER NOT NULL,
      kind TEXT NOT NULL,
      description TEXT NOT NULL,
      request_id INTEGER REFERENCES requests(id) ON DELETE SET NULL,
      invoice_id INTEGER REFERENCES billing_invoices(id) ON DELETE SET NULL,
      reference TEXT NOT NULL UNIQUE,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS subscriptions(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      invoice_id INTEGER UNIQUE REFERENCES billing_invoices(id), plan TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
      starts_at TEXT NOT NULL, ends_at TEXT NOT NULL, provider TEXT NOT NULL DEFAULT 'manual',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS favorites(user_id INTEGER NOT NULL REFERENCES users(user_id), favorite_user_id INTEGER NOT NULL REFERENCES users(user_id),
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(user_id,favorite_user_id));
    CREATE TABLE IF NOT EXISTS ads(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL REFERENCES users(user_id),
      text TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',expires_at TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS commercial_orders(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL REFERENCES users(user_id),
      title TEXT NOT NULL,gross_amount INTEGER NOT NULL,commission_percent INTEGER NOT NULL DEFAULT 10,commission_amount INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'draft',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS chats(id INTEGER PRIMARY KEY AUTOINCREMENT,request_id INTEGER NOT NULL UNIQUE REFERENCES requests(id) ON DELETE CASCADE,user_a_id INTEGER NOT NULL REFERENCES users(user_id),user_b_id INTEGER NOT NULL REFERENCES users(user_id),created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS chat_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,user_id INTEGER NOT NULL REFERENCES users(user_id),text TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS request_candidates(
      request_id INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
      candidate_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      score REAL NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'pending',
      offer_token TEXT,
      seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY(request_id,candidate_id)
    );
    CREATE TABLE IF NOT EXISTS request_views(
      request_id INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
      viewer_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY(request_id,viewer_id)
    );
    CREATE TABLE IF NOT EXISTS request_events(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      request_id INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
      actor_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
      event_type TEXT NOT NULL,
      message TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS support_tickets(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      subject TEXT NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
      admin_reply TEXT, replied_by INTEGER REFERENCES users(user_id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      replied_at TEXT
    );
    CREATE TABLE IF NOT EXISTS community_events(
      id INTEGER PRIMARY KEY AUTOINCREMENT, creator_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', place TEXT NOT NULL,
      starts_at TEXT NOT NULL, ends_at TEXT, capacity INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'published', image_data TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS event_participants(
      event_id INTEGER NOT NULL REFERENCES community_events(id) ON DELETE CASCADE,
      user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY(event_id,user_id)
    );
    CREATE TABLE IF NOT EXISTS ai_usage(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      request_count INTEGER NOT NULL DEFAULT 0, token_count INTEGER NOT NULL DEFAULT 0,
      period_start TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(user_id,period_start)
    );
    CREATE TABLE IF NOT EXISTS admin_audit_log(
      id INTEGER PRIMARY KEY AUTOINCREMENT, admin_user_id INTEGER NOT NULL REFERENCES users(user_id),
      action TEXT NOT NULL, target_user_id INTEGER REFERENCES users(user_id), details TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS game_profiles(
      user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
      games_played INTEGER NOT NULL DEFAULT 0,
      games_completed INTEGER NOT NULL DEFAULT 0,
      games_hp_earned INTEGER NOT NULL DEFAULT 0,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS game_sessions(
      id TEXT PRIMARY KEY,
      user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      game_code TEXT NOT NULL,
      state TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'active',
      score INTEGER NOT NULL DEFAULT 0,
      started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      last_action_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      completed_at TEXT,
      expires_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS game_records(
      user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      game_code TEXT NOT NULL,
      best_score INTEGER NOT NULL DEFAULT 0,
      best_meta TEXT NOT NULL DEFAULT '{}',
      plays INTEGER NOT NULL DEFAULT 0,
      completions INTEGER NOT NULL DEFAULT 0,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY(user_id,game_code)
    );
    CREATE TABLE IF NOT EXISTS game_daily_rewards(
      user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      game_code TEXT NOT NULL,
      reward_date TEXT NOT NULL,
      best_score INTEGER NOT NULL DEFAULT 0,
      awarded_hp INTEGER NOT NULL DEFAULT 0,
      result_hp INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(user_id,game_code,reward_date)
    );
    CREATE TABLE IF NOT EXISTS game_transactions(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      amount_hp INTEGER NOT NULL,
      kind TEXT NOT NULL,
      description TEXT NOT NULL,
      reference TEXT NOT NULL UNIQUE,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS game_item_ownership(
      user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      item_id TEXT NOT NULL,
      equipped INTEGER NOT NULL DEFAULT 0,
      purchased_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY(user_id,item_id)
    );
    CREATE TABLE IF NOT EXISTS game_achievements(
      user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      achievement_id TEXT NOT NULL,
      unlocked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY(user_id,achievement_id)
    );
    CREATE TABLE IF NOT EXISTS game_daily_challenge_claims(
      user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      challenge_id TEXT NOT NULL,
      reward_date TEXT NOT NULL,
      claimed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY(user_id,challenge_id,reward_date)
    );
    CREATE TABLE IF NOT EXISTS game_scenario_history(
      user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      game_code TEXT NOT NULL,
      scenario_id TEXT NOT NULL,
      content_version TEXT NOT NULL,
      selected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY(user_id,game_code,scenario_id)
    );
    CREATE INDEX IF NOT EXISTS idx_request_candidates_request ON request_candidates(request_id,status,score);
    CREATE INDEX IF NOT EXISTS idx_request_candidates_candidate ON request_candidates(candidate_id,status);
    CREATE INDEX IF NOT EXISTS idx_support_tickets_status ON support_tickets(status,created_at);
    CREATE INDEX IF NOT EXISTS idx_community_events_upcoming ON community_events(status,starts_at);
    CREATE INDEX IF NOT EXISTS idx_event_participants_user ON event_participants(user_id,joined_at);
    CREATE INDEX IF NOT EXISTS idx_chat_messages_chat ON chat_messages(chat_id,id);
    CREATE INDEX IF NOT EXISTS idx_identity_verification_status ON identity_verification_requests(status,submitted_at);
    CREATE INDEX IF NOT EXISTS idx_requests_open ON requests(status,created_at);
    CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
    CREATE INDEX IF NOT EXISTS idx_telegram_auth_tickets_expires ON telegram_auth_tickets(expires_at);
    CREATE INDEX IF NOT EXISTS idx_email_verification_codes_expires ON email_verification_codes(expires_at);
    CREATE INDEX IF NOT EXISTS idx_phone_verification_codes_expires ON phone_verification_codes(expires_at);
    CREATE INDEX IF NOT EXISTS idx_game_sessions_user_status ON game_sessions(user_id,status,started_at);
    CREATE INDEX IF NOT EXISTS idx_game_transactions_user ON game_transactions(user_id,id DESC);
    CREATE INDEX IF NOT EXISTS idx_game_daily_rewards_date ON game_daily_rewards(user_id,reward_date);
    CREATE INDEX IF NOT EXISTS idx_game_scenario_history_rotation ON game_scenario_history(user_id,game_code,selected_at);
    """
    if getattr(db, "is_postgres", False):
        schema = schema.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY").replace("INTEGER", "BIGINT")
    db.executescript(schema)
    db.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
    db.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(?)", ("001_initial",))
    db.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(?)", ("002_hpoint_games",))
    db.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(?)", ("003_hpoint_games_rewards",))
    db.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(?)", ("004_learning_game_content",))
    # Safe migration of the old project.
    for t,n,d in [
      ("users","email","TEXT"),("users","password_hash","TEXT"),("users","tg_user_id","INTEGER"),
      ("users","verification_code","TEXT"),("users","verification_code_hash","TEXT"),("users","verification_code_expires_at","TEXT"),("users","web_verified","INTEGER NOT NULL DEFAULT 0"),("users","email_verified","INTEGER NOT NULL DEFAULT 0"),
      ("users","full_name","TEXT DEFAULT ''"),("users","birth_date","TEXT"),("users","phone","TEXT"),("users","phone_verified","INTEGER NOT NULL DEFAULT 0"),
      ("users","lat","REAL"),("users","lon","REAL"),("users","city","TEXT DEFAULT ''"),("users","bio","TEXT DEFAULT ''"),
      ("users","role","TEXT NOT NULL DEFAULT 'user'"),("users","is_blocked","INTEGER NOT NULL DEFAULT 0"),("users","blocked_reason","TEXT"),
      ("users","last_seen_at","TEXT"),("users","helper_availability","TEXT NOT NULL DEFAULT ''"),
      ("request_candidates","offer_token","TEXT"),
      ("requests","lat","REAL"),("requests","lon","REAL"),("requests","expires_at","TEXT"),("requests","views","INTEGER NOT NULL DEFAULT 0"),("requests","reward_rub","INTEGER NOT NULL DEFAULT 0"),("requests","reward_payment_status","TEXT NOT NULL DEFAULT 'none'"),("requests","cancel_reason","TEXT"),("requests","cancelled_at","TEXT"),("community_events","image_data","TEXT NOT NULL DEFAULT ''"),("billing_invoices","amount_rub","INTEGER NOT NULL DEFAULT 0"),
      ("billing_invoices","currency","TEXT NOT NULL DEFAULT 'RUB'"),("billing_invoices","provider_payment_id","TEXT"),
      ("game_daily_rewards","result_hp","INTEGER NOT NULL DEFAULT 0")
      ,("sessions","device_id","TEXT")
    ]: _add_column(t,n,d)
    # Legacy payment columns remain for backwards-compatible data, but new code never uses them.
    db.execute("CREATE INDEX IF NOT EXISTS idx_requests_geo ON requests(status,lat,lon)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_requests_expires ON requests(status,expires_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_request_events_request ON request_events(request_id, id DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_wallet_transactions_user ON wallet_transactions(user_id, id DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_device ON sessions(device_id,expires_at)")
    # The personal dashboard reads both sides of the request relationship on
    # every sync.  These indexes keep that query fast as request history grows.
    db.execute("CREATE INDEX IF NOT EXISTS idx_requests_requester_history ON requests(requester_id, id DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_requests_helper_history ON requests(helper_id, id DESC)")
    if not getattr(db, "is_postgres", False):
        try: db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_tg ON users(tg_user_id) WHERE tg_user_id IS NOT NULL")
        except sqlite3.IntegrityError:
            pass
    if ADMIN_TELEGRAM_IDS:
        for telegram_id in ADMIN_TELEGRAM_IDS:
            db.execute("UPDATE users SET role='admin' WHERE tg_user_id=?", (telegram_id,))
    sync_legacy_subscriptions()

def sync_legacy_subscriptions():
    """Mirror legacy entitlement dates into the subscription ledger once."""
    now = datetime.now(timezone.utc).isoformat()
    for field, plan in (("pro_until", "pro"), ("business_until", "business")):
        rows = db.execute(f"SELECT user_id,created_at,{field} ends_at FROM users WHERE {field} IS NOT NULL").fetchall()
        for row in rows:
            exists = db.execute("SELECT 1 FROM subscriptions WHERE user_id=? AND plan=? AND ends_at=? LIMIT 1", (row["user_id"], plan, row["ends_at"])).fetchone()
            if not exists:
                state = "active" if row["ends_at"] > now else "expired"
                db.execute("INSERT INTO subscriptions(user_id,plan,status,starts_at,ends_at,provider) VALUES(?,?,?,?,?,?)", (row["user_id"], plan, state, row["created_at"], row["ends_at"], "legacy"))

def get_user(user_id):
    return db.execute("SELECT * FROM users WHERE user_id=?",(user_id,)).fetchone()
def get_user_by_email(email):
    return db.execute("SELECT * FROM users WHERE lower(email)=lower(?)",(email,)).fetchone()
def get_user_by_tg(tg_user_id):
    return db.execute("SELECT * FROM users WHERE tg_user_id=?",(tg_user_id,)).fetchone()

def delete_user_account(user_id):
    """Permanently erase an account and data that can identify or authenticate it."""
    db.execute("BEGIN IMMEDIATE")
    try:
        # A deleted helper must no longer be assigned to another person's request.
        db.execute("UPDATE requests SET helper_id=NULL, status=CASE WHEN status IN ('assigned','in_progress') THEN 'open' ELSE status END WHERE helper_id=?", (user_id,))
        db.execute("DELETE FROM admin_audit_log WHERE admin_user_id=? OR target_user_id=?", (user_id, user_id))
        db.execute("UPDATE identity_verification_requests SET reviewer_id=NULL WHERE reviewer_id=?", (user_id,))
        db.execute("DELETE FROM chats WHERE user_a_id=? OR user_b_id=?", (user_id, user_id))
        db.execute("DELETE FROM chat_messages WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM requests WHERE requester_id=?", (user_id,))
        db.execute("DELETE FROM helper_queue WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM request_candidates WHERE candidate_id=?", (user_id,))
        db.execute("DELETE FROM favorites WHERE user_id=? OR favorite_user_id=?", (user_id, user_id))
        db.execute("DELETE FROM ads WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM commercial_orders WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM subscriptions WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM billing_events WHERE invoice_id IN (SELECT id FROM billing_invoices WHERE user_id=?)", (user_id,))
        db.execute("DELETE FROM billing_invoices WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM web_login_tickets WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM telegram_auth_tickets WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM email_verification_codes WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM users WHERE user_id=?", (user_id,))
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

def insert_id(sql, params=()):
    """Insert a row and return its generated numeric id on both supported engines."""
    if getattr(db, "is_postgres", False):
        row = db.execute(sql.rstrip() + " RETURNING id", params).fetchone()
        return row["id"]
    return db.execute(sql, params).lastrowid

def create_web_login_ticket(user_id, token):
    token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()
    now=datetime.now(timezone.utc).isoformat()
    db.execute("DELETE FROM web_login_tickets WHERE expires_at<=?",(now,))
    db.execute("INSERT INTO web_login_tickets(token_hash,user_id,expires_at) VALUES(?,?,?)",(token_hash,user_id,expires))

def consume_web_login_ticket(token):
    if not token: return None
    token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest()
    now=datetime.now(timezone.utc).isoformat()
    db.execute("BEGIN IMMEDIATE")
    try:
        row=db.execute("SELECT user_id FROM web_login_tickets WHERE token_hash=? AND expires_at>?",(token_hash,now)).fetchone()
        if not row:
            db.execute("ROLLBACK"); return None
        db.execute("DELETE FROM web_login_tickets WHERE token_hash=?",(token_hash,))
        db.execute("COMMIT")
        return row["user_id"]
    except Exception:
        db.execute("ROLLBACK")
        raise

def _ticket_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def create_telegram_auth_ticket(token):
    token_hash = _ticket_hash(token)
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(seconds=TELEGRAM_AUTH_TTL_SECONDS)).isoformat()
    db.execute("DELETE FROM telegram_auth_tickets WHERE expires_at<=?", (now.isoformat(),))
    db.execute("INSERT INTO telegram_auth_tickets(token_hash,expires_at) VALUES(?,?)", (token_hash, expires))

def complete_telegram_auth_ticket(token, tg_user_id, name, username=None):
    """Bind a one-time browser ticket to the Telegram identity that opened it."""
    if not token:
        return False
    token_hash = _ticket_hash(token)
    now = datetime.now(timezone.utc).isoformat()
    db.execute("BEGIN IMMEDIATE")
    try:
        ticket = db.execute("SELECT user_id FROM telegram_auth_tickets WHERE token_hash=? AND expires_at>?", (token_hash, now)).fetchone()
        if not ticket or ticket["user_id"] is not None:
            db.execute("ROLLBACK")
            return False
        user = get_user_by_tg(tg_user_id) or get_user(tg_user_id)
        if user is None:
            create_user(tg_user_id, name[:50] or "Пользователь", username, tg_user_id=tg_user_id, web_verified=True)
        else:
            db.execute("UPDATE users SET tg_user_id=?,username=COALESCE(?,username),web_verified=1 WHERE user_id=?", (tg_user_id, username, user["user_id"]))
        db.execute("UPDATE telegram_auth_tickets SET user_id=? WHERE token_hash=? AND user_id IS NULL", (tg_user_id, token_hash))
        db.execute("COMMIT")
        return True
    except Exception:
        db.execute("ROLLBACK")
        raise

def consume_telegram_auth_ticket(token):
    if not token:
        return None
    token_hash = _ticket_hash(token)
    now = datetime.now(timezone.utc).isoformat()
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute("SELECT user_id FROM telegram_auth_tickets WHERE token_hash=? AND expires_at>?", (token_hash, now)).fetchone()
        if not row or row["user_id"] is None:
            db.execute("ROLLBACK")
            return None
        db.execute("DELETE FROM telegram_auth_tickets WHERE token_hash=?", (token_hash,))
        db.execute("COMMIT")
        return row["user_id"]
    except Exception:
        db.execute("ROLLBACK")
        raise

def _auth_subject(value):
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()

def auth_is_rate_limited(action, subject, limit):
    now = datetime.now(timezone.utc).isoformat()
    key = _auth_subject(subject)
    db.execute("DELETE FROM auth_attempts WHERE expires_at<=?", (now,))
    row = db.execute("SELECT attempts FROM auth_attempts WHERE action=? AND subject_hash=?", (action, key)).fetchone()
    return bool(row and row["attempts"] >= limit)

def record_auth_failure(action, subject):
    key = _auth_subject(subject)
    expires = (datetime.now(timezone.utc) + timedelta(seconds=AUTH_ATTEMPT_WINDOW_SECONDS)).isoformat()
    db.execute("""INSERT INTO auth_attempts(action,subject_hash,attempts,expires_at) VALUES(?,?,1,?)
        ON CONFLICT(action,subject_hash) DO UPDATE SET attempts=auth_attempts.attempts+1,expires_at=excluded.expires_at""", (action, key, expires))

def clear_auth_failures(action, subject):
    db.execute("DELETE FROM auth_attempts WHERE action=? AND subject_hash=?", (action, _auth_subject(subject)))

def reserve_auth_attempts(*entries):
    """Atomically reserve one or more attempts in the shared rate-limit window.

    A check followed by a separate increment allows parallel requests to pass
    the same limit. Reserving all relevant subjects in one short transaction
    makes password, reset and linking limits effective under concurrent load.
    Successful authentication clears its reservations immediately.
    """
    normalized = []
    for action, subject, limit in entries:
        action = str(action).strip()
        limit = int(limit)
        if not action or limit < 1:
            raise ValueError("invalid auth rate-limit reservation")
        normalized.append((action, _auth_subject(str(subject)), limit))
    now = datetime.now(timezone.utc)
    now_text = now.isoformat()
    expires = (now + timedelta(seconds=AUTH_ATTEMPT_WINDOW_SECONDS)).isoformat()
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM auth_attempts WHERE expires_at<=?", (now_text,))
        for action, subject_hash, limit in normalized:
            row = db.execute(
                "SELECT attempts FROM auth_attempts WHERE action=? AND subject_hash=?",
                (action, subject_hash),
            ).fetchone()
            if row and int(row["attempts"]) >= limit:
                db.execute("ROLLBACK")
                return False
        for action, subject_hash, _ in normalized:
            db.execute(
                """INSERT INTO auth_attempts(action,subject_hash,attempts,expires_at) VALUES(?,?,1,?)
                   ON CONFLICT(action,subject_hash) DO UPDATE SET
                     attempts=auth_attempts.attempts+1,expires_at=excluded.expires_at""",
                (action, subject_hash, expires),
            )
        db.execute("COMMIT")
        return True
    except Exception:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        raise

def _event_timestamp(value, required=True):
    raw = str(value or "").strip()
    if not raw:
        if required:
            raise ValueError("Укажите дату и время мероприятия.")
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Укажите корректную дату и время.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()

def create_community_event(creator_id, title, description, place, starts_at, ends_at=None, capacity=0, image_data=""):
    title = " ".join(str(title or "").split())
    description = str(description or "").strip()
    place = " ".join(str(place or "").split())
    if not 3 <= len(title) <= 120:
        raise ValueError("Название мероприятия должно быть от 3 до 120 символов.")
    if len(description) > 2000:
        raise ValueError("Описание не должно быть длиннее 2000 символов.")
    if not 2 <= len(place) <= 180:
        raise ValueError("Укажите место проведения.")
    start = _event_timestamp(starts_at)
    end = _event_timestamp(ends_at, required=False)
    current = datetime.now(timezone.utc)
    start_time = datetime.fromisoformat(start)
    if start_time <= current:
        raise ValueError("Время мероприятия должно быть в будущем.")
    if start_time > current + timedelta(days=366):
        raise ValueError("Мероприятие можно запланировать не более чем на год вперёд.")
    if end and datetime.fromisoformat(end) <= start_time:
        raise ValueError("Время окончания должно быть позже начала.")
    try:
        capacity = int(capacity or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Некорректное количество мест.") from exc
    if capacity and not 2 <= capacity <= 1000:
        raise ValueError("Количество мест — от 2 до 1000, либо оставьте поле пустым.")
    future_count = db.execute("SELECT COUNT(*) total FROM community_events WHERE creator_id=? AND status='published' AND starts_at>?", (creator_id, current.isoformat())).fetchone()["total"]
    if int(future_count) >= 20:
        raise ValueError("У вас уже слишком много запланированных мероприятий.")
    return insert_id("""INSERT INTO community_events(creator_id,title,description,place,starts_at,ends_at,capacity,image_data)
                      VALUES(?,?,?,?,?,?,?,?)""", (creator_id, title, description, place, start, end, capacity, image_data or ""))

def community_progress(days=30):
    """Return aggregate-only community metrics safe to display publicly."""
    days = max(7, min(int(days), 365))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    total = int(db.execute("SELECT COUNT(*) n FROM requests").fetchone()["n"] or 0)
    done = int(db.execute("SELECT COUNT(*) n FROM requests WHERE status=?", (STATUS_DONE,)).fetchone()["n"] or 0)
    active = int(db.execute("SELECT COUNT(*) n FROM requests WHERE status IN ('open','in_progress')").fetchone()["n"] or 0)
    counts = {row["category"]: int(row["n"] or 0) for row in db.execute(
        "SELECT category,COUNT(*) n FROM requests GROUP BY category"
    ).fetchall()}
    categories = [
        {"key": key, "title": title, "count": counts.get(key, 0)}
        for key, title in CATEGORIES.items()
    ]
    categories.sort(key=lambda item: (-item["count"], item["title"]))
    daily = db.execute(
        "SELECT substr(created_at,1,10) AS created_day,COUNT(*) n FROM requests WHERE created_at>=? GROUP BY substr(created_at,1,10) ORDER BY created_day",
        (since,),
    ).fetchall()
    rewards = int(db.execute("SELECT COALESCE(SUM(reward_rub),0) n FROM requests WHERE reward_rub>0").fetchone()["n"] or 0)
    leaders = db.execute("""SELECT u.user_id,u.name,u.city,COUNT(r.id) helped,
                                  AVG(r.requester_rating) rating,COUNT(r.requester_rating) reviews
                           FROM users u JOIN requests r ON r.helper_id=u.user_id
                           WHERE r.status=?
                           GROUP BY u.user_id,u.name,u.city
                           HAVING COUNT(r.id)>0
                           ORDER BY COUNT(r.id) DESC,COALESCE(AVG(r.requester_rating),0) DESC,u.user_id ASC
                           LIMIT 20""", (STATUS_DONE,)).fetchall()
    leaderboard = []
    for position, row in enumerate(leaders, 1):
        helped = int(row["helped"] or 0)
        rating = round(float(row["rating"]), 1) if row["rating"] is not None else None
        leaderboard.append({
            "position": position, "user_id": int(row["user_id"]), "name": row["name"],
            "city": row["city"] or "", "helped": helped, "rating": rating,
            "reviews": int(row["reviews"] or 0),
            "score": helped * 20 + int((rating or 0) * 10),
        })
    return {
        "summary": {"total": total, "done": done, "active": active, "rewards": rewards},
        "categories": categories, "daily": [dict(row) for row in daily], "period_days": days,
        "completion_percent": round(done / total * 100) if total else 0,
        "leaderboard": leaderboard,
    }

def community_profile(user_id):
    """Public community card: only reputation data, never contact or location data."""
    user = db.execute("SELECT user_id,name,city FROM users WHERE user_id=? AND is_blocked=0", (user_id,)).fetchone()
    if not user:
        return None
    stats = get_user_stats(user_id)
    reviews = db.execute("""SELECT * FROM (
          SELECT r.id,r.completed_at,r.requester_rating rating,r.requester_review review,
                 u.name reviewer_name,'За помощь' review_kind
          FROM requests r JOIN users u ON u.user_id=r.requester_id
          WHERE r.helper_id=? AND r.status=? AND r.requester_rating IS NOT NULL
          UNION ALL
          SELECT r.id,r.completed_at,r.helper_rating rating,r.helper_review review,
                 u.name reviewer_name,'Как заказчику' review_kind
          FROM requests r JOIN users u ON u.user_id=r.helper_id
          WHERE r.requester_id=? AND r.status=? AND r.helper_rating IS NOT NULL
        ) reputation ORDER BY completed_at DESC,id DESC LIMIT 30""", (user_id, STATUS_DONE, user_id, STATUS_DONE)).fetchall()
    return {
        "id": int(user["user_id"]), "name": user["name"], "city": user["city"] or "",
        "stats": stats,
        "reviews": [
            {"request_id": int(row["id"]), "title": "Завершённая заявка", "at": row["completed_at"],
             "rating": int(row["rating"]), "review": row["review"] or "",
             "reviewer_name": row["reviewer_name"], "kind": row["review_kind"]}
            for row in reviews
        ],
    }

def community_events_for_user(user_id, mine=False, limit=100):
    current = datetime.now(timezone.utc).isoformat()
    limit = max(1, min(int(limit), 100))
    if mine:
        where = "(e.creator_id=? OR EXISTS(SELECT 1 FROM event_participants mine WHERE mine.event_id=e.id AND mine.user_id=?))"
        args = (user_id, user_id, user_id, limit)
    else:
        where = "e.status='published' AND e.starts_at>?"
        args = (user_id, current, limit)
    return db.execute(f"""SELECT e.*,u.name creator_name,
        (SELECT COUNT(*) FROM event_participants p WHERE p.event_id=e.id) participant_count,
        CASE WHEN EXISTS(SELECT 1 FROM event_participants mine WHERE mine.event_id=e.id AND mine.user_id=?) THEN 1 ELSE 0 END joined
        FROM community_events e JOIN users u ON u.user_id=e.creator_id
        WHERE {where} ORDER BY CASE e.status WHEN 'published' THEN 0 ELSE 1 END,e.starts_at ASC LIMIT ?""", args).fetchall()

def join_community_event(event_id, user_id):
    current = datetime.now(timezone.utc).isoformat()
    db.execute("BEGIN IMMEDIATE")
    try:
        event = db.execute("SELECT * FROM community_events WHERE id=?", (event_id,)).fetchone()
        if not event or event["status"] != "published" or event["starts_at"] <= current:
            db.execute("ROLLBACK")
            return False, "Мероприятие уже недоступно."
        if event["creator_id"] == user_id:
            db.execute("ROLLBACK")
            return False, "Вы организатор этого мероприятия."
        exists = db.execute("SELECT 1 FROM event_participants WHERE event_id=? AND user_id=?", (event_id, user_id)).fetchone()
        if exists:
            db.execute("ROLLBACK")
            return True, "Вы уже участвуете."
        count = db.execute("SELECT COUNT(*) total FROM event_participants WHERE event_id=?", (event_id,)).fetchone()["total"]
        if event["capacity"] and int(count) >= int(event["capacity"]):
            db.execute("ROLLBACK")
            return False, "Свободных мест уже нет."
        db.execute("INSERT INTO event_participants(event_id,user_id) VALUES(?,?)", (event_id, user_id))
        db.execute("COMMIT")
        return True, "Вы участвуете в мероприятии."
    except Exception:
        db.execute("ROLLBACK")
        raise

def leave_community_event(event_id, user_id):
    event = db.execute("SELECT creator_id,status FROM community_events WHERE id=?", (event_id,)).fetchone()
    if not event or event["status"] != "published":
        return False, "Мероприятие уже недоступно."
    if event["creator_id"] == user_id:
        return False, "Организатор не может выйти из собственного мероприятия."
    changed = db.execute("DELETE FROM event_participants WHERE event_id=? AND user_id=?", (event_id, user_id)).rowcount
    return (True, "Участие отменено.") if changed else (False, "Вы не записаны на это мероприятие.")

def cancel_community_event(event_id, user_id, allow_admin=False):
    event = db.execute("SELECT creator_id,status FROM community_events WHERE id=?", (event_id,)).fetchone()
    if not event:
        return False, "Мероприятие не найдено."
    if event["creator_id"] != user_id and not allow_admin:
        return False, "Отменить мероприятие может только организатор."
    if event["status"] != "published":
        return False, "Мероприятие уже отменено."
    db.execute("UPDATE community_events SET status='cancelled' WHERE id=?", (event_id,))
    return True, "Мероприятие отменено."

def _email_code_hash(code):
    return hashlib.sha256(code.encode("utf-8")).hexdigest()

def create_email_verification_code(user_id):
    """Replace any previous code and return a short, one-time email code."""
    code = f"{secrets.randbelow(900_000) + 100_000:06d}"
    expires = (datetime.now(timezone.utc) + timedelta(seconds=EMAIL_VERIFICATION_TTL_SECONDS)).isoformat()
    db.execute("DELETE FROM email_verification_codes WHERE user_id=? OR expires_at<=?", (user_id, datetime.now(timezone.utc).isoformat()))
    db.execute("INSERT INTO email_verification_codes(user_id,code_hash,expires_at) VALUES(?,?,?)", (user_id, _email_code_hash(code), expires))
    return code

def verify_email_code(user_id, code, max_attempts=5):
    """Consume an email verification code atomically. Raw codes are never stored."""
    now = datetime.now(timezone.utc).isoformat()
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute("SELECT code_hash,expires_at,attempts FROM email_verification_codes WHERE user_id=?", (user_id,)).fetchone()
        if not row or row["expires_at"] <= now:
            db.execute("DELETE FROM email_verification_codes WHERE user_id=?", (user_id,))
            db.execute("COMMIT")
            return False, "expired"
        if row["attempts"] >= max_attempts:
            db.execute("DELETE FROM email_verification_codes WHERE user_id=?", (user_id,))
            db.execute("COMMIT")
            return False, "too_many_attempts"
        if not isinstance(code, str) or not re.fullmatch(r"\d{6}", code) or not secrets.compare_digest(row["code_hash"], _email_code_hash(code)):
            attempts = int(row["attempts"]) + 1
            if attempts >= max_attempts:
                db.execute("DELETE FROM email_verification_codes WHERE user_id=?", (user_id,))
                result = "too_many_attempts"
            else:
                db.execute("UPDATE email_verification_codes SET attempts=? WHERE user_id=?", (attempts, user_id))
                result = "invalid"
            db.execute("COMMIT")
            return False, result
        db.execute("UPDATE users SET email_verified=1 WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM email_verification_codes WHERE user_id=?", (user_id,))
        db.execute("COMMIT")
        return True, "verified"
    except Exception:
        db.execute("ROLLBACK")
        raise

def normalize_phone(phone):
    """Return one canonical E.164 number or None without guessing a country."""
    value = re.sub(r"[\s()\-.]", "", str(phone or ""))
    if re.fullmatch(r"8\d{10}", value):
        value = "+7" + value[1:]
    elif re.fullmatch(r"7\d{10}", value):
        value = "+" + value
    if not re.fullmatch(r"\+[1-9]\d{9,14}", value):
        return None
    return value

def update_contact_details(user_id, full_name, birth_date, phone):
    """Store profile data; replacing a phone invalidates its previous check."""
    name = " ".join(str(full_name or "").split())
    if not 2 <= len(name) <= 120:
        return False, "Укажите имя от 2 до 120 символов."
    try:
        born = datetime.strptime(str(birth_date or ""), "%Y-%m-%d").date()
    except ValueError:
        return False, "Укажите корректную дату рождения."
    today = datetime.now(timezone.utc).date()
    if born > today or born.year < today.year - 120:
        return False, "Укажите корректную дату рождения."
    normalized = normalize_phone(phone)
    if not normalized:
        return False, "Введите телефон в международном формате, например +7 999 123-45-67."
    current = get_user(user_id)
    if not current:
        return False, "Профиль не найден."
    changed_phone = current["phone"] != normalized
    db.execute("UPDATE users SET full_name=?,birth_date=?,phone=?,phone_verified=CASE WHEN ? THEN 0 ELSE phone_verified END WHERE user_id=?",
               (name, born.isoformat(), normalized, int(changed_phone), user_id))
    if changed_phone:
        db.execute("DELETE FROM phone_verification_codes WHERE user_id=?", (user_id,))
    return True, "saved"

def create_phone_verification_code(user_id):
    user = get_user(user_id)
    if not user or not user["phone"]:
        return None
    code = f"{secrets.randbelow(900_000) + 100_000:06d}"
    expires = (datetime.now(timezone.utc) + timedelta(seconds=PHONE_VERIFICATION_TTL_SECONDS)).isoformat()
    db.execute("DELETE FROM phone_verification_codes WHERE user_id=? OR expires_at<=?", (user_id, datetime.now(timezone.utc).isoformat()))
    db.execute("INSERT INTO phone_verification_codes(user_id,phone,code_hash,expires_at) VALUES(?,?,?,?)", (user_id, user["phone"], _email_code_hash(code), expires))
    return code

def verify_phone_code(user_id, code, max_attempts=5):
    """Consume a phone code atomically and only verify the currently stored number."""
    current_time = datetime.now(timezone.utc).isoformat()
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute("SELECT phone,code_hash,expires_at,attempts FROM phone_verification_codes WHERE user_id=?", (user_id,)).fetchone()
        user = get_user(user_id)
        if not row or not user or row["expires_at"] <= current_time or row["phone"] != user["phone"]:
            db.execute("DELETE FROM phone_verification_codes WHERE user_id=?", (user_id,))
            db.execute("COMMIT")
            return False, "expired"
        if row["attempts"] >= max_attempts:
            db.execute("DELETE FROM phone_verification_codes WHERE user_id=?", (user_id,))
            db.execute("COMMIT")
            return False, "too_many_attempts"
        valid = isinstance(code, str) and bool(re.fullmatch(r"\d{6}", code)) and secrets.compare_digest(row["code_hash"], _email_code_hash(code))
        if not valid:
            attempts = int(row["attempts"]) + 1
            if attempts >= max_attempts:
                db.execute("DELETE FROM phone_verification_codes WHERE user_id=?", (user_id,))
                result = "too_many_attempts"
            else:
                db.execute("UPDATE phone_verification_codes SET attempts=? WHERE user_id=?", (attempts, user_id))
                result = "invalid"
            db.execute("COMMIT")
            return False, result
        db.execute("UPDATE users SET phone_verified=1 WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM phone_verification_codes WHERE user_id=?", (user_id,))
        db.execute("COMMIT")
        return True, "verified"
    except Exception:
        db.execute("ROLLBACK")
        raise

def create_user(user_id,name,username=None,email=None,password_hash=None,tg_user_id=None,web_verified=False):
    # Telegram registrations use the Telegram id as both the primary user id
    # and the linked Telegram identity. Web accounts are created separately
    # by create_web_user().
    actual_tg_id = user_id if tg_user_id is None else tg_user_id
    role = "admin" if actual_tg_id in ADMIN_TELEGRAM_IDS else "user"
    db.execute("""INSERT OR IGNORE INTO users(user_id,name,username,email,password_hash,balance,helper_categories,tg_user_id,web_verified,email_verified,role)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(user_id,name,username,email,password_hash,START_BALANCE,"",actual_tg_id,int(web_verified),0,role))
    return get_user(user_id)
def create_web_user(name,email,password_hash):
    row=db.execute("SELECT COALESCE(MIN(user_id),0) m FROM users").fetchone()
    uid=min(-1, int(row["m"])-1)
    db.execute("""INSERT INTO users(user_id,name,email,password_hash,balance,helper_categories,web_verified,email_verified)
                  VALUES(?,?,?,?,?,?,0,0)""",(uid,name,email,password_hash,START_BALANCE,""))
    return uid

def detach_telegram_to_web_profile(user_id):
    """Split a linked Telegram account into an independent website profile.

    Website data and active sessions move to a new negative id; the former
    Telegram id stays as a clean bot profile.  This is reversible by linking
    the profiles again with a new code.
    """
    source = get_user(user_id)
    if not source or not source["tg_user_id"]:
        return None
    telegram_id = source["tg_user_id"]
    row = db.execute("SELECT COALESCE(MIN(user_id),0) m FROM users").fetchone()
    web_id = min(-1, int(row["m"]) - 1)
    db.execute("BEGIN IMMEDIATE")
    try:
        # Email is unique and must move from the Telegram row before the
        # independent website record can be inserted.
        db.execute("UPDATE users SET email=NULL WHERE user_id=?", (user_id,))
        db.execute("""INSERT INTO users(user_id,name,username,email,password_hash,balance,helper_categories,created_at,
                   pro_until,verified_until,business_until,favorite_slots,web_verified,email_verified,full_name,birth_date,phone,phone_verified,lat,lon,city,bio,role,is_blocked,blocked_reason)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (web_id,source["name"],None,source["email"],source["password_hash"],source["balance"],source["helper_categories"],source["created_at"],
                    source["pro_until"],source["verified_until"],source["business_until"],source["favorite_slots"],0,source["email_verified"],source["full_name"],source["birth_date"],source["phone"],source["phone_verified"],source["lat"],source["lon"],source["city"],source["bio"],source["role"],source["is_blocked"],source["blocked_reason"]))
        db.execute("UPDATE users SET helper_availability=? WHERE user_id=?",(source["helper_availability"] or "",web_id))
        for table, column in [
            ("requests","requester_id"),("requests","helper_id"),("helper_queue","user_id"),
            ("billing_invoices","user_id"),("subscriptions","user_id"),("web_login_tickets","user_id"),
            ("email_verification_codes","user_id"),("phone_verification_codes","user_id"),
            ("ai_usage","user_id"),("ads","user_id"),("commercial_orders","user_id"),("community_events","creator_id"),("event_participants","user_id"),
            ("chats","user_a_id"),("chats","user_b_id"),("chat_messages","user_id"),
            ("request_candidates","candidate_id"),("sessions","user_id"),
            ("admin_audit_log","admin_user_id"),("admin_audit_log","target_user_id")]:
            db.execute(f"UPDATE {table} SET {column}=? WHERE {column}=?", (web_id, user_id))
        db.execute("UPDATE favorites SET user_id=? WHERE user_id=?", (web_id, user_id))
        db.execute("UPDATE favorites SET favorite_user_id=? WHERE favorite_user_id=?", (web_id, user_id))
        db.execute("UPDATE identity_verification_requests SET user_id=? WHERE user_id=?", (web_id, user_id))
        db.execute("UPDATE identity_verification_requests SET reviewer_id=? WHERE reviewer_id=?", (web_id, user_id))
        # Keep the Telegram primary id available for a fresh, isolated bot profile.
        db.execute("""UPDATE users SET email=NULL,password_hash=NULL,balance=?,helper_categories='',pro_until=NULL,
                    verified_until=NULL,business_until=NULL,favorite_slots=3,web_verified=1,verification_code=NULL,verification_code_hash=NULL,
                   verification_code_expires_at=NULL,email_verified=0,full_name='',birth_date=NULL,phone=NULL,phone_verified=0,lat=NULL,lon=NULL,city='',bio='',tg_user_id=? WHERE user_id=?""",
                   (START_BALANCE, telegram_id, user_id))
        db.execute("COMMIT")
        return web_id
    except Exception:
        db.execute("ROLLBACK")
        raise

def create_link_code(user_id):
    # This code authorizes merging a Telegram identity into a web account.
    # Use 128 bits of entropy and retain only a hash at rest; a database leak
    # must not become an account-linking capability.
    code=secrets.token_hex(16).upper()
    expires=(datetime.now(timezone.utc)+timedelta(seconds=TELEGRAM_LINK_TTL_SECONDS)).isoformat()
    db.execute("UPDATE users SET verification_code=NULL,verification_code_hash=?,verification_code_expires_at=? WHERE user_id=?",(_ticket_hash(code),expires,user_id))
    return code

def is_user_blocked(user_id):
    user = get_user(user_id)
    return bool(user and user["is_blocked"])

def touch_user_activity(user_id, seen_at=None):
    """Record recent web activity without writing on every sync request."""
    user = get_user(user_id)
    if not user:
        return
    current = user["last_seen_at"]
    observed = seen_at or datetime.now(timezone.utc)
    # A five minute granularity keeps the activity view useful while avoiding a
    # write on each client-side sync tick.
    cutoff = (observed - timedelta(minutes=5)).isoformat()
    if current and str(current) >= cutoff:
        return
    db.execute("UPDATE users SET last_seen_at=? WHERE user_id=?", (observed.isoformat(), user_id))

def set_user_blocked(admin_user_id, target_user_id, blocked, reason=""):
    admin = get_user(admin_user_id)
    if not admin or admin["role"] != "admin":
        return False
    changed = db.execute("UPDATE users SET is_blocked=?, blocked_reason=? WHERE user_id=?", (int(blocked), reason[:300] if blocked else None, target_user_id)).rowcount
    if changed:
        db.execute("INSERT INTO admin_audit_log(admin_user_id,action,target_user_id,details) VALUES(?,?,?,?)", (admin_user_id, "block" if blocked else "unblock", target_user_id, json.dumps({"reason": reason[:300]} if blocked and reason else {}, ensure_ascii=False)))
    return changed == 1

def get_identity_verification(user_id):
    return db.execute("SELECT * FROM identity_verification_requests WHERE user_id=?", (user_id,)).fetchone()

def request_identity_verification(user_id):
    """Queue a manual identity review after the owner has linked Telegram.

    Linking Telegram proves control of the Telegram account; it does not by
    itself prove a person's identity.  Keeping the two states separate avoids
    issuing a misleading verification badge.
    """
    user = get_user(user_id)
    if not user:
        return False, "user_not_found"
    if not user["tg_user_id"]:
        return False, "telegram_required"
    current = get_identity_verification(user_id)
    if current and current["status"] == "approved":
        return True, "approved"
    db.execute("""INSERT INTO identity_verification_requests(user_id,status,submitted_at,reviewed_at,reviewer_id,note)
                  VALUES(?,'pending',CURRENT_TIMESTAMP,NULL,NULL,'')
                  ON CONFLICT(user_id) DO UPDATE SET
                    status='pending', submitted_at=CURRENT_TIMESTAMP,
                    reviewed_at=NULL, reviewer_id=NULL, note=''""", (user_id,))
    return True, "pending"

def pending_identity_verifications(limit=20):
    return db.execute("""SELECT v.*,u.name,u.username,u.tg_user_id
                         FROM identity_verification_requests v
                         JOIN users u ON u.user_id=v.user_id
                         WHERE v.status='pending'
                         ORDER BY v.submitted_at ASC LIMIT ?""", (limit,)).fetchall()

def review_identity_verification(admin_user_id, target_user_id, approved, note=""):
    admin = get_user(admin_user_id)
    if not admin or admin["role"] != "admin":
        return False, "forbidden"
    request = get_identity_verification(target_user_id)
    if not request or request["status"] != "pending":
        return False, "not_pending"
    status = "approved" if approved else "rejected"
    clean_note = str(note or "").strip()[:500]
    db.execute("""UPDATE identity_verification_requests
                  SET status=?, reviewed_at=CURRENT_TIMESTAMP, reviewer_id=?, note=?
                  WHERE user_id=?""", (status, admin_user_id, clean_note, target_user_id))
    if approved:
        until = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
        db.execute("UPDATE users SET verified_until=? WHERE user_id=?", (until, target_user_id))
    db.execute("INSERT INTO admin_audit_log(admin_user_id,action,target_user_id,details) VALUES(?,?,?,?)",
               (admin_user_id, "identity_approved" if approved else "identity_rejected", target_user_id,
                json.dumps({"note": clean_note}, ensure_ascii=False)))
    return True, status

def admin_summary():
    users = db.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
    blocked = db.execute("SELECT COUNT(*) n FROM users WHERE is_blocked=1").fetchone()["n"]
    requests = db.execute("SELECT status,COUNT(*) n FROM requests GROUP BY status").fetchall()
    invoices = db.execute("SELECT status,COUNT(*) n FROM billing_invoices GROUP BY status").fetchall()
    return {"users": users, "blocked_users": blocked, "requests": {r["status"]: r["n"] for r in requests}, "invoices": {r["status"]: r["n"] for r in invoices}}

def _as_utc_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)

def _date_key(value):
    parsed = _as_utc_datetime(value)
    return parsed.date().isoformat() if parsed else None

def record_admin_action(admin_user_id, action, target_user_id=None, details=None):
    db.execute(
        "INSERT INTO admin_audit_log(admin_user_id,action,target_user_id,details) VALUES(?,?,?,?)",
        (admin_user_id, action[:80], target_user_id, json.dumps(details or {}, ensure_ascii=False)),
    )

def admin_cancel_request(admin_user_id, request_id, reason=""):
    """Cancel only unfinished requests and leave an auditable operator trail."""
    admin = get_user(admin_user_id)
    request = get_request(request_id)
    if not admin or admin["role"] != "admin" or not request:
        return False, None
    if request["status"] not in (STATUS_OPEN, STATUS_IN_PROGRESS):
        return False, request
    clean_reason = str(reason).strip()[:300] or "Заявка закрыта поддержкой"
    changed = db.execute(
        "UPDATE requests SET status='cancelled',cancel_reason=?,cancelled_at=CURRENT_TIMESTAMP WHERE id=? AND status IN (?,?)",
        (clean_reason, request_id, STATUS_OPEN, STATUS_IN_PROGRESS),
    ).rowcount
    if not changed:
        return False, get_request(request_id)
    if request["reward_payment_status"] == "paid" and int(request["reward_rub"] or 0) > 0:
        amount = int(request["reward_rub"])
        wallet_add_entry(request["requester_id"], amount, "reward_refund", "Вознаграждение возвращено в кошелёк: заявка закрыта поддержкой", f"request:{request_id}:admin-refund", request_id)
        db.execute("UPDATE requests SET reward_payment_status='wallet_refunded' WHERE id=?", (request_id,))
    db.execute(
        "INSERT INTO request_events(request_id,actor_id,event_type,message) VALUES(?,?,?,?)",
        (request_id, admin_user_id, "admin_cancelled", f"Заявка закрыта поддержкой. Причина: {clean_reason}"),
    )
    record_admin_action(admin_user_id, "request_cancelled", request["requester_id"], {"request_id": request_id, "reason": str(reason).strip()[:300]})
    return True, request

def admin_dashboard(days=14, user_limit=100, user_query=""):
    """Return privacy conscious operational data for an authenticated admin."""
    days = max(7, min(int(days), 30))
    user_limit = max(1, min(int(user_limit), 200))
    now_utc = datetime.now(timezone.utc)
    labels = [(now_utc.date() - timedelta(days=offset)).isoformat() for offset in range(days - 1, -1, -1)]
    series = {label: {"date": label, "users": 0, "requests": 0, "support": 0} for label in labels}

    all_users = db.execute("SELECT user_id,created_at,last_seen_at,is_blocked FROM users").fetchall()
    all_requests = db.execute("SELECT created_at,status,views FROM requests").fetchall()
    all_tickets = db.execute("SELECT created_at,status FROM support_tickets").fetchall()
    for row in all_users:
        day = _date_key(row["created_at"])
        if day in series:
            series[day]["users"] += 1
    for row in all_requests:
        day = _date_key(row["created_at"])
        if day in series:
            series[day]["requests"] += 1
    for row in all_tickets:
        day = _date_key(row["created_at"])
        if day in series:
            series[day]["support"] += 1

    active_24h = active_7d = 0
    for row in all_users:
        seen = _as_utc_datetime(row["last_seen_at"])
        if seen and seen >= now_utc - timedelta(days=7):
            active_7d += 1
            if seen >= now_utc - timedelta(hours=24):
                active_24h += 1
    request_counts = {}
    views_total = 0
    for row in all_requests:
        request_counts[row["status"]] = request_counts.get(row["status"], 0) + 1
        views_total += int(row["views"] or 0)
    support_counts = {}
    for row in all_tickets:
        support_counts[row["status"]] = support_counts.get(row["status"], 0) + 1

    query = str(user_query or "").strip().lower()[:80]
    params = []
    where = ""
    if query:
        where = "WHERE lower(u.name) LIKE ? OR lower(COALESCE(u.email,'')) LIKE ?"
        like = f"%{query}%"
        params.extend((like, like))
    params.append(user_limit)
    users = db.execute(f"""SELECT u.user_id,u.name,u.email,u.city,u.created_at,u.last_seen_at,u.role,u.is_blocked,u.blocked_reason,
               u.tg_user_id,u.email_verified,
               (SELECT COUNT(*) FROM requests r WHERE r.requester_id=u.user_id OR r.helper_id=u.user_id) request_count,
               (SELECT COUNT(*) FROM requests r WHERE (r.requester_id=u.user_id OR r.helper_id=u.user_id) AND r.status IN ('open','in_progress')) active_request_count,
               (SELECT COUNT(*) FROM support_tickets t WHERE t.user_id=u.user_id AND t.status='open') open_support_count
          FROM users u {where}
         ORDER BY CASE WHEN u.last_seen_at IS NULL THEN 1 ELSE 0 END,u.last_seen_at DESC,u.created_at DESC LIMIT ?""", tuple(params)).fetchall()
    user_payloads = [{
        "id": row["user_id"], "name": row["name"], "email": row["email"] or "", "city": row["city"] or "",
        "created_at": row["created_at"], "last_seen_at": row["last_seen_at"], "role": row["role"],
        "blocked": bool(row["is_blocked"]), "blocked_reason": row["blocked_reason"] or "",
        "telegram_linked": bool(row["tg_user_id"]), "email_verified": bool(row["email_verified"]),
        "request_count": int(row["request_count"] or 0), "active_request_count": int(row["active_request_count"] or 0),
        "open_support_count": int(row["open_support_count"] or 0),
    } for row in users]

    activities = []
    for row in db.execute("""SELECT r.id,r.what,r.status,r.created_at,u.name
                             FROM requests r JOIN users u ON u.user_id=r.requester_id
                             ORDER BY r.created_at DESC LIMIT 20""").fetchall():
        activities.append({"kind": "request", "target_id": row["id"], "status": row["status"], "at": row["created_at"], "title": f"Заявка #{row['id']}: {row['what'][:90]}", "meta": f"{row['name']} · {row['status']}"})
    for row in db.execute("""SELECT t.id,t.subject,t.status,t.created_at,u.name
                             FROM support_tickets t JOIN users u ON u.user_id=t.user_id
                             ORDER BY t.created_at DESC LIMIT 20""").fetchall():
        activities.append({"kind": "support", "target_id": row["id"], "status": row["status"], "at": row["created_at"], "title": f"Поддержка #{row['id']}: {row['subject'][:90]}", "meta": f"{row['name']} · {row['status']}"})
    activities.sort(key=lambda item: str(item["at"]), reverse=True)

    tickets = db.execute("""SELECT t.*,u.name user_name,u.email user_email
                            FROM support_tickets t JOIN users u ON u.user_id=t.user_id
                            ORDER BY CASE t.status WHEN 'open' THEN 0 ELSE 1 END,t.id DESC LIMIT 100""").fetchall()
    return {
        "summary": {
            "users": len(all_users), "active_24h": active_24h, "active_7d": active_7d,
            "new_7d": sum(point["users"] for point in list(series.values())[-7:]),
            "blocked_users": sum(1 for row in all_users if row["is_blocked"]),
            "requests": request_counts, "support": support_counts, "views_total": views_total,
        },
        "series": list(series.values()), "users": user_payloads,
        "tickets": [dict(row) for row in tickets], "activities": activities[:30],
    }

def consume_ai_quota(user_id, token_count, max_requests, max_tokens):
    """Reserve AI quota atomically before a future AI provider call."""
    if token_count < 0:
        return False
    period = datetime.now(timezone.utc).date().isoformat()
    cur = db.execute("""INSERT INTO ai_usage(user_id,request_count,token_count,period_start)
        VALUES(?,1,?,?)
        ON CONFLICT(user_id,period_start) DO UPDATE SET
        request_count=ai_usage.request_count+1, token_count=ai_usage.token_count+excluded.token_count,
        updated_at=CURRENT_TIMESTAMP
        WHERE ai_usage.request_count < ? AND ai_usage.token_count + excluded.token_count <= ?""",
        (user_id, token_count, period, max_requests, max_tokens))
    return cur.rowcount == 1
def link_telegram(user_id,tg_user_id,username=None):
    db.execute("UPDATE users SET tg_user_id=?, username=COALESCE(?,username), web_verified=1, verification_code=NULL, verification_code_hash=NULL, verification_code_expires_at=NULL WHERE user_id=?",(tg_user_id,username,user_id))
def get_request(request_id): return db.execute("SELECT * FROM requests WHERE id=?",(request_id,)).fetchone()
def get_or_create_chat_for_request(request_id):
    """Return the one chat for an assigned request, safely under races."""
    request=get_request(request_id)
    if not request or not request["helper_id"]:
        return None
    db.execute("INSERT OR IGNORE INTO chats(request_id,user_a_id,user_b_id) VALUES(?,?,?)",
               (request_id,request["requester_id"],request["helper_id"]))
    row=db.execute("SELECT id FROM chats WHERE request_id=?",(request_id,)).fetchone()
    return row["id"] if row else None
def get_active_own_request(uid): return db.execute("SELECT * FROM requests WHERE requester_id=? AND status IN (?,?) ORDER BY id DESC LIMIT 1",(uid,STATUS_OPEN,STATUS_IN_PROGRESS)).fetchone()
def get_active_help(uid): return db.execute("SELECT * FROM requests WHERE helper_id=? AND status=? ORDER BY id DESC LIMIT 1",(uid,STATUS_IN_PROGRESS)).fetchone()
def get_unrated_request(uid): return db.execute("SELECT * FROM requests WHERE requester_id=? AND status=? AND requester_rating IS NULL ORDER BY id DESC LIMIT 1",(uid,STATUS_DONE)).fetchone()
def get_unrated_help(uid): return db.execute("SELECT * FROM requests WHERE helper_id=? AND status=? AND helper_rating IS NULL ORDER BY id DESC LIMIT 1",(uid,STATUS_DONE)).fetchone()
def get_history(uid,limit=20): return db.execute("SELECT * FROM requests WHERE requester_id=? OR helper_id=? ORDER BY id DESC LIMIT ?",(uid,uid,limit)).fetchall()
def get_user_stats(uid):
    a=db.execute("SELECT COUNT(*) n,AVG(requester_rating) avg FROM requests WHERE helper_id=? AND status=?",(uid,STATUS_DONE)).fetchone()
    b=db.execute("SELECT COUNT(*) n,AVG(helper_rating) avg FROM requests WHERE requester_id=? AND status=?",(uid,STATUS_DONE)).fetchone()
    return {"helped":a["n"] or 0,"helped_avg":float(a["avg"]) if a["avg"] is not None else None,
            "received":b["n"] or 0,"received_avg":float(b["avg"]) if b["avg"] is not None else None}
def save_request_candidates(request_id, candidates):
    for candidate in candidates:
        db.execute(
            """INSERT INTO request_candidates(request_id,candidate_id,score,status,seen_at,updated_at)
               VALUES(?,?,?,'pending',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
               ON CONFLICT(request_id,candidate_id) DO UPDATE SET
                 score=excluded.score, updated_at=CURRENT_TIMESTAMP""",
            (request_id, candidate["user_id"], candidate["score"]),
        )

def get_request_candidates(request_id, limit=20):
    return db.execute(
        """SELECT rc.*, u.name, u.username, u.lat, u.lon, u.bio, u.tg_user_id
           FROM request_candidates rc
           JOIN users u ON u.user_id=rc.candidate_id
           WHERE rc.request_id=? AND rc.status='pending'
           ORDER BY rc.score DESC, rc.updated_at DESC LIMIT ?""",
        (request_id, limit),
    ).fetchall()

def get_invoice(invoice_id): return db.execute("SELECT * FROM billing_invoices WHERE id=?",(invoice_id,)).fetchone()
def get_invoice_by_payload(payload): return db.execute("SELECT * FROM billing_invoices WHERE payload=?",(payload,)).fetchone()
def record_billing_event(invoice_id,event_type,provider_event_id=None,payload="{}"):
    db.execute("INSERT OR IGNORE INTO billing_events(invoice_id,event_type,provider_event_id,payload) VALUES(?,?,?,?)",(invoice_id,event_type,provider_event_id,payload))
def get_billing_history(uid,limit=20): return db.execute("SELECT * FROM billing_invoices WHERE user_id=? ORDER BY id DESC LIMIT ?",(uid,limit)).fetchall()

def wallet_add_entry(user_id, amount_rub, kind, description, reference, request_id=None, invoice_id=None):
    """Append an idempotent RUB wallet ledger entry. Amounts are integer kopeck-free RUB."""
    amount = int(amount_rub)
    if not amount:
        return False
    result = db.execute(
        """INSERT OR IGNORE INTO wallet_transactions
           (user_id,amount_rub,kind,description,request_id,invoice_id,reference)
           VALUES(?,?,?,?,?,?,?)""",
        (user_id, amount, str(kind)[:64], str(description)[:300], request_id, invoice_id, str(reference)[:160]),
    )
    return bool(getattr(result, "rowcount", 0))

def wallet_summary(user_id, limit=50):
    balance = db.execute(
        "SELECT COALESCE(SUM(amount_rub),0) amount FROM wallet_transactions WHERE user_id=?", (user_id,)
    ).fetchone()["amount"]
    reserved = db.execute(
        """SELECT COALESCE(SUM(reward_rub),0) amount FROM requests
           WHERE requester_id=? AND reward_payment_status='paid' AND status IN (?,?)""",
        (user_id, STATUS_OPEN, STATUS_IN_PROGRESS),
    ).fetchone()["amount"]
    incoming = db.execute(
        """SELECT COALESCE(SUM(reward_rub),0) amount FROM requests
           WHERE helper_id=? AND reward_payment_status='paid' AND status=?""",
        (user_id, STATUS_IN_PROGRESS),
    ).fetchone()["amount"]
    rows = db.execute(
        "SELECT amount_rub,kind,description,request_id,invoice_id,created_at FROM wallet_transactions WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return {"balance_rub": int(balance or 0), "reserved_rub": int(reserved or 0), "incoming_rub": int(incoming or 0), "transactions": [dict(row) for row in rows]}

def link_by_code(code,tg_user_id,username=None):
    """Link a Telegram identity to the existing web account and merge prior activity.

    Both clients use the same users/requests tables. If Telegram was used before
    linking, that Telegram-only account is merged into the web account instead of
    being rejected or leaving two separate histories. The Telegram user id is kept
    as the canonical user_id because Telegram handlers address users by that id.
    """
    code = str(code or "").strip().upper()
    if not re.fullmatch(r"(?:[A-F0-9]{8}|[A-F0-9]{32})", code):
        return False,"Код не найден или уже использован."
    if not reserve_auth_attempts(("telegram_link", str(tg_user_id), AUTH_ATTEMPT_LIMIT)):
        return False,"Слишком много попыток. Повторите через 15 минут."
    now=datetime.now(timezone.utc).isoformat()
    # ``verification_code`` is retained only as a short migration bridge for
    # codes issued before this update. Every newly issued code is hashed.
    row=db.execute("SELECT * FROM users WHERE (verification_code_hash=? OR verification_code=?) AND verification_code_expires_at>?",(_ticket_hash(code),code,now)).fetchone()
    if not row:
        return False,"Код не найден или уже использован."

    web_uid=row["user_id"]
    if row["tg_user_id"] and row["tg_user_id"] != tg_user_id:
        return False,"Этот аккаунт уже привязан к другому Telegram."

    # Older bot registrations may have user_id=tg_user_id but a NULL
    # tg_user_id column. Treat that row as the same Telegram identity too.
    tg_row=get_user_by_tg(tg_user_id) or get_user(tg_user_id)
    if tg_row and tg_row["user_id"] == web_uid:
        db.execute("UPDATE users SET username=COALESCE(?,username),web_verified=1,verification_code=NULL,verification_code_hash=NULL,verification_code_expires_at=NULL WHERE user_id=?",
                   (username,web_uid))
        clear_auth_failures("telegram_link", str(tg_user_id))
        return True,"linked"

    try:
        db.execute("BEGIN IMMEDIATE")

        # No Telegram profile yet: keep the old behaviour, but migrate every FK
        # first so the primary-key change remains safe with foreign_keys=ON.
        if tg_row is None:
            canonical=tg_user_id
            admin_role = "admin" if tg_user_id in ADMIN_TELEGRAM_IDS else "user"
            db.execute("""INSERT INTO users(user_id,name,username,balance,helper_categories,tg_user_id,web_verified,role)
                VALUES(?,?,?,?,?,?,1,?)""", (canonical,row["name"],username,row["balance"],row["helper_categories"],tg_user_id,admin_role))
            db.execute("UPDATE users SET helper_availability=? WHERE user_id=?",(row["helper_availability"] or "",canonical))
            for table,col in [
                ("requests","requester_id"),("requests","helper_id"),
                ("helper_queue","user_id"),("billing_invoices","user_id"),
                ("subscriptions","user_id"),
                ("web_login_tickets","user_id"),("ai_usage","user_id"),
                ("admin_audit_log","admin_user_id"),("admin_audit_log","target_user_id"),
                ("identity_verification_requests","reviewer_id"),
                ("ads","user_id"),("commercial_orders","user_id"),("community_events","creator_id"),("event_participants","user_id"),
                ("chats","user_a_id"),("chats","user_b_id"),("chat_messages","user_id"),("request_candidates","candidate_id")
            ]:
                db.execute(f"UPDATE {table} SET {col}=? WHERE {col}=?",(canonical,web_uid))
            db.execute("UPDATE favorites SET user_id=? WHERE user_id=?",(canonical,web_uid))
            db.execute("UPDATE favorites SET favorite_user_id=? WHERE favorite_user_id=?",(canonical,web_uid))
            db.execute("UPDATE sessions SET user_id=? WHERE user_id=?",(canonical,web_uid))
            db.execute("UPDATE identity_verification_requests SET user_id=? WHERE user_id=?", (canonical, web_uid))
            db.execute("UPDATE email_verification_codes SET user_id=? WHERE user_id=?", (canonical, web_uid))
            db.execute("UPDATE phone_verification_codes SET user_id=? WHERE user_id=?", (canonical, web_uid))
            db.execute("DELETE FROM users WHERE user_id=?",(web_uid,))
            db.execute("UPDATE users SET name=?,username=COALESCE(?,username),email=?,password_hash=?,balance=?,helper_categories=?,created_at=?,pro_until=?,verified_until=?,business_until=?,favorite_slots=?,verification_code=NULL,verification_code_hash=NULL,verification_code_expires_at=NULL,web_verified=1,email_verified=?,full_name=?,birth_date=?,phone=?,phone_verified=?,lat=?,lon=?,city=?,bio=? WHERE user_id=?",
                       (row["name"],username or row["username"],row["email"],row["password_hash"],row["balance"],row["helper_categories"],row["created_at"],row["pro_until"],row["verified_until"],row["business_until"],row["favorite_slots"],row["email_verified"],row["full_name"],row["birth_date"],row["phone"],row["phone_verified"],row["lat"],row["lon"],row["city"],row["bio"],canonical))
            db.execute("COMMIT")
            clear_auth_failures("telegram_link", str(tg_user_id))
            return True,"linked"

        # Telegram was already used before the site account was linked. Merge
        # both identities into the Telegram id and preserve all activity.
        tg_uid=tg_row["user_id"]
        canonical=tg_uid

        # Prefer explicitly entered web profile data where it exists.
        merged_name=row["name"] or tg_row["name"]
        merged_email=tg_row["email"] or row["email"]
        merged_email_verified=tg_row["email_verified"] if tg_row["email"] else row["email_verified"]
        merged_password=tg_row["password_hash"] or row["password_hash"]
        merged_username=username or tg_row["username"] or row["username"]
        merged_categories=tg_row["helper_categories"] or row["helper_categories"]
        merged_city=tg_row["city"] or row["city"]
        merged_bio=tg_row["bio"] or row["bio"]
        merged_lat=tg_row["lat"] if tg_row["lat"] is not None else row["lat"]
        merged_lon=tg_row["lon"] if tg_row["lon"] is not None else row["lon"]
        merged_full_name=tg_row["full_name"] or row["full_name"]
        merged_birth_date=tg_row["birth_date"] or row["birth_date"]
        merged_phone=tg_row["phone"] or row["phone"]
        merged_phone_verified=tg_row["phone_verified"] if tg_row["phone"] else row["phone_verified"]
        merged_balance=max(int(tg_row["balance"] or 0),int(row["balance"] or 0))
        merged_favorite_slots=max(int(tg_row["favorite_slots"] or 0),int(row["favorite_slots"] or 0))
        merged_pro=max(x for x in (tg_row["pro_until"],row["pro_until"]) if x is not None) if (tg_row["pro_until"] or row["pro_until"]) else None
        merged_verified=max(x for x in (tg_row["verified_until"],row["verified_until"]) if x is not None) if (tg_row["verified_until"] or row["verified_until"]) else None
        merged_business=max(x for x in (tg_row["business_until"],row["business_until"]) if x is not None) if (tg_row["business_until"] or row["business_until"]) else None

        # Merge FK-backed activity. Tables with composite primary keys need
        # INSERT OR IGNORE first to avoid collisions, then the old rows are removed.
        for table,col in [
            ("requests","requester_id"),("requests","helper_id"),
            ("billing_invoices","user_id"),("subscriptions","user_id"),
            ("web_login_tickets","user_id"),("ads","user_id"),
            ("commercial_orders","user_id"),("chat_messages","user_id"),("community_events","creator_id")
        ]:
            db.execute(f"UPDATE {table} SET {col}=? WHERE {col}=?",(canonical,web_uid))

        db.execute("INSERT OR IGNORE INTO request_candidates(request_id,candidate_id,score,status,offer_token,seen_at,updated_at) SELECT request_id,?,score,status,offer_token,seen_at,updated_at FROM request_candidates WHERE candidate_id=?",(canonical,web_uid))
        db.execute("DELETE FROM request_candidates WHERE candidate_id=?",(web_uid,))
        db.execute("INSERT INTO ai_usage(user_id,request_count,token_count,period_start,updated_at) SELECT ?,request_count,token_count,period_start,updated_at FROM ai_usage WHERE user_id=? ON CONFLICT(user_id,period_start) DO UPDATE SET request_count=ai_usage.request_count+excluded.request_count,token_count=ai_usage.token_count+excluded.token_count",(canonical,web_uid))
        db.execute("DELETE FROM ai_usage WHERE user_id=?",(web_uid,))
        db.execute("UPDATE admin_audit_log SET admin_user_id=? WHERE admin_user_id=?",(canonical,web_uid))
        db.execute("UPDATE admin_audit_log SET target_user_id=? WHERE target_user_id=?",(canonical,web_uid))

        source_identity = get_identity_verification(web_uid)
        target_identity = get_identity_verification(canonical)
        if source_identity:
            if target_identity is None:
                db.execute("UPDATE identity_verification_requests SET user_id=? WHERE user_id=?", (canonical, web_uid))
            elif source_identity["status"] == "approved" and target_identity["status"] != "approved":
                db.execute("""UPDATE identity_verification_requests
                              SET status=?,submitted_at=?,reviewed_at=?,reviewer_id=?,note=? WHERE user_id=?""",
                           (source_identity["status"], source_identity["submitted_at"], source_identity["reviewed_at"],
                            source_identity["reviewer_id"], source_identity["note"], canonical))
                db.execute("DELETE FROM identity_verification_requests WHERE user_id=?", (web_uid,))
            else:
                db.execute("DELETE FROM identity_verification_requests WHERE user_id=?", (web_uid,))
        db.execute("UPDATE identity_verification_requests SET reviewer_id=? WHERE reviewer_id=?", (canonical, web_uid))

        db.execute("UPDATE chats SET user_a_id=? WHERE user_a_id=?",(canonical,web_uid))
        db.execute("UPDATE chats SET user_b_id=? WHERE user_b_id=?",(canonical,web_uid))

        db.execute("INSERT OR IGNORE INTO helper_queue(user_id,joined_at) SELECT ?,joined_at FROM helper_queue WHERE user_id=?",(canonical,web_uid))
        db.execute("DELETE FROM helper_queue WHERE user_id=?",(web_uid,))

        db.execute("INSERT OR IGNORE INTO event_participants(event_id,user_id,joined_at) SELECT event_id,?,joined_at FROM event_participants WHERE user_id=?", (canonical, web_uid))
        db.execute("DELETE FROM event_participants WHERE user_id=?", (web_uid,))

        db.execute("INSERT OR IGNORE INTO favorites(user_id,favorite_user_id,created_at) SELECT ?,favorite_user_id,created_at FROM favorites WHERE user_id=?",(canonical,web_uid))
        db.execute("INSERT OR IGNORE INTO favorites(user_id,favorite_user_id,created_at) SELECT user_id,?,created_at FROM favorites WHERE favorite_user_id=?",(canonical,web_uid))
        db.execute("DELETE FROM favorites WHERE user_id=? OR favorite_user_id=?",(web_uid,web_uid))

        # Website sessions now follow the canonical Telegram-backed account, so
        # the already-open browser remains logged in after linking.
        db.execute("UPDATE sessions SET user_id=? WHERE user_id=?",(canonical,web_uid))
        db.execute("DELETE FROM email_verification_codes WHERE user_id=?", (web_uid,))
        db.execute("DELETE FROM phone_verification_codes WHERE user_id=?", (web_uid,))

        # Remove the old web shadow before copying its unique email/password
        # onto the canonical Telegram row. All dependent rows were migrated above.
        db.execute("DELETE FROM users WHERE user_id=?",(web_uid,))

        # Merge billing / profile state into the canonical Telegram row.
        db.execute("""UPDATE users SET
            name=?,username=?,email=?,password_hash=?,balance=?,helper_categories=?,
            pro_until=?,verified_until=?,business_until=?,favorite_slots=?,
            tg_user_id=?,web_verified=1,verification_code=NULL,verification_code_hash=NULL,verification_code_expires_at=NULL,email_verified=?,full_name=?,birth_date=?,phone=?,phone_verified=?,lat=?,lon=?,city=?,bio=?
            WHERE user_id=?""",
            (merged_name,merged_username,merged_email,merged_password,merged_balance,merged_categories,
             merged_pro,merged_verified,merged_business,merged_favorite_slots,tg_user_id,
             merged_email_verified,merged_full_name,merged_birth_date,merged_phone,merged_phone_verified,merged_lat,merged_lon,merged_city,merged_bio,canonical))

        db.execute("UPDATE users SET helper_availability=? WHERE user_id=?",
                   (tg_row["helper_availability"] or row["helper_availability"] or "", canonical))
        db.execute("COMMIT")
        clear_auth_failures("telegram_link", str(tg_user_id))
        return True,"linked"
    except Exception:
        db.execute("ROLLBACK")
        raise

