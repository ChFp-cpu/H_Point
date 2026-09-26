"""SQLite persistence shared by the website and Telegram bot."""
import sqlite3
from .config import DB_PATH, START_BALANCE, STATUS_OPEN, STATUS_IN_PROGRESS, STATUS_DONE

db = None

def db_connect():
    if db is not None:
        return db
    conn = sqlite3.connect(DB_PATH, isolation_level=None, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=15000')
    return conn

def _close(c):
    if db is None:
        c.close()

def init_db():
    conn = db_connect()
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS users (
      user_id INTEGER PRIMARY KEY, name TEXT NOT NULL, username TEXT,
      balance INTEGER NOT NULL DEFAULT 100, helper_categories TEXT NOT NULL DEFAULT '',
      skills TEXT NOT NULL DEFAULT '', portfolio TEXT NOT NULL DEFAULT '',
      platform TEXT NOT NULL DEFAULT 'telegram', telegram_id INTEGER UNIQUE, telegram_username TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS requests (
      id INTEGER PRIMARY KEY AUTOINCREMENT, requester_id INTEGER NOT NULL REFERENCES users(user_id),
      helper_id INTEGER REFERENCES users(user_id), category TEXT NOT NULL DEFAULT 'other',
      what TEXT NOT NULL, place TEXT NOT NULL, time_needed TEXT NOT NULL, urgency TEXT NOT NULL,
      details TEXT NOT NULL, required_skills TEXT NOT NULL DEFAULT '', featured_until TEXT,
      status TEXT NOT NULL DEFAULT 'open', rating INTEGER, requester_rating INTEGER,
      requester_review TEXT, helper_rating INTEGER, helper_review TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, completed_at TEXT
    );
    CREATE TABLE IF NOT EXISTS applications (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      request_id INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
      helper_id INTEGER NOT NULL REFERENCES users(user_id),
      status TEXT NOT NULL DEFAULT 'pending',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(request_id, helper_id)
    );
    CREATE TABLE IF NOT EXISTS helper_queue (
      user_id INTEGER PRIMARY KEY REFERENCES users(user_id),
      joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS link_tokens (
      code TEXT PRIMARY KEY,
      web_user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      expires_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS notifications (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      text TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      sent_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_requests_open ON requests(status, featured_until, created_at);
    CREATE INDEX IF NOT EXISTS idx_requests_requester ON requests(requester_id, status);
    CREATE INDEX IF NOT EXISTS idx_requests_helper ON requests(helper_id, status);
    CREATE INDEX IF NOT EXISTS idx_apps_request ON applications(request_id, status);
    CREATE INDEX IF NOT EXISTS idx_apps_helper ON applications(helper_id, status);
    ''')
    # Lightweight migrations for databases created by older H-Point versions.
    user_cols = {r['name'] for r in conn.execute('PRAGMA table_info(users)').fetchall()}
    for col, ddl in [('platform', "TEXT NOT NULL DEFAULT 'telegram'"), ('password_hash', 'TEXT'), ('telegram_id', 'INTEGER'),
                     ('skills', "TEXT NOT NULL DEFAULT ''"), ('portfolio', "TEXT NOT NULL DEFAULT ''"), ('telegram_username', 'TEXT')]:
        if col not in user_cols:
            conn.execute(f'ALTER TABLE users ADD COLUMN {col} {ddl}')
    req_cols = {r['name'] for r in conn.execute('PRAGMA table_info(requests)').fetchall()}
    for col, ddl in [('required_skills', "TEXT NOT NULL DEFAULT ''"), ('featured_until', 'TEXT')]:
        if col not in req_cols:
            conn.execute(f'ALTER TABLE requests ADD COLUMN {col} {ddl}')
    _close(conn)

def _one(sql, args=()):
    c = db_connect(); r = c.execute(sql, args).fetchone(); _close(c); return r

def _all(sql, args=()):
    c = db_connect(); r = c.execute(sql, args).fetchall(); _close(c); return r

def get_user(user_id): return _one('SELECT * FROM users WHERE user_id=?', (user_id,))

def get_user_by_telegram(telegram_id): return _one('SELECT * FROM users WHERE telegram_id=?', (telegram_id,))

def resolve_user_id(telegram_id):
    row = get_user_by_telegram(telegram_id)
    return row['user_id'] if row else None

def create_user(user_id, name, username, platform='telegram'):
    c = db_connect()
    existing = c.execute('SELECT * FROM users WHERE telegram_id=?', (user_id,)).fetchone()
    if existing:
        c.execute('UPDATE users SET name=?, telegram_username=COALESCE(?,telegram_username) WHERE user_id=?', (name, username, existing['user_id']))
        _close(c); return existing['user_id']
    collision = c.execute('SELECT user_id FROM users WHERE user_id=?', (user_id,)).fetchone()
    if collision:
        cur = c.execute("INSERT INTO users(name,username,balance,helper_categories,skills,portfolio,platform,telegram_id,telegram_username) VALUES(?,?,?,?,?,?,?,?,?)",
                        (name, None, START_BALANCE, '', '', '', platform, user_id if platform == 'telegram' else None, username if platform == 'telegram' else None))
        uid = cur.lastrowid
    else:
        c.execute("INSERT INTO users(user_id,name,username,balance,helper_categories,skills,portfolio,platform,telegram_id,telegram_username) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (user_id, name, None, START_BALANCE, '', '', '', platform, user_id if platform == 'telegram' else None, username if platform == 'telegram' else None))
        uid = user_id
    _close(c); return uid

def normalize_username(username):
    return (username or '').strip().lstrip('@').lower()[:50]

def get_web_user_by_username(username):
    username = normalize_username(username)
    if not username: return None
    return _one("SELECT * FROM users WHERE lower(ltrim(username,'@'))=? ORDER BY CASE WHEN platform='linked' THEN 0 ELSE 1 END, user_id LIMIT 1", (username,))

def create_web_user(name, username, password_hash=None):
    username = normalize_username(username)
    c = db_connect()
    if c.execute("SELECT 1 FROM users WHERE lower(ltrim(username,'@'))=?", (username,)).fetchone():
        _close(c); raise ValueError('username already exists')
    cur = c.execute("INSERT INTO users(name,username,balance,helper_categories,skills,portfolio,platform,password_hash) VALUES(?,?,?,?,?,?,?,?)",
                    (name, username or None, START_BALANCE, '', '', '', 'web', password_hash))
    uid = cur.lastrowid
    _close(c)
    return uid

def set_user_password(user_id, password_hash):
    c=db_connect(); cur=c.execute('UPDATE users SET password_hash=? WHERE user_id=?',(password_hash,user_id)); _close(c); return cur.rowcount==1

def get_request(request_id): return _one('SELECT * FROM requests WHERE id=?', (request_id,))
def get_active_own_request(user_id): return _one("SELECT * FROM requests WHERE requester_id=? AND status IN (?,?) ORDER BY id DESC LIMIT 1", (user_id, STATUS_OPEN, STATUS_IN_PROGRESS))
def get_active_help(user_id): return _one("SELECT * FROM requests WHERE helper_id=? AND status=? ORDER BY id DESC LIMIT 1", (user_id, STATUS_IN_PROGRESS))
def get_in_progress_task(user_id): return _one("SELECT * FROM requests WHERE status=? AND (requester_id=? OR helper_id=?) ORDER BY id DESC LIMIT 1", (STATUS_IN_PROGRESS, user_id, user_id))
def get_unrated_request(user_id): return _one("SELECT * FROM requests WHERE requester_id=? AND status=? AND requester_rating IS NULL ORDER BY id DESC LIMIT 1", (user_id, STATUS_DONE))
def get_unrated_help(user_id): return _one("SELECT * FROM requests WHERE helper_id=? AND status=? AND helper_rating IS NULL ORDER BY id DESC LIMIT 1", (user_id, STATUS_DONE))
def get_history(user_id, limit=10): return _all('SELECT * FROM requests WHERE requester_id=? OR helper_id=? ORDER BY id DESC LIMIT ?', (user_id, user_id, limit))

def get_user_stats(user_id):
    a = _one("SELECT COUNT(*) n, AVG(helper_rating) avg FROM requests WHERE helper_id=? AND status=?", (user_id, STATUS_DONE))
    b = _one("SELECT COUNT(*) n, AVG(requester_rating) avg FROM requests WHERE requester_id=? AND status=?", (user_id, STATUS_DONE))
    return {'helped': a['n'] or 0, 'helped_avg': float(a['avg']) if a['avg'] is not None else None,
            'received': b['n'] or 0, 'received_avg': float(b['avg']) if b['avg'] is not None else None}


def create_link_token(web_user_id, code, expires_at):
    c=db_connect(); c.execute('DELETE FROM link_tokens WHERE web_user_id=?',(web_user_id,)); c.execute('INSERT INTO link_tokens(code,web_user_id,expires_at) VALUES(?,?,?)',(code,web_user_id,expires_at)); _close(c)

def get_link_token(code):
    return _one("SELECT * FROM link_tokens WHERE code=? AND datetime(expires_at)>datetime('now')",(code,))

def consume_link_token(code):
    c=db_connect(); c.execute('DELETE FROM link_tokens WHERE code=?',(code,)); _close(c)

def link_accounts(web_user_id, telegram_id, telegram_username=None):
    """Merge the anonymous web account into the Telegram account identity.

    The web user's primary key remains the canonical identity, so an existing
    browser session keeps working after linking. Telegram is attached through
    users.telegram_id and all bot actions resolve that canonical user_id.
    """
    c = db_connect(); c.execute('BEGIN IMMEDIATE')
    web = c.execute('SELECT * FROM users WHERE user_id=?', (web_user_id,)).fetchone()
    tg = c.execute('SELECT * FROM users WHERE telegram_id=? OR user_id=?', (telegram_id, telegram_id)).fetchone()
    if not web or web['platform'] != 'web':
        c.rollback(); _close(c); return False
    if tg and tg['user_id'] == web_user_id:
        c.execute("UPDATE users SET platform='linked', telegram_id=?, telegram_username=? WHERE user_id=?", (telegram_id, telegram_username, web_user_id))
        c.execute('DELETE FROM link_tokens WHERE web_user_id=?', (web_user_id,))
        c.commit(); _close(c); return True
    if tg is None:
        # The bot user may have been created using user_id=telegram_id in an older DB.
        tg = c.execute('SELECT * FROM users WHERE user_id=?', (telegram_id,)).fetchone()
    if tg is None:
        c.execute("UPDATE users SET platform='linked', telegram_id=?, telegram_username=? WHERE user_id=?", (telegram_id, telegram_username, web_user_id))
        c.execute('DELETE FROM link_tokens WHERE web_user_id=?', (web_user_id,))
        c.commit(); _close(c); return True

    tg_id = tg['user_id']
    if tg['platform'] == 'linked' and tg_id != web_user_id:
        c.rollback(); _close(c); return False
    if tg_id == web_user_id:
        c.rollback(); _close(c); return False

    # Keep the web profile as canonical. Merge profile fields without duplicating
    # the 100 HP starting balance; preserve whichever balance is larger.
    name = web['name'] or tg['name']
    skills = web['skills'] or tg['skills']
    portfolio = web['portfolio'] or tg['portfolio']
    cats = web['helper_categories'] or tg['helper_categories']
    balance = max(web['balance'] or 0, tg['balance'] or 0)

    # Move all requester/helper references to the canonical web user.
    c.execute('UPDATE requests SET requester_id=? WHERE requester_id=?', (web_user_id, tg_id))
    c.execute('UPDATE requests SET helper_id=? WHERE helper_id=?', (web_user_id, tg_id))

    # Move applications and de-duplicate collisions.
    apps = c.execute('SELECT id, request_id FROM applications WHERE helper_id=?', (tg_id,)).fetchall()
    for a in apps:
        exists = c.execute('SELECT id FROM applications WHERE request_id=? AND helper_id=?', (a['request_id'], web_user_id)).fetchone()
        if exists:
            c.execute('DELETE FROM applications WHERE id=?', (a['id'],))
        else:
            c.execute('UPDATE applications SET helper_id=? WHERE id=?', (web_user_id, a['id']))

    c.execute('DELETE FROM helper_queue WHERE user_id=?', (tg_id,))
    # Preserve notifications by moving them to the canonical user.
    c.execute('UPDATE notifications SET user_id=? WHERE user_id=?', (web_user_id, tg_id))
    # Free the unique Telegram identity before assigning it to the canonical web row.
    c.execute('UPDATE users SET telegram_id=NULL WHERE user_id=?', (tg_id,))
    c.execute("UPDATE users SET name=?, skills=?, portfolio=?, helper_categories=?, balance=?, platform='linked', telegram_id=?, telegram_username=? WHERE user_id=?",
              (name, skills, portfolio, cats, balance, telegram_id, telegram_username, web_user_id))
    c.execute('DELETE FROM users WHERE user_id=?', (tg_id,))
    c.execute('DELETE FROM link_tokens WHERE web_user_id=?', (web_user_id,))
    c.commit(); _close(c); return True

def enqueue_notification(user_id, text):
    c=db_connect(); c.execute('INSERT INTO notifications(user_id,text) VALUES(?,?)',(user_id,text)); _close(c)

def pending_notifications(user_id, limit=20):
    return _all('SELECT * FROM notifications WHERE user_id=? AND sent_at IS NULL ORDER BY id LIMIT ?',(user_id,limit))

def mark_notification_sent(notification_id):
    c=db_connect(); c.execute("UPDATE notifications SET sent_at=CURRENT_TIMESTAMP WHERE id=? AND sent_at IS NULL",(notification_id,)); _close(c)

def telegram_users_with_pending(limit=100):
    return _all("SELECT DISTINCT u.user_id, u.telegram_id FROM users u JOIN notifications n ON n.user_id=u.user_id WHERE u.telegram_id IS NOT NULL AND n.sent_at IS NULL LIMIT ?",(limit,))
