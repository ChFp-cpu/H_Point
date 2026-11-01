"""Explicit, private calendar snapshots; never an external calendar connection.

RFC 5545 text is escaped before UTF-8 safe folding. Exports contain agenda titles
and responsibility, never CRM contacts, health observations, notes or prices.
"""
from datetime import datetime, time, timedelta, timezone
import re

from . import commercial as c, commercial_team as team


def _text(value):
    value = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    value = "".join(char for char in value if (ord(char) >= 32 and ord(char) != 127) or char in "\n\t")
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def _fold(line):
    chunks, current, size = [], "", 0
    for char in line:
        length = len(char.encode("utf-8"))
        if size + length > 75:
            chunks.append(current)
            current, size = " ", 1
        current += char
        size += length
    chunks.append(current)
    return "\r\n".join(chunks)


def _stamp(value):
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def export_calendar(db, uid, owner_id=None, starts_on=None, ends_on=None,
                    person=None, kind="all", timezone_minutes="0"):
    owner, profile, _role = c._context(db, uid, owner_id)
    if not profile:
        raise ValueError("Сначала создайте кабинет для работы.")
    if kind not in ("all", "bookings", "shifts"):
        raise ValueError("Выберите записи, смены или всё расписание.")
    if isinstance(timezone_minutes, bool) or not re.fullmatch(r"-?\d{1,4}", str(timezone_minutes)):
        raise ValueError("Некорректный часовой пояс.")
    offset = int(timezone_minutes)
    if not -840 <= offset <= 840:
        raise ValueError("Некорректный часовой пояс.")
    zone = timezone(timedelta(minutes=offset))
    today = c._now().astimezone(zone).date()
    first = team._day(starts_on) or today.isoformat()
    try:
        last = team._day(ends_on) or (datetime.fromisoformat(first).date() + timedelta(days=30)).isoformat()
    except OverflowError:
        raise ValueError("Проверьте период календаря.")
    first_day, last_day = datetime.fromisoformat(first).date(), datetime.fromisoformat(last).date()
    if last_day < first_day or (last_day - first_day).days > 365:
        raise ValueError("Выберите период от одного дня до 366 дней.")
    start = datetime.combine(first_day, time.min, zone)
    try:
        end = datetime.combine(last_day + timedelta(days=1), time.min, zone)
    except OverflowError:
        raise ValueError("Проверьте период календаря.")
    assigned = team.assignee(db, owner, person) if person not in (None, "") else None
    people = {row["user_id"]: row["name"] for row in team._members(db, owner)}
    objects = {row["id"]: row["title"] for row in db.execute(
        "SELECT id,title FROM commercial_objects WHERE owner_id=?", (owner,)).fetchall()}
    events = []
    for collection, table in (("bookings", "commercial_bookings"), ("shifts", "commercial_shifts")):
        if kind != "all" and kind != collection:
            continue
        sql = "SELECT * FROM " + table + " WHERE owner_id=?"
        args = [owner]
        if collection == "bookings":
            sql += " AND status='planned'"
        if assigned is not None:
            sql += " AND assignee_id=?"
            args.append(assigned)
        # Parse instants, including legacy non-UTC timestamps; SQL lexical
        # comparisons would exclude valid events close to midnight.
        for row in db.execute(sql, tuple(args)).fetchall():
            begins = c._date(row["starts_at"])
            if begins >= end:
                continue
            try:
                finishes = (c._date(row["ends_at"]) if collection == "shifts"
                            else begins + timedelta(minutes=row["duration_minutes"]))
            except OverflowError:
                raise ValueError("Проверьте дату и длительность записи в расписании.")
            if finishes <= start:
                continue
            description = ["Организация: " + profile["title"]]
            if row["assignee_id"] in people:
                description.append("Исполнитель: " + people[row["assignee_id"]])
            if row["object_id"] in objects:
                description.append("Объект: " + objects[row["object_id"]])
            events.append((begins, collection, row["id"], [
                "BEGIN:VEVENT", f"UID:hpoint-{owner}-{collection}-{row['id']}@gethpoint.ru",
                "DTSTAMP:" + _stamp(c._now()), "DTSTART:" + _stamp(begins),
                "DTEND:" + _stamp(finishes), "SUMMARY:" + _text(row["title"]),
                "DESCRIPTION:" + _text("\n".join(description)),
                "CATEGORIES:" + ("Записи" if collection == "bookings" else "Смены"),
                "CLASS:PRIVATE", "STATUS:CONFIRMED", "END:VEVENT"]))
            if len(events) > 10000:
                raise ValueError("Слишком много событий. Выберите меньший период или сотрудника.")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//H-Point//Work Calendar//RU",
             "CALSCALE:GREGORIAN", "X-WR-CALNAME:" + _text(profile["title"])]
    for _date, _kind, _id, event in sorted(events, key=lambda event: event[:3]):
        lines.extend(event)
    lines.append("END:VCALENDAR")
    return {"body": ("\r\n".join(_fold(line) for line in lines) + "\r\n").encode("utf-8"),
            "content_type": "text/calendar; charset=utf-8",
            "filename": f"hpoint-calendar-{first}-{last}.ics"}
