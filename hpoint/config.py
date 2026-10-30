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
# RUB campaign credit is separate from H-Points. Set 0 to stop new grants.
REGISTRATION_BONUS_RUB = max(0, int(os.getenv("REGISTRATION_BONUS_RUB", "0")))
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
PHONE_VERIFICATION_TTL_SECONDS = int(os.getenv("PHONE_VERIFICATION_TTL_SECONDS", "600"))
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "2525"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "").strip()
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "1").strip().lower() not in ("0", "false", "no", "off")
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "0").strip().lower() in ("1", "true", "yes", "on")
SMTP_TIMEOUT_SECONDS = int(os.getenv("SMTP_TIMEOUT_SECONDS", "10"))
# A transactional SMS provider is optional.  The UI never claims that a phone
# is verified until a code was actually sent and checked.
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "").strip()
SMS_SENDER = os.getenv("SMS_SENDER", "HPoint").strip()
YANDEX_MAPS_API_KEY = os.getenv("YANDEX_MAPS_API_KEY", "").strip()
DONATION_URL = os.getenv("DONATION_URL", "").strip()
DONATION_TITLE = os.getenv("DONATION_TITLE", "Поддержать H-Point").strip()[:80]
EVENT_IMAGE_MAX_BYTES = int(os.getenv("EVENT_IMAGE_MAX_BYTES", "800000"))
MAX_PAYMENT_BODY = int(os.getenv("MAX_PAYMENT_BODY", "10000"))

# H-Point Games economy.  These are deliberately server-side values: the
# browser only receives the resulting balance and can never choose a reward.
GAME_REWARD_TIMEZONE = os.getenv("GAME_REWARD_TIMEZONE", "Europe/Moscow").strip() or "Europe/Moscow"
GAME_DAILY_REWARD_CAP = int(os.getenv("GAME_DAILY_REWARD_CAP", "15"))
GAME_PER_TITLE_REWARD_CAP = int(os.getenv("GAME_PER_TITLE_REWARD_CAP", "3"))
GAME_SESSION_TTL_SECONDS = int(os.getenv("GAME_SESSION_TTL_SECONDS", str(60 * 45)))
GAME_ACTION_MIN_INTERVAL_MS = int(os.getenv("GAME_ACTION_MIN_INTERVAL_MS", "110"))

# Scores are evaluated by the server against these thresholds.  The values
# express the *daily total* for a title, so improving a result only grants the
# difference that has not already been issued on that day.
GAME_REWARD_THRESHOLDS = {
    "crossing": ((90, 1), (180, 2), (290, 3)),
    "dispatch": ((180, 1), (420, 2), (650, 3)),
    "match": ((180, 1), (420, 2), (720, 3)),
    "safety": ((3, 1), (5, 2), (6, 3)),
    "mission": ((3, 1), (5, 2), (7, 3)),
}

BTN_NEED_HELP = "🆘 Мне нужна помощь"
BTN_WANT_HELP = "🤝 Хочу помочь"
BTN_FIND_CANDIDATES = "⚡ Подобрать кандидатов"
BTN_MY_CANDIDATES = "👥 Мои кандидаты"
BTN_PROFILE = "👤 Мой профиль"
BTN_HISTORY = "📜 История"
BTN_SETTINGS = "⚙️ Настройки помощи"
BTN_WEBSITE = "🌐 Перейти на сайт"
BTN_GAMES = "🎮 Игры H-Point"
BTN_NAVIGATOR = "ℹ️ Как пользоваться"
BTN_CANCEL = "❌ Отмена"
BTN_NO_DETAILS = "Нет"

# One catalogue powers request forms, helper preferences, filters and the League.
# Stable keys deliberately retain the original eight categories and saved choices.
CATEGORY_GROUPS = [
    {"key": "home", "title": "Дом и ремонт"},
    {"key": "errands", "title": "Дела и забота"},
    {"key": "learning", "title": "Учёба и цифровая помощь"},
    {"key": "leisure", "title": "Досуг и общее дело"},
    {"key": "other", "title": "Другое"},
]


def _help_category(key, label, icon, group, hint):
    return {"key": key, "label": label, "icon": icon, "title": icon + " " + label,
            "group": group, "hint": hint}


CATEGORY_CATALOG = [
    _help_category("carry", "Перенос / переезд", "📦", "home", "Донести коробки, перенести вещи, помочь с переездом"),
    _help_category("cleaning", "Уборка дома", "🧹", "home", "Убрать квартиру, помыть окна, разобрать вещи"),
    _help_category("snow", "Снег и уборка территории", "❄️", "home", "Расчистить дорожку, убрать снег или мусор во дворе"),
    _help_category("repairs", "Мелкий ремонт", "🛠️", "home", "Повесить полку, закрепить карниз, починить ручку"),
    _help_category("plumbing", "Сантехника", "🚰", "home", "Заменить смеситель, устранить течь, подключить сантехнику"),
    _help_category("electric", "Электрика", "💡", "home", "Розетки, выключатели, светильники — помощь специалиста"),
    _help_category("furniture", "Сборка мебели", "🪑", "home", "Собрать или разобрать шкаф, стол, кровать"),
    _help_category("garden", "Сад и растения", "🌱", "home", "Полить цветы, пересадить растения, помочь на участке"),
    _help_category("tools", "Инструменты / вещи", "🔧", "home", "Одолжить инструмент или нужную вещь"),
    _help_category("shopping", "Покупки", "🛒", "errands", "Купить продукты, лекарства по списку или другие товары"),
    _help_category("delivery", "Доставка и поручения", "📬", "errands", "Забрать посылку, передать документы, выполнить поручение"),
    _help_category("transport", "Транспорт", "🚗", "errands", "Подвезти человека или перевезти груз"),
    _help_category("pets", "Забота о животных", "🐾", "errands", "Выгулять собаку, покормить питомца, присмотреть за котом"),
    _help_category("elderly", "Помощь пожилым", "🤲", "errands", "Бытовые дела, общение и сопровождение пожилого человека"),
    _help_category("children", "Помощь с детьми", "🧸", "errands", "Присмотр, сопровождение и занятия с ребёнком"),
    _help_category("accompany", "Сопровождение", "🚶", "errands", "Встретить, проводить или составить компанию в поездке"),
    _help_category("tech", "Техника", "💻", "learning", "Настроить компьютер, телефон, принтер или интернет"),
    _help_category("study", "Учёба", "📚", "learning", "Разобрать задание, подготовиться к уроку или экзамену"),
    _help_category("languages", "Языки и перевод", "🌍", "learning", "Перевести текст, попрактиковать язык, разобрать произношение"),
    _help_category("documents", "Документы и тексты", "📄", "learning", "Заполнить форму, оформить резюме, отредактировать текст"),
    _help_category("design", "Дизайн и творчество", "🎨", "learning", "Сделать макет, презентацию, афишу или иллюстрацию"),
    _help_category("sport", "Спорт и тренировки", "🏃", "leisure", "Найти партнёра для пробежки или помощь с тренировкой"),
    _help_category("cooking", "Готовка", "🍳", "leisure", "Приготовить еду, освоить рецепт, помочь на кухне"),
    _help_category("sewing", "Шитьё и одежда", "🧵", "leisure", "Подшить брюки, пришить пуговицу, починить одежду"),
    _help_category("photo", "Фото и видео", "📷", "leisure", "Провести съёмку, обработать фото, смонтировать видео"),
    _help_category("events", "Помощь на мероприятиях", "🎈", "leisure", "Подготовить площадку, встретить гостей, помочь организатору"),
    _help_category("volunteering", "Волонтёрство", "💚", "leisure", "Помочь приюту, благотворительной акции или общему делу"),
    _help_category("other", "Другое", "🧩", "other", "Если подходящего направления нет — опишите задачу своими словами"),
]
CATEGORIES = {item["key"]: item["title"] for item in CATEGORY_CATALOG}
CATEGORY_KEYWORDS = {
    "carry": ("короб", "переезд", "донест", "перенест", "перенос", "мебел", "шкаф", "погруз", "разгруз"),
    "cleaning": ("уборк", "убрат", "помыт", "мыть", "окна", "клининг", "пылесос", "разобрат вещи"),
    "snow": ("снег", "расчист", "снеж", "убрат двор", "уборк территор", "уборк двор", "убрат мусор"),
    "repairs": ("ремонт", "полк", "карниз", "плинтус", "повесит", "дверн ручк", "покрасит", "обои"),
    "plumbing": ("сантех", "смесител", "кран", "унитаз", "раковин", "сифон", "протеч", "течет", "засор"),
    "electric": ("электрик", "розетк", "выключател", "светильник", "люстр", "проводк", "лампоч"),
    "furniture": ("собрат шкаф", "собрат мебел", "собрат стол", "собрат стул", "собрат кроват", "сборк мебел", "сборк шкаф", "разобрат шкаф", "разобрат мебел", "мебельщик"),
    "garden": ("сад", "огород", "рассад", "растен", "полит цвет", "полив", "пересад", "пропол", "газон", "дерев"),
    "tools": ("инструмент", "одолж", "дрел", "шуруповерт", "лестниц", "одолжит вещ"),
    "shopping": ("магазин", "покупк", "продукт", "купит", "аптек"),
    "delivery": ("достав", "посылк", "курьер", "поручен", "забрат заказ", "передат документ", "пункт выдач"),
    "transport": ("машин", "авто", "перевез", "транспорт", "подвез", "довез", "водител"),
    "pets": ("собак", "кот", "котен", "кошк", "питом", "животн", "выгул", "покормит"),
    "elderly": ("пожил", "пенсионер", "бабушк", "дедушк"),
    "children": ("ребен", "детьми", "детей", "няня", "няню", "детск сад", "забрат школ"),
    "accompany": ("сопровод", "сопровожд", "встретит", "проводит", "составит компан"),
    "tech": ("компьютер", "ноутбук", "телефон", "принтер", "настроит", "техник", "интернет", "роутер", "wi-fi", "вайфай"),
    "study": ("учеб", "математ", "физик", "информатик", "урок", "домашк", "репетитор", "экзамен", "егэ", "огэ"),
    "languages": ("английск", "немецк", "французск", "испанск", "китайск", "перевод", "перевест текст", "иностранн язык", "произношен"),
    "documents": ("документ", "резюме", "заявлен", "анкет", "редактур", "отредактир", "написат текст", "заполнит форм", "корректур"),
    "design": ("дизайн", "макет", "афиш", "логотип", "презентац", "иллюстрац", "нарисоват"),
    "sport": ("спорт", "трениров", "пробеж", "фитнес", "тренер", "зарядк", "плаван", "соревнован"),
    "cooking": ("готовк", "приготов", "рецепт", "кулинар", "испеч", "повар", "пирог", "торт", "ужин", "обед"),
    "sewing": ("шить", "швея", "подшит", "зашит", "пришит", "пуговиц", "брюк", "одежд", "штоп"),
    "photo": ("фото", "фотограф", "фотосъем", "видео", "съемк", "сфотограф", "монтаж", "смонтир", "ретуш"),
    "events": ("мероприят", "праздник", "свадьб", "гостей", "фестивал", "концерт", "день рожден"),
    "volunteering": ("волонтер", "благотвор", "приют", "субботник", "добровол", "сбор помощ"),
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
PRICE_PRO_RUB = 149
PRICE_VERIFICATION_RUB = 99
PRICE_FAVORITES_RUB = 149
PRICE_BUSINESS_RUB = 999
PRICE_BUSINESS_PRO_RUB = 1499
PRICE_AD_RUB = 199
MONETIZATION_ITEMS = {
    "pro":{"title":"H-Point PRO","description":"Для личных задач: до 5 активных заявок, активности без месячного лимита, шаблоны и повторы по расписанию. Управление помощью через Telegram и мягкий приоритет среди подходящих вариантов.","rub":PRICE_PRO_RUB,"hp":90,"term":"30 дней · без автопродления","benefits":["До 5 собственных активных заявок вместо 1","Активности без месячного лимита вместо 2 публикаций","Личные шаблоны и повторы по расписанию","Управление заявками через привязанный Telegram","Мягкий приоритет; без гарантии помощников или откликов"]},
}
# Historical invoice descriptions only. Never offer these for a new purchase;
# existing invoices and paid entitlements must remain fulfillable.
LEGACY_MONETIZATION_ITEMS = {
    "boost":{"title":"Продвижение заявки","description":"Ранее оплаченное продвижение одной заявки","rub":PRICE_BOOST_RUB,"hp":25},
    "more_responses":{"title":"Больше откликов","description":"Повышенный приоритет заявки","rub":PRICE_MORE_RESPONSES_RUB,"hp":40},
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
