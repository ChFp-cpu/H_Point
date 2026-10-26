"""One escaped notification format for the website and linked bot."""
from html import escape
from .config import WEB_PUBLIC_URL


def chat_notification(request_id: int, sender_name: str, text: str, request_title=None) -> str:
    title=str(request_title or "Помощь")[:160]
    link=WEB_PUBLIC_URL.rstrip("/")+"/#/help/chat/"+str(int(request_id))
    return (f"💬 <b>{escape(str(sender_name or 'Участник')[:80])}</b> · {escape(title)}\n\n"
            f"{escape(str(text)[:1000])}\n\n"
            f'<a href="{escape(link,quote=True)}">Открыть чат по этой помощи</a>')
