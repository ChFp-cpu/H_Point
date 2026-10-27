"""Private conversations for individual responses to a help request."""
import re
from . import media


def initialize_schema(db):
    """Preserve legacy chat/message IDs while allowing one chat per candidate."""
    postgres=bool(getattr(db,"is_postgres",False))
    if postgres:
        rows=db.execute("""SELECT tc.constraint_name FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage k USING(constraint_catalog,constraint_schema,constraint_name)
            WHERE tc.table_schema=current_schema() AND tc.table_name='chats' AND tc.constraint_type='UNIQUE'
            AND k.table_name=tc.table_name
            GROUP BY tc.constraint_name HAVING COUNT(*)=1 AND BOOL_AND(k.column_name='request_id')""").fetchall()
        for row in rows:
            name=row["constraint_name"]
            if not re.fullmatch(r"[A-Za-z0-9_]+",name):raise RuntimeError("Unexpected chat constraint")
            db.execute('ALTER TABLE chats DROP CONSTRAINT IF EXISTS "'+name+'"')
    else:
        legacy=False
        for row in db.execute("PRAGMA index_list(chats)").fetchall():
            if row["unique"]:
                name=row["name"]
                if not re.fullmatch(r"[A-Za-z0-9_]+",name):raise RuntimeError("Unexpected chat index")
                columns=[item["name"] for item in db.execute('PRAGMA index_info("'+name+'")').fetchall()]
                legacy=legacy or columns==["request_id"]
        if legacy:
            foreign_keys=int(db.execute("PRAGMA foreign_keys").fetchone()[0])
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("""CREATE TABLE chats_responses_migration(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
                    user_a_id INTEGER NOT NULL REFERENCES users(user_id),
                    user_b_id INTEGER NOT NULL REFERENCES users(user_id),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
                db.execute("INSERT INTO chats_responses_migration SELECT id,request_id,user_a_id,user_b_id,created_at FROM chats")
                db.execute("DROP TABLE chats")
                db.execute("ALTER TABLE chats_responses_migration RENAME TO chats")
                assert not db.execute("PRAGMA foreign_key_check").fetchall(), "Chat migration broke references"
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
            finally:
                db.execute("PRAGMA foreign_keys="+str(foreign_keys))
    integer="BIGINT" if postgres else "INTEGER"
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_chats_request_helper ON chats(request_id,user_b_id)")
    db.execute("""CREATE TABLE IF NOT EXISTS chat_archives(
        chat_id """+integer+""" NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
        user_id """+integer+""" NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        archived_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(chat_id,user_id))""")
    db.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES('008_response_conversations')")


def ensure_chat(db,request_id,helper_id=None):
    request=db.execute("SELECT * FROM requests WHERE id=?",(request_id,)).fetchone()
    if not request:return None
    helper_id=helper_id if helper_id is not None else request["helper_id"]
    if helper_id is None or helper_id==request["requester_id"]:return None
    db.execute("INSERT OR IGNORE INTO chats(request_id,user_a_id,user_b_id) VALUES(?,?,?)",(request_id,request["requester_id"],helper_id))
    row=db.execute("SELECT id FROM chats WHERE request_id=? AND user_b_id=?",(request_id,helper_id)).fetchone()
    return row["id"] if row else None


def _user(db,uid):
    row=db.execute("SELECT user_id,is_blocked FROM users WHERE user_id=?",(uid,)).fetchone()
    if not row or row["is_blocked"]:raise PermissionError("Аккаунт недоступен.")


def _positive(value,label):
    if isinstance(value,bool):raise ValueError("Некорректный "+label)
    try:value=int(value)
    except (TypeError,ValueError):raise ValueError("Некорректный "+label)
    if value<=0:raise ValueError("Некорректный "+label)
    return value


def resolve_chat(db,uid,request_id=None,chat_id=None):
    _user(db,uid)
    if chat_id is not None:
        chat_id=_positive(chat_id,"чат")
        row=db.execute("SELECT * FROM chats WHERE id=? AND (user_a_id=? OR user_b_id=?)",(chat_id,uid,uid)).fetchone()
        if not row:raise PermissionError("Нет доступа к чату.")
        if request_id is not None and _positive(request_id,"request_id")!=row["request_id"]:raise ValueError("Чат относится к другой заявке.")
        return row
    rid=_positive(request_id,"request_id")
    request=db.execute("SELECT requester_id,helper_id FROM requests WHERE id=?",(rid,)).fetchone()
    if not request:raise LookupError("Заявка не найдена.")
    if uid!=request["requester_id"]:
        rows=db.execute("SELECT * FROM chats WHERE request_id=? AND user_b_id=?",(rid,uid)).fetchall()
    elif request["helper_id"] is not None:
        rows=db.execute("SELECT * FROM chats WHERE request_id=? AND user_b_id=?",(rid,request["helper_id"])).fetchall()
    else:
        rows=db.execute("SELECT * FROM chats WHERE request_id=? AND user_a_id=? ORDER BY id DESC",(rid,uid)).fetchall()
    if not rows:
        if uid!=request["requester_id"]:raise PermissionError("Нет доступа к чату.")
        raise LookupError("Чат ещё не создан.")
    if len(rows)>1:raise ValueError("Выберите собеседника в списке чатов.")
    return rows[0]


def _messages(db,cid,uid):
    rows=db.execute("""SELECT m.*,u.name author_name FROM chat_messages m JOIN users u ON u.user_id=m.user_id
        WHERE m.chat_id=? ORDER BY m.id DESC LIMIT 100""",(cid,)).fetchall()[::-1]
    return [{**m,"mine":m["user_id"]==uid} for m in media.messages_with_photos(db,rows)]


def _payload(db,chat,uid,messages=False):
    request=db.execute("SELECT * FROM requests WHERE id=?",(chat["request_id"],)).fetchone()
    other_id=chat["user_b_id"] if uid==chat["user_a_id"] else chat["user_a_id"]
    other=db.execute("SELECT name FROM users WHERE user_id=?",(other_id,)).fetchone()
    application=db.execute("SELECT status,offer_token FROM request_candidates WHERE request_id=? AND candidate_id=?",(chat["request_id"],chat["user_b_id"])).fetchone()
    candidate_status=application["status"] if application else None
    selected=request["helper_id"]==chat["user_b_id"]
    author=uid==request["requester_id"]
    active=request["status"]=="in_progress" and selected
    last=db.execute("SELECT id,text,created_at FROM chat_messages WHERE chat_id=? ORDER BY id DESC LIMIT 1",(chat["id"],)).fetchone()
    result={**dict(chat),"chat_id":chat["id"],"what":request["what"],"status":request["status"],
        "requester_id":request["requester_id"],"helper_id":request["helper_id"],"other_id":other_id,"other_name":other["name"] if other else "Участник",
        "candidate_id":chat["user_b_id"],"application_status":candidate_status,"application_token":application["offer_token"] if application else None,
        "reward_rub":int(request["reward_rub"] or 0),"reward_payment_status":request["reward_payment_status"],
        "can_send":active or (request["status"]=="open" and candidate_status in ("applied","offered")),
        "can_complete":active and author,"can_cancel":request["status"] in ("open","in_progress") and (author or active),
        "can_select":author and request["status"]=="open" and candidate_status=="applied",
        "can_withdraw":not author and request["status"]=="open" and candidate_status=="applied",
        "can_decline":not author and request["status"]=="open" and candidate_status=="offered",
        "last_message":last["text"] if last else None,"last_message_id":last["id"] if last else 0,
        "updated_at":last["created_at"] if last else chat["created_at"],
        "archived":bool(db.execute("SELECT 1 FROM chat_archives WHERE chat_id=? AND user_id=?",(chat["id"],uid)).fetchone())}
    if messages:result["messages"]=_messages(db,chat["id"],uid)
    return result


def list_chats(db,uid,include_archived=False):
    _user(db,uid)
    rows=db.execute("""SELECT c.* FROM chats c LEFT JOIN chat_archives a ON a.chat_id=c.id AND a.user_id=?
        WHERE (c.user_a_id=? OR c.user_b_id=?)"""+("" if include_archived else " AND a.chat_id IS NULL")+" ORDER BY COALESCE((SELECT MAX(id) FROM chat_messages WHERE chat_id=c.id),0) DESC,c.id DESC",(uid,uid,uid)).fetchall()
    return [_payload(db,row,uid) for row in rows]


def read_chat(db,uid,request_id=None,chat_id=None):
    return _payload(db,resolve_chat(db,uid,request_id,chat_id),uid,messages=True)


def archive_chat(db,uid,chat_id,archived=True):
    db.execute("BEGIN IMMEDIATE")
    try:
        chat=resolve_chat(db,uid,chat_id=chat_id)
        if getattr(db,"is_postgres",False):db.execute("SELECT id FROM chats WHERE id=? FOR UPDATE",(chat["id"],)).fetchone()
        if archived:
            db.execute("""INSERT INTO chat_archives(chat_id,user_id) VALUES(?,?) ON CONFLICT(chat_id,user_id)
                DO UPDATE SET archived_at=CURRENT_TIMESTAMP""",(chat["id"],uid))
        else:db.execute("DELETE FROM chat_archives WHERE chat_id=? AND user_id=?",(chat["id"],uid))
        db.execute("COMMIT")
        return True
    except BaseException:
        db.execute("ROLLBACK")
        raise


def send_message(db,uid,text,request_id=None,chat_id=None,photos=None):
    if not isinstance(text,str):raise ValueError("Проверьте текст сообщения.")
    text=text.strip()
    if len(text)>1000:raise ValueError("Сообщение: до 1000 символов.")
    prepared=media.prepare_photos(photos)
    if not text and not prepared:raise ValueError("Добавьте текст или фото.")
    db.execute("BEGIN IMMEDIATE")
    try:
        chat=resolve_chat(db,uid,request_id,chat_id)
        if getattr(db,"is_postgres",False):
            db.execute("SELECT id FROM requests WHERE id=? FOR UPDATE",(chat["request_id"],)).fetchone()
            db.execute("SELECT id FROM chats WHERE id=? FOR UPDATE",(chat["id"],)).fetchone()
        payload=_payload(db,chat,uid)
        if not payload["can_send"]:raise ValueError("Обсуждение закрыто. История переписки сохранена.")
        sql="INSERT INTO chat_messages(chat_id,user_id,text) VALUES(?,?,?)"
        cur=db.execute(sql+(" RETURNING id" if getattr(db,"is_postgres",False) else ""),(chat["id"],uid,text))
        mid=cur.fetchone()["id"] if getattr(db,"is_postgres",False) else cur.lastrowid
        media.attach_message_photos(db,mid,uid,prepared)
        db.execute("DELETE FROM chat_archives WHERE chat_id=?",(chat["id"],))
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    return read_chat(db,uid,chat_id=chat["id"])
