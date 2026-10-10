"""H-Point configuration."""
import os

DB_PATH = os.getenv("DB_PATH", "hpoint.db")
WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))
WEB_PUBLIC_URL = os.getenv("WEB_PUBLIC_URL", f"http://{WEB_HOST}:{WEB_PORT}")
_cookie_secure_value = os.getenv("SESSION_COOKIE_SECURE", "").strip()
SESSION_COOKIE_SECURE = (
    _cookie_secure_value.lower() in ("1", "true", "yes")
    if _cookie_secure_value
    else WEB_PUBLIC_URL.startswith("https://")
)
YANDEX_MAPS_API_KEY = os.getenv("YANDEX_MAPS_API_KEY", "")
SESSION_TTL = int(os.getenv("SESSION_TTL", str(60 * 60 * 24 * 14)))
START_BALANCE = 100
REQUEST_COST = 10
HELPER_REWARD = 20
MAX_TEXT_LEN = 500
MAX_NAME_LEN = 50
HISTORY_LIMIT = 20

BTN_NEED_HELP = "🆘 Мне нужна помощь"
BTN_WANT_HELP = "🤝 Хочу помочь"
BTN_FIND_CANDIDATES = "⚡ Подобрать кандидатов"
BTN_MY_CANDIDATES = "👥 Мои кандидаты"
BTN_PROFILE = "👤 Мой профиль"
BTN_HISTORY = "📜 История"
BTN_SETTINGS = "⚙️ Настройки помощи"
BTN_CANCEL = "❌ Отмена"
BTN_NO_DETAILS = "Нет"

CATEGORIES = {
    "carry": "📦 Перенос / переезд", "shopping": "🛒 Покупки",
    "snow": "❄️ Снег / уборка", "tools": "🔧 Инструменты / вещи",
    "transport": "🚗 Транспорт", "tech": "💻 Техника",
    "study": "📚 Учёба", "other": "🧩 Другое",
}
CATEGORY_KEYWORDS = {
    "carry": ("короб","переезд","донест","перенест","мебел","шкаф"),
    "shopping": ("магазин","покупк","продукт","купить","аптек"),
    "snow": ("снег","уборк","лопат","расчист"),
    "tools": ("инструмент","одолж","дрел","ключ","вещь"),
    "transport": ("машин","авто","перевез","транспорт","подвез"),
    "tech": ("компьютер","ноутбук","телефон","принтер","настроить","техник"),
    "study": ("учеб","математ","физик","информатик","урок","домашк"),
}
URGENCY_OPTIONS = ["🔥 Очень срочно", "⏳ В течение дня", "🕊 Не срочно"]
STATUS_OPEN, STATUS_IN_PROGRESS, STATUS_DONE, STATUS_CANCELLED = "open","in_progress","done","cancelled"
STATUS_TITLES = {STATUS_OPEN:"Ожидает помощника",STATUS_IN_PROGRESS:"В работе",STATUS_DONE:"Завершена",STATUS_CANCELLED:"Отменена"}

# External acquiring for website checkout. Telegram in-bot sales are disabled;
# Telegram requires Stars for digital goods and services sold inside its apps.
PAYMENT_CURRENCY = "RUB"
ROBOKASSA_MERCHANT_LOGIN = os.getenv("ROBOKASSA_MERCHANT_LOGIN", "")
ROBOKASSA_PASSWORD_1 = os.getenv("ROBOKASSA_PASSWORD_1", "")
ROBOKASSA_PASSWORD_2 = os.getenv("ROBOKASSA_PASSWORD_2", "")
ROBOKASSA_HASH_ALGORITHM = os.getenv("ROBOKASSA_HASH_ALGORITHM", "SHA256").upper()
ROBOKASSA_RESULT_URL = os.getenv("ROBOKASSA_RESULT_URL", WEB_PUBLIC_URL + "/api/payments/robokassa/result")
PAYMENT_SUCCESS_URL = os.getenv("PAYMENT_SUCCESS_URL", WEB_PUBLIC_URL + "/payment/result?status=success")
PAYMENT_FAIL_URL = os.getenv("PAYMENT_FAIL_URL", WEB_PUBLIC_URL + "/payment/result?status=fail")

PRICE_BOOST_RUB = 49
PRICE_MORE_RESPONSES_RUB = 79
PRICE_PRO_RUB = 299
PRICE_VERIFICATION_RUB = 99
PRICE_FAVORITES_RUB = 149
PRICE_BUSINESS_RUB = 999
PRICE_BUSINESS_PRO_RUB = 1499
PRICE_AD_RUB = 199
MONETIZATION_ITEMS = {
    "boost":{"title":"Продвижение заявки","description":"Приоритет заявки в Smart Match","rub":PRICE_BOOST_RUB},
    "more_responses":{"title":"Больше откликов","description":"Повышенный приоритет заявки","rub":PRICE_MORE_RESPONSES_RUB},
    "pro":{"title":"H-Point PRO","description":"PRO-доступ на 30 дней","rub":PRICE_PRO_RUB},
    "verification":{"title":"Верификация","description":"Проверенный профиль на 365 дней","rub":PRICE_VERIFICATION_RUB},
    "favorites":{"title":"Избранное+","description":"Дополнительные слоты избранных","rub":PRICE_FAVORITES_RUB},
    "business":{"title":"H-Point Business","description":"Business-доступ на 30 дней","rub":PRICE_BUSINESS_RUB},
    "business_pro":{"title":"H-Point Business Pro","description":"Расширенный Business на 30 дней","rub":PRICE_BUSINESS_PRO_RUB},
    "ad":{"title":"Локальное объявление","description":"Размещение объявления на 7 дней","rub":PRICE_AD_RUB},
}
