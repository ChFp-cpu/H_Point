"""H-Point configuration."""
import os

APP_ENV = os.getenv("APP_ENV", "development").strip().lower()

DB_PATH = os.getenv("DB_PATH", "hpoint.db")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))
WEB_PUBLIC_URL = os.getenv("WEB_PUBLIC_URL", f"http://{WEB_HOST}:{WEB_PORT}")
_cookie_secure_value = os.getenv("SESSION_COOKIE_SECURE", "").strip()
SESSION_COOKIE_SECURE = (
    _cookie_secure_value.lower() in ("1", "true", "yes")
    if _cookie_secure_value
    else WEB_PUBLIC_URL.startswith("https://")
)
BOT_USERNAME = os.getenv("BOT_USERNAME", "").lstrip("@").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
RUN_TELEGRAM_BOT = os.getenv("RUN_TELEGRAM_BOT", "1").strip().lower() not in ("0", "false", "no", "off")
TRUST_PROXY_HEADERS = os.getenv("TRUST_PROXY_HEADERS", "").strip().lower() in ("1", "true", "yes")
SESSION_TTL = int(os.getenv("SESSION_TTL", str(60 * 60 * 24 * 14)))
ADMIN_TELEGRAM_IDS = {int(value) for value in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",") if value.strip().isdigit()}
AI_REQUESTS_PER_DAY = int(os.getenv("AI_REQUESTS_PER_DAY", "20"))
AI_TOKENS_PER_DAY = int(os.getenv("AI_TOKENS_PER_DAY", "20000"))
START_BALANCE = 100
REQUEST_COST = 10
HELPER_REWARD = 20
MAX_TEXT_LEN = 500
MAX_NAME_LEN = 50
HISTORY_LIMIT = 20
AUTH_ATTEMPT_LIMIT = int(os.getenv("AUTH_ATTEMPT_LIMIT", "5"))
AUTH_ATTEMPT_WINDOW_SECONDS = int(os.getenv("AUTH_ATTEMPT_WINDOW_SECONDS", str(15 * 60)))
TELEGRAM_AUTH_TTL_SECONDS = int(os.getenv("TELEGRAM_AUTH_TTL_SECONDS", "300"))
TELEGRAM_LINK_TTL_SECONDS = int(os.getenv("TELEGRAM_LINK_TTL_SECONDS", "600"))
EMAIL_VERIFICATION_TTL_SECONDS = int(os.getenv("EMAIL_VERIFICATION_TTL_SECONDS", "600"))
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "2525"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "").strip()
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "1").strip().lower() not in ("0", "false", "no", "off")
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "0").strip().lower() in ("1", "true", "yes", "on")
SMTP_TIMEOUT_SECONDS = int(os.getenv("SMTP_TIMEOUT_SECONDS", "10"))
MAX_PAYMENT_BODY = int(os.getenv("MAX_PAYMENT_BODY", "10000"))

BTN_NEED_HELP = "🆘 Мне нужна помощь"
BTN_WANT_HELP = "🤝 Хочу помочь"
BTN_FIND_CANDIDATES = "⚡ Подобрать кандидатов"
BTN_MY_CANDIDATES = "👥 Мои кандидаты"
BTN_PROFILE = "👤 Мой профиль"
BTN_HISTORY = "📜 История"
BTN_SETTINGS = "⚙️ Настройки помощи"
BTN_WEBSITE = "🌐 Перейти на сайт"
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

# External acquiring for website checkout. In-bot sales are disabled.
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
    "boost":{"title":"Продвижение заявки","description":"Приоритет заявки в Smart Match","rub":PRICE_BOOST_RUB,"hp":25},
    "more_responses":{"title":"Больше откликов","description":"Повышенный приоритет заявки","rub":PRICE_MORE_RESPONSES_RUB,"hp":40},
    "pro":{"title":"H-Point PRO","description":"PRO-доступ на 30 дней","rub":PRICE_PRO_RUB,"hp":180},
    "verification":{"title":"Проверка личности","description":"Рассмотрение заявки после привязки Telegram","rub":PRICE_VERIFICATION_RUB,"hp":70},
    "favorites":{"title":"Избранное+","description":"Дополнительные слоты избранных","rub":PRICE_FAVORITES_RUB,"hp":90},
    "business":{"title":"H-Point Business","description":"Business-доступ на 30 дней","rub":PRICE_BUSINESS_RUB,"hp":600},
    "business_pro":{"title":"H-Point Business Pro","description":"Расширенный Business на 30 дней","rub":PRICE_BUSINESS_PRO_RUB,"hp":900},
    "ad":{"title":"Локальное объявление","description":"Размещение объявления на 7 дней","rub":PRICE_AD_RUB,"hp":120},
}

def validate_production_config() -> None:
    """Fail fast rather than launch a publicly unsafe production instance."""
    if APP_ENV not in {"production", "prod"}:
        return
    issues = []
    if not DATABASE_URL.startswith(("postgres://", "postgresql://")):
        issues.append("DATABASE_URL must point to PostgreSQL")
    if not WEB_PUBLIC_URL.startswith("https://"):
        issues.append("WEB_PUBLIC_URL must start with https://")
    if not SESSION_COOKIE_SECURE:
        issues.append("SESSION_COOKIE_SECURE must be enabled")
    if RUN_TELEGRAM_BOT and not BOT_TOKEN:
        issues.append("BOT_TOKEN is required")
    if BOT_TOKEN and not BOT_USERNAME:
        issues.append("BOT_USERNAME is required for Telegram website login")
    if not TRUST_PROXY_HEADERS:
        issues.append("TRUST_PROXY_HEADERS must be enabled behind Caddy")
    if issues:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(issues))
