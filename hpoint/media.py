"""Validated photographs and privacy-conscious community participant lists.

All persistence receives the caller's connection. Attach helpers participate
in the enclosing request/message transaction; they never commit independently.
Only generated, access-controlled image URLs leave the server in JSON.
"""
import base64
import binascii
from dataclasses import dataclass
from io import BytesIO
import re
import uuid
import warnings


MAX_PHOTOS = 3
MAX_PHOTO_BYTES = 3 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_EDGE = 1920
_DATA_IMAGE = re.compile(r"data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=]+)\Z")


@dataclass(frozen=True)
class PreparedPhoto:
    content: bytes
    width: int
    height: int
    mime: str = "image/jpeg"


def initialize_schema(db):
    integer = "BIGINT" if getattr(db, "is_postgres", False) else "INTEGER"
    db.execute(f"""CREATE TABLE IF NOT EXISTS photos(
        id TEXT PRIMARY KEY,
        owner_id {integer} NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        request_id {integer} REFERENCES requests(id) ON DELETE CASCADE,
        message_id {integer} REFERENCES chat_messages(id) ON DELETE CASCADE,
        mime TEXT NOT NULL,
        content_base64 TEXT NOT NULL,
        width {integer} NOT NULL,
        height {integer} NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CHECK ((request_id IS NOT NULL AND message_id IS NULL) OR
               (request_id IS NULL AND message_id IS NOT NULL))
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_photos_request ON photos(request_id,created_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_photos_message ON photos(message_id,created_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_photos_owner ON photos(owner_id)")


def prepare_photo(value):
    """Decode the image, cap its dimensions and discard all EXIF/GPS metadata."""
    if not isinstance(value, str) or len(value) > (MAX_PHOTO_BYTES * 4 // 3 + 100):
        raise ValueError("Фото должно быть не больше 3 МБ.")
    match = _DATA_IMAGE.fullmatch(value)
    if not match:
        raise ValueError("Прикрепите фото в формате JPEG, PNG или WebP.")
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("Не удалось прочитать фото.") from None
    if not raw or len(raw) > MAX_PHOTO_BYTES:
        raise ValueError("Фото должно быть не больше 3 МБ.")
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError:
        raise RuntimeError("Обработка фото временно недоступна.") from None
    allowed = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as source:
                if source.format != allowed[match.group(1)] or getattr(source, "n_frames", 1) != 1:
                    raise ValueError("Нужна обычная фотография JPEG, PNG или WebP.")
                width, height = source.size
                if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
                    raise ValueError("Фото слишком большое. Уменьшите его до 20 мегапикселей.")
                source.verify()
            with Image.open(BytesIO(raw)) as source:
                source.load()
                image = ImageOps.exif_transpose(source)
                image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
                # A fresh pixel-only image drops metadata, comments, profiles
                # and any content following the original image end marker.
                if "A" in image.getbands() or "transparency" in image.info:
                    rgba = image.convert("RGBA")
                    clean = Image.new("RGB", rgba.size, "white")
                    clean.paste(rgba, mask=rgba.getchannel("A"))
                else:
                    clean = Image.new("RGB", image.size)
                    clean.paste(image.convert("RGB"))
                output = BytesIO()
                clean.save(output, format="JPEG", quality=85, optimize=True)
                content = output.getvalue()
                if len(content) > MAX_PHOTO_BYTES:
                    raise ValueError("Не удалось уменьшить фото до 3 МБ.")
                return PreparedPhoto(content, *clean.size)
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError("Фото повреждено или имеет недопустимый размер.") from None


def prepare_photos(values):
    if values is None:
        return []
    if not isinstance(values, list) or len(values) > MAX_PHOTOS:
        raise ValueError("Можно прикрепить до трёх фотографий.")
    return [prepare_photo(value) for value in values]


def _active_user(db, user_id):
    user = db.execute("SELECT user_id,is_blocked FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not user or user["is_blocked"]:
        raise PermissionError("Войдите в свой аккаунт, чтобы посмотреть фото.")
    return user


def _attach(db, owner_id, photos, *, request_id=None, message_id=None):
    if any(not isinstance(photo, PreparedPhoto) for photo in photos):
        raise ValueError("Фото нужно проверить перед сохранением.")
    column, target = ("request_id", request_id) if request_id is not None else ("message_id", message_id)
    count = db.execute(f"SELECT COUNT(*) n FROM photos WHERE {column}=?", (target,)).fetchone()["n"]
    if int(count) + len(photos) > MAX_PHOTOS:
        raise ValueError("Можно прикрепить до трёх фотографий.")
    for photo in photos:
        db.execute("""INSERT INTO photos(id,owner_id,request_id,message_id,mime,content_base64,width,height)
            VALUES(?,?,?,?,?,?,?,?)""", (uuid.uuid4().hex, owner_id, request_id, message_id,
                photo.mime, base64.b64encode(photo.content).decode("ascii"), photo.width, photo.height))


def attach_request_photos(db, request_id, user_id, photos):
    """Call after request creation, inside the same write transaction."""
    _active_user(db, user_id)
    lock = " FOR UPDATE" if getattr(db, "is_postgres", False) else ""
    request = db.execute("SELECT * FROM requests WHERE id=?" + lock, (request_id,)).fetchone()
    if not request or request["requester_id"] != user_id:
        raise PermissionError("Фото может добавить только автор помощи.")
    if request["status"] not in ("open", "in_progress"):
        raise ValueError("К закрытой помощи нельзя добавить фото.")
    _attach(db, user_id, photos, request_id=request_id)
    return request_photo_metadata(db, request_id)


def attach_message_photos(db, message_id, user_id, photos):
    """Call after inserting the message, inside its write transaction."""
    _active_user(db, user_id)
    lock = " FOR UPDATE OF m" if getattr(db, "is_postgres", False) else ""
    message = db.execute("""SELECT m.id,m.user_id,c.user_a_id,c.user_b_id FROM chat_messages m
        JOIN chats c ON c.id=m.chat_id WHERE m.id=?""" + lock, (message_id,)).fetchone()
    if not message or message["user_id"] != user_id or user_id not in (message["user_a_id"], message["user_b_id"]):
        raise PermissionError("Нет доступа к этому сообщению.")
    _attach(db, user_id, photos, message_id=message_id)
    return message_photo_metadata(db, message_id)


def _metadata(row):
    return {"id": row["id"], "url": "/api/photos?id=" + row["id"],
            "width": int(row["width"]), "height": int(row["height"])}


def request_photo_metadata(db, request_id):
    return [_metadata(row) for row in db.execute("SELECT id,width,height FROM photos WHERE request_id=? ORDER BY created_at,id", (request_id,)).fetchall()]


def message_photo_metadata(db, message_id):
    return [_metadata(row) for row in db.execute("SELECT id,width,height FROM photos WHERE message_id=? ORDER BY created_at,id", (message_id,)).fetchall()]


def messages_with_photos(db, messages):
    """Enrich up to one chat page using one metadata query, without image bytes."""
    messages = [dict(message) for message in messages]
    ids = [message["id"] for message in messages]
    by_message = {}
    if ids:
        rows = db.execute("SELECT id,message_id,width,height FROM photos WHERE message_id IN (" + ",".join("?" for _ in ids) + ") ORDER BY created_at,id", ids).fetchall()
        for row in rows:
            by_message.setdefault(row["message_id"], []).append(_metadata(row))
    return [{**message, "photos": by_message.get(message["id"], [])} for message in messages]


def photo_for_user(db, photo_id, user_id):
    """Return a sanitized JPEG only after checking current membership/access."""
    _active_user(db, user_id)
    if not isinstance(photo_id, str) or not re.fullmatch(r"[0-9a-f]{32}", photo_id):
        raise LookupError("Фото не найдено.")
    photo = db.execute("SELECT * FROM photos WHERE id=?", (photo_id,)).fetchone()
    if not photo:
        raise LookupError("Фото не найдено.")
    if photo["request_id"] is not None:
        request = db.execute("SELECT status,requester_id,helper_id FROM requests WHERE id=?", (photo["request_id"],)).fetchone()
        permitted = request and (request["status"] == "open" or user_id in (request["requester_id"], request["helper_id"]))
    else:
        chat = db.execute("""SELECT c.user_a_id,c.user_b_id FROM chats c JOIN chat_messages m
            ON m.chat_id=c.id WHERE m.id=?""", (photo["message_id"],)).fetchone()
        permitted = chat and user_id in (chat["user_a_id"], chat["user_b_id"])
    if not permitted:
        raise PermissionError("Нет доступа к этому фото.")
    return photo["mime"], base64.b64decode(photo["content_base64"], validate=True)


def event_participants(db, event_id, user_id):
    """Names and public profile identifiers only: never contact information."""
    _active_user(db, user_id)
    event = db.execute("SELECT id,title,status,creator_id FROM community_events WHERE id=?", (event_id,)).fetchone()
    if not event:
        raise LookupError("Мероприятие не найдено.")
    if event["status"] != "published" and event["creator_id"] != user_id:
        raise PermissionError("Список участников этого мероприятия недоступен.")
    rows = db.execute("""SELECT u.user_id,u.name FROM event_participants p JOIN users u ON u.user_id=p.user_id
        WHERE p.event_id=? AND u.is_blocked=0 ORDER BY p.joined_at,u.user_id""", (event_id,)).fetchall()
    return {"event_id": event["id"], "title": event["title"],
            "participants": [{"profile_id": int(row["user_id"]), "name": row["name"]} for row in rows]}
