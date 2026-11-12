"""Read-only discovery data for visitors, independent of private sync payloads.

Every returned record has an explicit field allowlist.  In particular, this
module must never reuse user_payload, request details, helper queues or the
commercial dashboard: those contain account and customer information.
"""
from datetime import datetime, timezone
from urllib.parse import parse_qs

from .config import CATEGORIES
from . import commercial


def public_snapshot(connection, *, category="", query="", limit=100):
    if category and category not in CATEGORIES:
        raise ValueError("Неизвестное направление помощи.")
    limit = max(1, min(int(limit), 100))
    query = str(query).strip()[:100].casefold()
    current = datetime.now(timezone.utc).isoformat()
    # No lifecycle mutations on a public GET. Unreserved paid requests and
    # expired records cannot be offered to a visitor as available work.
    rows = connection.execute("""SELECT r.id,r.what,r.category,r.time_needed,
        r.urgency,r.reward_rub,r.reward_test_rub,r.scheduled_at,r.created_at,
        u.name requester_name
        FROM requests r JOIN users u ON u.user_id=r.requester_id
        WHERE r.status='open' AND u.is_blocked=0
        AND (r.expires_at IS NULL OR r.expires_at>?)
        AND (r.reward_rub=0 OR r.reward_payment_status='paid')
        ORDER BY r.created_at DESC,r.id DESC LIMIT 300""", (current,)).fetchall()
    requests = []
    for row in rows:
        if category and row["category"] != category:
            continue
        title = CATEGORIES.get(row["category"], "Другое")
        if query and query not in (str(row["what"]) + " " + title).casefold():
            continue
        requests.append({
            "id": int(row["id"]), "what": row["what"],
            "category": row["category"], "category_name": title,
            "requester_name": row["requester_name"],
            "time_needed": row["time_needed"], "urgency": row["urgency"],
            "reward_rub": int(row["reward_rub"] or 0),
            "reward_test_rub": int(row["reward_test_rub"] or 0),
            "currency": "TEST_RUB", "scheduled_at": row["scheduled_at"],
            "created_at": row["created_at"], "status": "open",
        })
        if len(requests) >= limit:
            break
    events = [{
        "id": int(row["id"]), "title": row["title"],
        "starts_at": row["starts_at"], "ends_at": row["ends_at"],
        "capacity": int(row["capacity"] or 0),
        "participant_count": int(row["participant_count"] or 0),
        "creator_name": row["creator_name"],
    } for row in connection.execute("""SELECT e.id,e.title,e.starts_at,e.ends_at,
        e.capacity,u.name creator_name,
        (SELECT COUNT(*) FROM event_participants p WHERE p.event_id=e.id) participant_count
        FROM community_events e JOIN users u ON u.user_id=e.creator_id
        WHERE e.status='published' AND e.starts_at>? AND u.is_blocked=0
        ORDER BY e.starts_at,e.id LIMIT 100""", (current,)).fetchall()]
    # public_services already enforces published organization, active access,
    # verified owner and published service. Still keep a local allowlist so a
    # future commercial payload extension cannot expose private fields here.
    service_fields = ("id", "title", "description", "price_rub", "duration_minutes",
                      "currency", "organization_title", "organization_kind",
                      "organization_slug", "organization_url")
    services = [{key: row[key] for key in service_fields if key in row}
                for row in commercial.public_services(connection)]
    totals = connection.execute("""SELECT COUNT(*) total,
        COALESCE(SUM(CASE WHEN r.status='done' THEN 1 ELSE 0 END),0) done,
        COALESCE(SUM(CASE WHEN r.status='in_progress' THEN 1 ELSE 0 END),0) in_progress
        FROM requests r JOIN users u ON u.user_id=r.requester_id WHERE u.is_blocked=0""").fetchone()
    counts = {row["category"]: int(row["total"]) for row in connection.execute(
        """SELECT r.category,COUNT(*) total FROM requests r JOIN users u
        ON u.user_id=r.requester_id WHERE u.is_blocked=0 GROUP BY r.category""").fetchall()}
    return {"ok": True, "guest": True, "requests": requests, "events": events,
            "services": services, "categories": [{"key": key, "title": title,
                "count": counts.get(key, 0)} for key, title in CATEGORIES.items()],
            "progress": {"total": int(totals["total"]), "done": int(totals["done"]),
                         "in_progress": int(totals["in_progress"])}}


def handle_public_get(handler, parsed_url, connection, reply):
    """Hook before protected GET dispatch; True means a response was sent."""
    if parsed_url.path != "/api/guest":
        return False
    query = parse_qs(parsed_url.query)
    try:
        payload = public_snapshot(connection, category=query.get("category", [""])[0],
                                  query=query.get("q", [""])[0])
    except ValueError as error:
        reply(handler, {"ok": False, "error": str(error)}, 400)
    else:
        reply(handler, payload)
    return True


def enhance_page(page):
    """Install after the current workspace shell and before its single boot."""
    marker = "<script>window.hpointStart();</script>"
    if marker not in page:
        raise ValueError("H-Point workspace boot marker not found")
    return page.replace(marker,
        '<link rel="stylesheet" href="/assets/hpoint-guest.css?v=20261107-match2">'
        '<script src="/assets/hpoint-guest.js?v=20261107-match2"></script>' + marker, 1)
