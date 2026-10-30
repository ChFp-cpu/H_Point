"""One escaped notification format for the website and linked bot."""
from html import escape
from .config import WEB_PUBLIC_URL


def chat_notification(request_id: int, sender_name: str, text: str, request_title=None, chat_id=None) -> str:
    header,footer=_parts(request_id,sender_name,request_title,chat_id)
    return header+escape(str(text))+footer


def _parts(request_id,sender_name,request_title=None,chat_id=None):
    title=str(request_title or "Помощь")[:160]
    link=WEB_PUBLIC_URL.rstrip("/")+"/#/help/chat/"+str(int(request_id))
    if chat_id is not None:link+="/"+str(int(chat_id))
    return (f"💬 <b>{escape(str(sender_name or 'Участник')[:80])}</b> · {escape(title)}\n\n",
            f'\n\n<a href="{escape(link,quote=True)}">Открыть чат по этой помощи</a>')


def chat_notification_chunks(request_id: int,sender_name: str,text: str,request_title=None,chat_id=None) -> list[str]:
    """Keep all message characters and split before escaping, never inside HTML.

    The site's 1,000-character message limit is unchanged. Conservative encoded
    chunks also handle long escaped strings and UTF-16 emoji safely in Telegram.
    No subscription checks or promotional text belong in message delivery.
    """
    header,footer=_parts(request_id,sender_name,request_title,chat_id)
    budget=3800-len(header)-len(footer)
    chunks=[];current=[];length=0
    for char in str(text):
        encoded=escape(char)
        size=max(len(encoded),len(char.encode("utf-16-le"))//2)
        if current and length+size>budget:
            chunks.append("".join(current));current=[];length=0
        current.append(encoded);length+=size
    if current or not chunks:chunks.append("".join(current))
    return [header+part+footer for part in chunks]
