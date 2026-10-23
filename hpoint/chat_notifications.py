"""One safe notification format for the website and Telegram chat relay."""
from html import escape


def chat_notification(request_id: int, sender_name: str, text: str) -> str:
    # Chat input is capped at 1000 characters on both channels. Escape before
    # HTML delivery so a participant cannot inject links or bot formatting.
    return (
        f"💬 <b>{escape(str(sender_name or 'Участник')[:80])}</b> · заявка №{int(request_id)}\n\n"
        f"{escape(str(text)[:1000])}\n\n"
        f"Ответить в этот чат:\n<code>/chat #{int(request_id)} ваш ответ</code>"
    )
