"""Конфигурация и константы H-Point."""
import os
DB_PATH = os.getenv('DB_PATH', os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'hpoint.db')))
START_BALANCE = 100
REQUEST_COST = 10
HELPER_REWARD = 20
BOOST_COST = 15
BOOST_HOURS = 24
MAX_TEXT_LEN = 500
MAX_NAME_LEN = 50
HISTORY_LIMIT = 10
BTN_NEED_HELP = '🆘 Мне нужна помощь'
BTN_WANT_HELP = '🤝 Хочу помочь'
BTN_PROFILE = '👤 Мой профиль'
BTN_HISTORY = '📜 История'
BTN_SETTINGS = '⚙️ Настройки помощи'
BTN_CANDIDATES = '👥 Мои кандидаты'
BTN_MY_OFFERS = '📨 Мои отклики'
BTN_CANCEL = '❌ Отмена'
BTN_NO_DETAILS = 'Нет'
CATEGORIES = {'carry':'📦 Перенос / переезд','shopping':'🛒 Покупки','snow':'❄️ Снег / уборка','tools':'🔧 Инструменты / вещи','transport':'🚗 Транспорт','tech':'💻 Техника','study':'📚 Учёба','other':'🧩 Другое'}
CATEGORY_KEYWORDS = {'carry':('короб','переезд','донест','перенест','мебел','шкаф'),'shopping':('магазин','покупк','продукт','купить','аптек'),'snow':('снег','уборк','лопат','расчист'),'tools':('инструмент','одолж','дрел','ключ','вещь'),'transport':('машин','авто','перевез','транспорт','подвез'),'tech':('компьютер','ноутбук','телефон','принтер','настроить','техник'),'study':('учеб','математ','физик','информатик','урок','домашк')}
URGENCY_OPTIONS = ['🔥 Очень срочно','⏳ В течение дня','🕊 Не срочно']
STATUS_OPEN='open'; STATUS_IN_PROGRESS='in_progress'; STATUS_DONE='done'; STATUS_CANCELLED='cancelled'
STATUS_TITLES={STATUS_OPEN:'Ожидает выбора',STATUS_IN_PROGRESS:'В работе',STATUS_DONE:'Завершена',STATUS_CANCELLED:'Отменена'}
APP_PENDING='pending'; APP_ACCEPTED='accepted'; APP_REJECTED='rejected'
