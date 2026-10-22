"""Server-authoritative H-Point Games rules, progress and economy.

The browser renders each game, but never supplies a score or a reward.  It
only submits small, validated game actions to an expiring server-side session.
That keeps the existing H-Points balance safe from edited JavaScript or replayed
completion requests while still allowing the games to feel like normal web
games.
"""
from __future__ import annotations

import copy
import json
import random
import re
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import database
from .game_content import (
    CONTENT_VERSION,
    LEARNING_SESSION_LENGTH,
    MISSION_SCENARIOS as CONTENT_MISSION_SCENARIOS,
    SAFETY_SCENARIOS as CONTENT_SAFETY_SCENARIOS,
    published_scenarios,
)
from .config import (
    GAME_ACTION_MIN_INTERVAL_MS,
    GAME_DAILY_REWARD_CAP,
    GAME_PER_TITLE_REWARD_CAP,
    GAME_REWARD_THRESHOLDS,
    GAME_REWARD_TIMEZONE,
    GAME_SESSION_TTL_SECONDS,
)


GAME_CATALOG = {
    "crossing": {
        "title": "H-Crossing: Дорога помощи",
        "short_title": "H-Crossing",
        "genre": "Аркада",
        "difficulty": "Средняя",
        "description": "Проведите посылку через живой город, собирая ресурсы и доставляя помощь по пути.",
        "award": "до 3 HP в сутки",
        "accent": "mint",
    },
    "dispatch": {
        "title": "H-Dispatch: Центр помощи",
        "short_title": "H-Dispatch",
        "genre": "Стратегия",
        "difficulty": "Продвинутая",
        "description": "Распределяйте волонтёров по заявкам с учётом навыков, расстояния и срочности.",
        "award": "до 3 HP в сутки",
        "accent": "sun",
    },
    "match": {
        "title": "H-Match: Собери помощь",
        "short_title": "H-Match",
        "genre": "Match-3",
        "difficulty": "Средняя",
        "description": "Собирайте наборы полезных вещей, запускайте каскады и выполняйте цели уровня.",
        "award": "до 3 HP в сутки",
        "accent": "violet",
    },
    "safety": {
        "title": "H-Safety: Академия безопасности",
        "short_title": "H-Safety",
        "genre": "Интерактивный курс",
        "difficulty": "Доступная",
        "description": "Тренируйте безопасные решения в интернете и на платформе взаимопомощи.",
        "award": "до 3 HP в сутки",
        "accent": "blue",
    },
    "mission": {
        "title": "H-Mission: Школа добрых дел",
        "short_title": "H-Mission",
        "genre": "Сюжетный симулятор",
        "difficulty": "Доступная",
        "description": "Выбирайте бережные и ответственные способы помочь в жизненных ситуациях.",
        "award": "до 3 HP в сутки",
        "accent": "coral",
    },
}

# All purchasable effects are local to Games and do not alter the core
# request/payment flows.  Cosmetic items are sent to the client only when the
# player explicitly equips them; utility items are consumed by server rules.
STORE_ITEMS = {
    "crossing_leaf_trail": {
        "game": "crossing", "category": "effects", "price": 5,
        "title": "След добрых дел", "description": "Мятный след и мягкое свечение для героя.", "effect": "trail",
    },
    "crossing_wayfinder": {
        "game": "crossing", "category": "upgrades", "price": 10,
        "title": "Маршрут-проводник", "description": "Один щит от столкновения в каждой новой игре.", "effect": "shield",
    },
    "dispatch_signal": {
        "game": "dispatch", "category": "skins", "price": 5,
        "title": "Сигнал команды", "description": "Новый цвет маркеров команды на карте центра.", "effect": "signal",
    },
    "dispatch_radio": {
        "game": "dispatch", "category": "upgrades", "price": 10,
        "title": "Рация координатора", "description": "Даёт бонус к очкам за каждое верное назначение.", "effect": "radio",
    },
    "match_supply_palette": {
        "game": "match", "category": "skins", "price": 5,
        "title": "Набор ресурсов", "description": "Меняет палитру предметов на поле.", "effect": "palette",
    },
    "match_hint": {
        "game": "match", "category": "abilities", "price": 10,
        "title": "Умная подсказка", "description": "Одна серверная подсказка о возможном ходе в каждой игре.", "effect": "hint",
    },
    "safety_compass": {
        "game": "safety", "category": "effects", "price": 5,
        "title": "Компас безопасности", "description": "Выделяет ключевой принцип в разборе каждой ситуации.", "effect": "compass",
    },
    "mission_storybook": {
        "game": "mission", "category": "characters", "price": 10,
        "title": "Дневник помощника", "description": "Открывает добрый визуальный стиль сюжетных карточек.", "effect": "storybook",
    },
}

ACHIEVEMENTS = {
    "first_steps": {"title": "Первые шаги", "description": "Завершите первую игру.", "hp": 1},
    "crossing_helper": {"title": "Помощник в пути", "description": "Наберите 180 очков в H-Crossing.", "hp": 1},
    "dispatch_organizer": {"title": "Организатор", "description": "Выполните 5 заявок в H-Dispatch.", "hp": 1},
    "match_combo": {"title": "Комбо-мастер", "description": "Соберите каскад из 3 волн в H-Match.", "hp": 1},
    "safety_expert": {"title": "Знаток безопасности", "description": "Дайте не меньше 5 верных ответов в H-Safety.", "hp": 1},
    "mission_helper": {"title": "Настоящий помощник", "description": "Получите репутацию 5+ в H-Mission.", "hp": 1},
    "all_rounder": {"title": "Универсальный помощник", "description": "Завершите все пять игр.", "hp": 1},
}

DAILY_CHALLENGES = {
    "daily_start": {"title": "На связи", "description": "Завершите любую игру сегодня.", "hp": 1},
    "daily_learning": {"title": "Безопасный выбор", "description": "Пройдите образовательную игру с результатом 3+.", "hp": 1},
}

SAFETY_SCENARIOS = (
    {
        "level": "Базовый", "title": "Слишком выгодная заявка",
        "scene": "В заявке обещают крупную награду, но просят заранее оплатить «страховку» переводом незнакомцу.",
        "question": "Как поступить безопаснее всего?",
        "choices": (
            "Перевести небольшую сумму: риск кажется минимальным.",
            "Не переводить деньги, пожаловаться на заявку и прекратить диалог вне платформы.",
            "Попросить прислать фото паспорта и продолжить разговор.",
        ),
        "correct": 1,
        "explanation": "Не переводите деньги незнакомцам ради обещания работы. Используйте жалобу и официальный канал поддержки.",
        "principle": "Сомнительные предоплаты — повод остановиться и проверить заявку.",
    },
    {
        "level": "Базовый", "title": "Код подтверждения",
        "scene": "Собеседник представляется сотрудником поддержки и просит назвать код из SMS, чтобы «закрыть заявку».",
        "question": "Что нужно сделать?",
        "choices": (
            "Не сообщать код; завершить разговор и написать в поддержку через сайт.",
            "Сообщить только первые две цифры кода.",
            "Переслать сообщение с кодом, если собеседник знает ваше имя.",
        ),
        "correct": 0,
        "explanation": "Коды из SMS, пуш-уведомлений и приложения — ключи к аккаунту. Поддержка никогда не просит их сообщать.",
        "principle": "Одноразовый код нельзя передавать никому.",
    },
    {
        "level": "Стандарт", "title": "Личные данные",
        "scene": "Перед откликом на просьбу о помощи у вас просят в чате отправить паспортные данные и полный адрес проживания.",
        "question": "Какая реакция ответственна?",
        "choices": (
            "Отправить всё, чтобы показать серьёзность намерений.",
            "Поделиться только городом и попросить согласовать детали через безопасный канал после взаимного решения.",
            "Опубликовать данные в комментариях, чтобы быстрее найти помощника.",
        ),
        "correct": 1,
        "explanation": "Делитесь минимально необходимой информацией. Точный адрес и документы не нужны для первого безопасного контакта.",
        "principle": "Минимизируйте персональные данные до подтверждения необходимости.",
    },
    {
        "level": "Стандарт", "title": "Подозрительная ссылка",
        "scene": "В чате приходит ссылка на страницу, похожую на H-Point, с просьбой срочно войти и подтвердить профиль.",
        "question": "Как лучше проверить ссылку?",
        "choices": (
            "Открыть её и сразу ввести пароль, пока ссылка активна.",
            "Проверить адрес сайта, не вводить данные и открыть H-Point вручную в новой вкладке.",
            "Переслать ссылку друзьям и спросить, работает ли она.",
        ),
        "correct": 1,
        "explanation": "Не вводите пароль по ссылке из сообщения. Наберите адрес сервиса самостоятельно и сообщите о фишинге.",
        "principle": "Адрес сайта и способ входа проверяются до ввода данных.",
    },
    {
        "level": "Продвинутый", "title": "Давление в переписке",
        "scene": "Человек торопит вас, просит перейти в мессенджер и угрожает «пожаловаться», если вы не ответите немедленно.",
        "question": "Как сохранить контроль?",
        "choices": (
            "Сделать паузу, сохранить переписку и обратиться к модерации через платформу.",
            "Выполнить всё быстро, чтобы конфликт закончился.",
            "Передать собеседнику доступ к профилю для проверки.",
        ),
        "correct": 0,
        "explanation": "Давление и срочность — частые признаки манипуляции. Вы вправе остановить разговор и использовать инструменты безопасности.",
        "principle": "Никто не может требовать немедленного решения ценой вашей безопасности.",
    },
    {
        "level": "Продвинутый", "title": "Безопасное общение",
        "scene": "Новый участник предлагает встретиться в незнакомом месте поздно вечером, чтобы передать вещи без предварительного согласования.",
        "question": "Какой вариант подходит лучше?",
        "choices": (
            "Согласиться, но никому не говорить, чтобы не отвлекать близких.",
            "Предложить безопасный публичный формат, согласовать детали в платформе и отказаться, если границы не уважают.",
            "Сразу отправить домашний адрес, чтобы сэкономить время.",
        ),
        "correct": 1,
        "explanation": "Безопасная помощь строится на согласии, понятных границах и публичных, подходящих условиях встречи.",
        "principle": "Ваши границы и безопасный формат важнее спешки.",
    },
)

MISSION_SCENARIOS = (
    {
        "title": "Задача по математике", "person": "Саша", "place": "после уроков",
        "scene": "Одноклассник не понимает тему и просит помочь перед контрольной.",
        "choices": (
            ("Спросить, какая именно часть непонятна, и разобрать один пример вместе в удобное время.", 2, "Помощь становится полезнее, когда человек участвует и темп ему подходит."),
            ("Сделать всё за него и отправить готовые ответы.", 0, "Готовые ответы не помогают освоить тему и могут создать проблемы."),
            ("Сказать, что это не ваша проблема.", 0, "Можно честно обозначить свои возможности, но полезно предложить безопасный вариант поддержки."),
        ),
    },
    {
        "title": "Тяжёлые пакеты", "person": "Соседка", "place": "у подъезда",
        "scene": "Соседка просит помочь донести пакеты. Вы спешите, а рядом нет знакомых взрослых.",
        "choices": (
            ("Уточнить, куда именно нужна помощь, предложить короткую безопасную помощь в общедоступном месте или позвать взрослого.", 2, "Согласие, ясные границы и безопасный формат важнее спешки."),
            ("Пойти с незнакомым человеком куда угодно, не сообщая никому.", 0, "Не стоит соглашаться на небезопасные встречи или скрывать их от близких."),
            ("Взять пакеты и оставить их без объяснений у двери.", 1, "Намерение доброе, но сначала лучше согласовать, что именно человеку удобно."),
        ),
    },
    {
        "title": "Потерянная вещь", "person": "Посетитель парка", "place": "в парке",
        "scene": "Человек ищет потерянный ключ и просит помочь обойти площадку.",
        "choices": (
            ("Спросить описание вещи, искать в публичной зоне и при необходимости обратиться к сотруднику парка.", 2, "Так вы помогаете, не рискуя безопасностью и не вторгаясь в чужие границы."),
            ("Опубликовать номер телефона человека в открытом чате без согласия.", 0, "Контактные данные нельзя публиковать без явного согласия."),
            ("Предложить искать поздно вечером в безлюдном месте.", 0, "Время и место помощи должны быть безопасными для всех."),
        ),
    },
    {
        "title": "Неподходящее предложение", "person": "Участница H-Point", "place": "в чате",
        "scene": "Участница получила предложение, которое не соответствует её заявке и вызывает дискомфорт.",
        "choices": (
            ("Поддержать её решение отказаться, подсказать жалобу и не давить с советами.", 2, "Уважение к отказу и безопасные инструменты платформы помогают сохранить контроль."),
            ("Уговорить согласиться, потому что «помощь редко предлагают».", 0, "Никто не обязан соглашаться на неподходящие условия."),
            ("Написать от её имени и выложить переписку публично.", 0, "Не стоит действовать за человека или раскрывать его личную переписку."),
        ),
    },
    {
        "title": "Невыполнимое обещание", "person": "Волонтёр", "place": "в приложении",
        "scene": "Волонтёр понимает, что не успевает выполнить обещанное задание.",
        "choices": (
            ("Сообщить заранее, извиниться и предложить отменить или безопасно найти замену через платформу.", 2, "Раннее честное предупреждение даёт человеку время найти другой вариант."),
            ("Пропасть и надеяться, что никто не заметит.", 0, "Молчание оставляет человека без помощи и без возможности спланировать другой вариант."),
            ("Передать задачу незнакомому человеку без согласования.", 0, "Нельзя передавать чужие данные или обязательства без согласия."),
        ),
    },
)

# The historical inline lists above are kept only so an interrupted upgrade
# can still read an already-persisted legacy session.  New sessions use the
# versioned content source below, which has stable IDs and editorial metadata.
SAFETY_SCENARIOS = CONTENT_SAFETY_SCENARIOS
MISSION_SCENARIOS = CONTENT_MISSION_SCENARIOS

_PURCHASE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{12,128}$")
_TILES = ("food", "book", "tool", "cloth", "kit", "box")


def _db():
    return database.db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_text() -> str:
    return _now().isoformat()


def _reward_day() -> str:
    try:
        return _now().astimezone(ZoneInfo(GAME_REWARD_TIMEZONE)).date().isoformat()
    except Exception:
        return _now().date().isoformat()


def _loads(value, fallback):
    try:
        return json.loads(value) if value else copy.deepcopy(fallback)
    except (TypeError, json.JSONDecodeError):
        return copy.deepcopy(fallback)


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _is_postgres() -> bool:
    return bool(getattr(_db(), "is_postgres", False))


def _lock_sql(sql: str) -> str:
    return sql + (" FOR UPDATE" if _is_postgres() else "")


def _begin() -> None:
    _db().execute("BEGIN IMMEDIATE")


def _rollback() -> None:
    try:
        _db().execute("ROLLBACK")
    except Exception:
        pass


def catalog() -> list[dict]:
    return [{"code": code, **details} for code, details in GAME_CATALOG.items()]


def _ensure_profile(user_id: int) -> None:
    _db().execute("INSERT OR IGNORE INTO game_profiles(user_id) VALUES(?)", (user_id,))


def _owned_item_ids(user_id: int, game_code: str | None = None) -> set[str]:
    sql = "SELECT item_id FROM game_item_ownership WHERE user_id=?"
    params: tuple = (user_id,)
    if game_code:
        ids = tuple(item_id for item_id, item in STORE_ITEMS.items() if item["game"] == game_code)
        if not ids:
            return set()
        placeholders = ",".join("?" for _ in ids)
        sql += f" AND item_id IN ({placeholders})"
        params += ids
    return {row["item_id"] for row in _db().execute(sql, params).fetchall()}


def _equipped_item_ids(user_id: int, game_code: str) -> set[str]:
    allowed = {item_id for item_id, item in STORE_ITEMS.items() if item["game"] == game_code}
    if not allowed:
        return set()
    placeholders = ",".join("?" for _ in allowed)
    rows = _db().execute(
        f"SELECT item_id FROM game_item_ownership WHERE user_id=? AND equipped=1 AND item_id IN ({placeholders})",
        (user_id, *allowed),
    ).fetchall()
    return {row["item_id"] for row in rows}


def _score_target(game_code: str, score: int) -> int:
    earned = 0
    for threshold, hp in GAME_REWARD_THRESHOLDS[game_code]:
        if score >= threshold:
            earned = hp
    return min(GAME_PER_TITLE_REWARD_CAP, earned)


# Crossing advances from server time, not from browser-provided frames.  The
# client receives enough data to draw it smoothly, but score and collisions
# are always calculated against this server clock.
_CROSSING_TICK_MS = 750
_LEGACY_LEARNING_LENGTHS = {"safety": 6, "mission": 5}


def _timestamp_ms(value: str | None) -> int:
    try:
        stamp = datetime.fromisoformat(value or "")
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return int(stamp.timestamp() * 1000)
    except (TypeError, ValueError):
        return int(_now().timestamp() * 1000)


def _select_learning_scenarios(user_id: int, game_code: str) -> list[dict]:
    """Select a frozen, non-repeating learning set for a new session.

    A participant sees each published scenario once before the rotation can
    reuse it.  The final partial batch carries remaining unseen prompts into
    the next cycle without repeating a prompt inside one session.
    """
    catalog_items = list(published_scenarios(game_code))
    if len(catalog_items) < LEARNING_SESSION_LENGTH:
        raise RuntimeError("Недостаточно опубликованных учебных сценариев.")
    seen = {
        row["scenario_id"]
        for row in _db().execute(
            "SELECT scenario_id FROM game_scenario_history WHERE user_id=? AND game_code=?",
            (user_id, game_code),
        ).fetchall()
    }
    unseen = [item for item in catalog_items if item["id"] not in seen]
    rng = secrets.SystemRandom()
    selected = rng.sample(unseen, min(len(unseen), LEARNING_SESSION_LENGTH))
    if len(selected) < LEARNING_SESSION_LENGTH:
        remaining = [item for item in catalog_items if item["id"] not in {scene["id"] for scene in selected}]
        selected.extend(rng.sample(remaining, LEARNING_SESSION_LENGTH - len(selected)))
    for scene in selected:
        _db().execute(
            "INSERT OR IGNORE INTO game_scenario_history(user_id,game_code,scenario_id,content_version) VALUES(?,?,?,?)",
            (user_id, game_code, scene["id"], scene["version"]),
        )
    return copy.deepcopy(selected)


def _learning_scenes(state: dict, game_code: str) -> list[dict]:
    """Return server-side snapshots, retaining sessions begun before 2026.10."""
    snapshots = state.get("scenarios")
    if isinstance(snapshots, list) and snapshots:
        return snapshots
    # Old sessions were ordered against the small original bank.  Keep that
    # order and length so deployment never changes an in-progress lesson.
    return list(published_scenarios(game_code))[:_LEGACY_LEARNING_LENGTHS[game_code]]


def _make_crossing_state(user_id: int, equipped: set[str]) -> dict:
    clock_anchor = _now_text()
    return {
        "seed": secrets.randbelow(2**31 - 1), "player": {"x": 3, "y": 0}, "ticks": 0,
        "elapsed_ms": 0, "clock_anchor_at": clock_anchor, "paused": False,
        "distance": 0, "coins": 0, "deliveries": 0, "collected": [],
        "shield": 1 if "crossing_wayfinder" in equipped else 0,
        "last_notice": "Двигайтесь вперёд: соберите ресурсы и доберитесь до точки помощи.",
        "equipped": sorted(equipped),
    }


def _dispatch_jobs(seed: int) -> list[dict]:
    templates = (
        ("Продукты", "shopping", "food"), ("Передать книгу", "delivery", "book"),
        ("Помочь с уборкой", "cleaning", "broom"), ("Передать вещи", "delivery", "box"),
        ("Разобрать задание", "study", "study"), ("Аптечка", "shopping", "kit"),
        ("Небольшой ремонт", "repair", "tool"), ("Поддержать соседа", "delivery", "heart"),
    )
    rng = random.Random(seed)
    jobs = []
    for index, (title, skill, icon) in enumerate(templates):
        distance = rng.randint(1, 4)
        deadline = rng.randint(max(2, distance), 5)
        jobs.append({
            "id": f"job-{index + 1}", "title": title, "skill": skill, "icon": icon,
            "distance": distance, "deadline": deadline, "spawn": index // 2,
            "x": rng.randint(10, 88), "y": rng.randint(15, 82), "assigned": None, "success": None,
        })
    return jobs


def _make_dispatch_state(user_id: int, equipped: set[str]) -> dict:
    seed = secrets.randbelow(2**31 - 1)
    volunteers = [
        {"id": "vera", "name": "Вера", "skills": ["shopping", "delivery"], "speed": 3, "color": "teal"},
        {"id": "maks", "name": "Макс", "skills": ["repair", "cleaning"], "speed": 4, "color": "orange"},
        {"id": "lena", "name": "Лена", "skills": ["study", "delivery"], "speed": 2, "color": "purple"},
        {"id": "amir", "name": "Амир", "skills": ["shopping", "cleaning"], "speed": 5, "color": "blue"},
    ]
    return {
        "seed": seed, "turn": 0, "jobs": _dispatch_jobs(seed), "volunteers": volunteers,
        "completed": 0, "assigned": 0, "score": 0, "efficiency": 100,
        "last_notice": "Выберите волонтёра, затем подходящую заявку на карте.",
        "equipped": sorted(equipped),
    }


def _make_match_board(seed: int) -> list[list[str]]:
    rng = random.Random(seed)
    board: list[list[str]] = []
    for row in range(7):
        values: list[str] = []
        for col in range(7):
            allowed = list(_TILES)
            if col >= 2 and values[col - 1] == values[col - 2]:
                allowed.remove(values[col - 1])
            if row >= 2 and board[row - 1][col] == board[row - 2][col] and board[row - 1][col] in allowed:
                allowed.remove(board[row - 1][col])
            values.append(rng.choice(allowed))
        board.append(values)
    return board


def _make_match_state(user_id: int, equipped: set[str]) -> dict:
    seed = secrets.randbelow(2**31 - 1)
    return {
        "seed": seed, "rng_nonce": 0, "board": _make_match_board(seed), "moves": 18,
        "score": 0, "target_tile": "book", "target_goal": 12, "target_count": 0,
        "max_combo": 0, "last_combo": 0, "hints": 1 if "match_hint" in equipped else 0,
        "last_notice": "Соберите три одинаковых предмета в ряд.", "equipped": sorted(equipped),
    }


def _make_safety_state(user_id: int, equipped: set[str]) -> dict:
    scenarios = _select_learning_scenarios(user_id, "safety")
    return {
        "content_version": CONTENT_VERSION, "scenario_ids": [item["id"] for item in scenarios], "scenarios": scenarios,
        "index": 0, "correct": 0, "answers": [], "equipped": sorted(equipped),
        "last_notice": "Выберите самый безопасный вариант.",
    }


def _make_mission_state(user_id: int, equipped: set[str]) -> dict:
    scenarios = _select_learning_scenarios(user_id, "mission")
    return {
        "content_version": CONTENT_VERSION, "scenario_ids": [item["id"] for item in scenarios], "scenarios": scenarios,
        "index": 0, "reputation": 0, "answers": [], "equipped": sorted(equipped),
        "last_notice": "Помогайте бережно, с уважением к границам и согласию.",
    }


_NEW_SESSION = {
    "crossing": _make_crossing_state,
    "dispatch": _make_dispatch_state,
    "match": _make_match_state,
    "safety": _make_safety_state,
    "mission": _make_mission_state,
}


def _crossing_lane(seed: int, row: int, tick: int) -> list[int]:
    if row <= 0 or row % 4 not in (1, 2):
        return []
    speed = 1 if row % 2 else -1
    offset = (seed // 17 + row * 3 + tick * speed) % 7
    cars = [offset, (offset + 3) % 7]
    if row % 9 == 1:
        cars.append((offset + 5) % 7)
    return cars


def _crossing_elapsed_ms(state: dict) -> int:
    elapsed = max(0, int(state.get("elapsed_ms", int(state.get("ticks", 0)) * _CROSSING_TICK_MS)))
    if state.get("paused"):
        return elapsed
    anchor = state.get("clock_anchor_at")
    if not anchor:
        return elapsed
    return max(elapsed, elapsed + int(_now().timestamp() * 1000) - _timestamp_ms(anchor))


def _crossing_tick(state: dict) -> int:
    return max(0, _crossing_elapsed_ms(state) // _CROSSING_TICK_MS)


def _set_crossing_paused(state: dict, paused: bool) -> None:
    if bool(state.get("paused")) == paused:
        return
    state["elapsed_ms"] = _crossing_elapsed_ms(state)
    state["clock_anchor_at"] = _now_text()
    state["paused"] = paused
    state["ticks"] = state["elapsed_ms"] // _CROSSING_TICK_MS


def _crossing_view(state: dict) -> dict:
    player = state["player"]
    tick = _crossing_tick(state)
    low = max(0, int(player["y"]) - 3)
    rows = []
    for row in range(low, low + 10):
        lane = row % 4 in (1, 2)
        rows.append({
            "y": row, "lane": lane, "cars": _crossing_lane(state["seed"], row, tick),
            "coin": bool(row and (state["seed"] + row * 7) % 5 == 0 and row not in state["collected"]),
            "delivery": bool(row and row % 10 == 0),
        })
    return {
        "player": player, "rows": rows, "distance": state["distance"], "coins": state["coins"],
        "deliveries": state["deliveries"], "shield": state["shield"], "notice": state["last_notice"],
        "seed": state["seed"], "elapsed_ms": _crossing_elapsed_ms(state),
        "server_time_ms": int(_now().timestamp() * 1000), "tick_ms": _CROSSING_TICK_MS,
        "paused": bool(state.get("paused")),
    }


def _public_session(row: dict, state: dict | None = None) -> dict:
    state = state if state is not None else _loads(row["state"], {})
    game_code = row["game_code"]
    data = {
        "id": row["id"], "game": game_code, "status": row["status"], "score": int(row["score"] or 0),
        "title": GAME_CATALOG[game_code]["title"], "started_at": row["started_at"],
        "equipped": state.get("equipped", []),
    }
    if game_code == "crossing":
        data["game_state"] = _crossing_view(state)
    elif game_code == "dispatch":
        visible_jobs = [job for job in state["jobs"] if job["spawn"] <= state["turn"]]
        data["game_state"] = {
            "turn": state["turn"], "jobs": visible_jobs, "volunteers": state["volunteers"],
            "completed": state["completed"], "assigned": state["assigned"], "efficiency": state["efficiency"],
            "notice": state["last_notice"],
        }
    elif game_code == "match":
        data["game_state"] = {
            "board": state["board"], "moves": state["moves"], "target_tile": state["target_tile"],
            "target_goal": state["target_goal"], "target_count": state["target_count"],
            "last_combo": state["last_combo"], "max_combo": state["max_combo"], "hints": state["hints"],
            "notice": state["last_notice"],
        }
    elif game_code == "safety":
        index = state["index"]
        scenes = _learning_scenes(state, "safety")
        if index < len(scenes):
            scene = scenes[index]
            data["game_state"] = {
                "index": index, "total": len(scenes), "correct": state["correct"],
                "content_version": state.get("content_version", "legacy"),
                "scenario": {"id": scene.get("id"), "difficulty": scene.get("difficulty", scene.get("level", "")), "tags": scene.get("tags", ()), "title": scene["title"], "scene": scene["scene"], "question": scene["question"], "choices": scene["choices"]},
                "notice": state["last_notice"],
            }
        else:
            data["game_state"] = {"index": index, "total": len(scenes), "correct": state["correct"], "finished": True}
    elif game_code == "mission":
        index = state["index"]
        scenes = _learning_scenes(state, "mission")
        if index < len(scenes):
            scene = scenes[index]
            data["game_state"] = {
                "index": index, "total": len(scenes), "reputation": state["reputation"],
                "content_version": state.get("content_version", "legacy"),
                "scenario": {"id": scene.get("id"), "difficulty": scene.get("difficulty"), "tags": scene.get("tags", ()), "title": scene["title"], "person": scene["person"], "place": scene["place"], "scene": scene["scene"], "choices": [choice[0] for choice in scene["choices"]]},
                "notice": state["last_notice"],
            }
        else:
            data["game_state"] = {"index": index, "total": len(scenes), "reputation": state["reputation"], "finished": True}
    if state.get("result"):
        data["result"] = state["result"]
    return data


def start_game(user_id: int, game_code: str) -> dict:
    if game_code not in GAME_CATALOG:
        raise ValueError("Неизвестная игра.")
    _begin()
    try:
        _ensure_profile(user_id)
        cutoff = (_now() - timedelta(seconds=GAME_SESSION_TTL_SECONDS)).isoformat()
        _db().execute("UPDATE game_sessions SET status='expired' WHERE user_id=? AND status='active' AND expires_at<=?", (user_id, _now_text()))
        active_count = _db().execute("SELECT COUNT(*) n FROM game_sessions WHERE user_id=? AND status='active' AND started_at>?", (user_id, cutoff)).fetchone()["n"]
        if int(active_count or 0) >= 3:
            raise ValueError("Завершите или перезапустите одну из текущих игр.")
        equipped = _equipped_item_ids(user_id, game_code)
        state = _NEW_SESSION[game_code](user_id, equipped)
        session_id = secrets.token_urlsafe(24)
        stamp = _now_text()
        expires = (_now() + timedelta(seconds=GAME_SESSION_TTL_SECONDS)).isoformat()
        _db().execute(
            """INSERT INTO game_sessions(id,user_id,game_code,state,status,score,started_at,last_action_at,expires_at)
               VALUES(?,?,?,?, 'active',0,?,?,?)""",
            (session_id, user_id, game_code, _dumps(state), stamp, stamp, expires),
        )
        _db().execute("UPDATE game_profiles SET games_played=games_played+1,updated_at=CURRENT_TIMESTAMP WHERE user_id=?", (user_id,))
        _db().execute(
            """INSERT OR IGNORE INTO game_records(user_id,game_code,plays,completions)
               VALUES(?,?,0,0)""", (user_id, game_code)
        )
        _db().execute("UPDATE game_records SET plays=plays+1,updated_at=CURRENT_TIMESTAMP WHERE user_id=? AND game_code=?", (user_id, game_code))
        _db().execute("COMMIT")
    except Exception:
        _rollback()
        raise
    row = {"id": session_id, "game_code": game_code, "state": _dumps(state), "status": "active", "score": 0, "started_at": stamp}
    return _public_session(row, state)


def _get_active_session(user_id: int, session_id: str) -> tuple[dict, dict]:
    if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", session_id):
        raise ValueError("Некорректная игровая сессия.")
    row = _db().execute(_lock_sql("SELECT * FROM game_sessions WHERE id=? AND user_id=?"), (session_id, user_id)).fetchone()
    if not row:
        raise ValueError("Игровая сессия не найдена.")
    if row["status"] != "active":
        return dict(row), _loads(row["state"], {})
    if row["expires_at"] <= _now_text():
        _db().execute("UPDATE game_sessions SET status='expired' WHERE id=?", (session_id,))
        updated = dict(row)
        updated["status"] = "expired"
        return updated, _loads(row["state"], {})
    return dict(row), _loads(row["state"], {})


def _check_action_timing(row: dict) -> None:
    try:
        previous = datetime.fromisoformat(row["last_action_at"])
        elapsed = (_now() - previous).total_seconds() * 1000
        if elapsed < GAME_ACTION_MIN_INTERVAL_MS:
            raise ValueError("Слишком быстро. Попробуйте следующий ход через мгновение.")
    except ValueError:
        raise
    except Exception:
        return


def _crossing_action(state: dict, action: dict) -> tuple[dict, bool, dict | None]:
    control = action.get("type")
    if control == "pause":
        _set_crossing_paused(state, True)
        state["last_notice"] = "Маршрут поставлен на паузу. Машины остановлены на сервере."
        return state, False, None
    if control == "resume":
        _set_crossing_paused(state, False)
        state["last_notice"] = "Маршрут продолжен. Следите за движением машин."
        return state, False, None
    direction = action.get("direction")
    if direction not in {"up", "down", "left", "right"}:
        raise ValueError("Выберите направление движения.")
    if state.get("paused"):
        raise ValueError("Сначала продолжите маршрут.")
    player = state["player"]
    shifts = {"up": (0, 1), "down": (0, -1), "left": (-1, 0), "right": (1, 0)}
    dx, dy = shifts[direction]
    next_x = max(0, min(6, int(player["x"]) + dx))
    next_y = max(0, int(player["y"]) + dy)
    state["ticks"] = _crossing_tick(state)
    if next_x == player["x"] and next_y == player["y"]:
        state["last_notice"] = "Здесь край маршрута — выберите другое направление."
        return state, False, None
    player["x"], player["y"] = next_x, next_y
    if dy > 0:
        state["distance"] = max(state["distance"], next_y)
    if next_y and (state["seed"] + next_y * 7) % 5 == 0 and next_y not in state["collected"]:
        state["collected"].append(next_y)
        state["coins"] += 1
        state["last_notice"] = "Найден полезный ресурс: +5 к счёту."
    elif next_y and next_y % 10 == 0 and next_y > state["deliveries"] * 10:
        state["deliveries"] += 1
        state["last_notice"] = "Помощь доставлена в контрольную точку!"
    else:
        state["last_notice"] = "Маршрут открыт — двигайтесь к следующей точке помощи."
    score = state["distance"] * 10 + state["coins"] * 5 + state["deliveries"] * 20
    state["score"] = score
    cars = _crossing_lane(state["seed"], next_y, state["ticks"])
    if next_x in cars:
        if state["shield"] > 0:
            state["shield"] -= 1
            state["last_notice"] = "Проводник защитил героя от столкновения."
        else:
            state["last_notice"] = "Маршрут перекрыт. В следующий раз выберите безопасную клетку."
            return state, True, {"score": score, "outcome": "Маршрут прерван", "metric": state["distance"]}
    if state["distance"] >= 30:
        state["last_notice"] = "Все контрольные точки пройдены — помощь доставлена!"
        state["score"] = score + 40
        return state, True, {"score": state["score"], "outcome": "Маршрут завершён", "metric": state["distance"]}
    return state, False, None


def _dispatch_action(state: dict, action: dict) -> tuple[dict, bool, dict | None]:
    if action.get("type") != "assign":
        raise ValueError("Для центра помощи выберите волонтёра и заявку.")
    job_id = action.get("job_id")
    volunteer_id = action.get("volunteer_id")
    job = next((entry for entry in state["jobs"] if entry["id"] == job_id), None)
    volunteer = next((entry for entry in state["volunteers"] if entry["id"] == volunteer_id), None)
    if not job or not volunteer or job["spawn"] > state["turn"]:
        raise ValueError("Эта заявка или волонтёр сейчас недоступны.")
    if job["assigned"]:
        raise ValueError("На эту заявку уже назначен помощник.")
    job["assigned"] = volunteer_id
    state["assigned"] += 1
    state["turn"] += 1
    travel = max(1, job["distance"] - max(0, int(volunteer["speed"]) - 2))
    success = job["skill"] in volunteer["skills"] and travel <= job["deadline"]
    job["success"] = success
    if success:
        bonus = max(0, job["deadline"] - travel) * 15
        if "dispatch_radio" in state.get("equipped", []):
            bonus += 20
        state["score"] += 100 + bonus
        state["completed"] += 1
        state["last_notice"] = f"{volunteer['name']} справляется: заявка выполнена."
    else:
        state["efficiency"] = max(0, state["efficiency"] - 12)
        state["last_notice"] = "Назначение не подошло по навыкам или времени. Проверьте карточки команды."
    if state["assigned"] >= len(state["jobs"]):
        return state, True, {
            "score": state["score"], "outcome": "Смена центра завершена",
            "metric": state["completed"], "efficiency": state["efficiency"],
        }
    return state, False, None


def _find_matches(board: list[list[str]]) -> set[tuple[int, int]]:
    found: set[tuple[int, int]] = set()
    for row in range(7):
        start = 0
        while start < 7:
            end = start + 1
            while end < 7 and board[row][end] == board[row][start]:
                end += 1
            if end - start >= 3:
                found.update((row, col) for col in range(start, end))
            start = end
    for col in range(7):
        start = 0
        while start < 7:
            end = start + 1
            while end < 7 and board[end][col] == board[start][col]:
                end += 1
            if end - start >= 3:
                found.update((row, col) for row in range(start, end))
            start = end
    return found


def _collapse_board(state: dict, removed: set[tuple[int, int]]) -> None:
    board = state["board"]
    rng = random.Random(f"{state['seed']}:{state['rng_nonce']}")
    state["rng_nonce"] += 1
    for col in range(7):
        remaining = [board[row][col] for row in range(6, -1, -1) if (row, col) not in removed]
        while len(remaining) < 7:
            remaining.append(rng.choice(_TILES))
        for row in range(6, -1, -1):
            board[row][col] = remaining[6 - row]


def _legal_match_swaps(board: list[list[str]]) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    moves = []
    for row in range(7):
        for col in range(7):
            for dr, dc in ((0, 1), (1, 0)):
                other_row, other_col = row + dr, col + dc
                if other_row >= 7 or other_col >= 7:
                    continue
                board[row][col], board[other_row][other_col] = board[other_row][other_col], board[row][col]
                valid = bool(_find_matches(board))
                board[row][col], board[other_row][other_col] = board[other_row][other_col], board[row][col]
                if valid:
                    moves.append(((row, col), (other_row, other_col)))
    return moves


def _match_action(state: dict, action: dict) -> tuple[dict, bool, dict | None, dict | None]:
    if action.get("type") == "hint":
        if state["hints"] <= 0:
            raise ValueError("Подсказка не активна для этой игры.")
        moves = _legal_match_swaps(state["board"])
        if not moves:
            raise ValueError("На поле нет доступного хода. Перезапустите уровень.")
        state["hints"] -= 1
        state["last_notice"] = "Подсказка подсветила ход."
        return state, False, None, {"hint": {"a": moves[0][0], "b": moves[0][1]}}
    if action.get("type") != "swap":
        raise ValueError("Выберите две соседние клетки.")
    a, b = action.get("a"), action.get("b")
    if not (isinstance(a, list) and isinstance(b, list) and len(a) == 2 and len(b) == 2):
        raise ValueError("Некорректный ход.")
    try:
        ar, ac, br, bc = (int(a[0]), int(a[1]), int(b[0]), int(b[1]))
    except (TypeError, ValueError):
        raise ValueError("Некорректный ход.")
    if not all(0 <= value < 7 for value in (ar, ac, br, bc)) or abs(ar - br) + abs(ac - bc) != 1:
        raise ValueError("Можно менять только соседние предметы.")
    board = state["board"]
    board[ar][ac], board[br][bc] = board[br][bc], board[ar][ac]
    removed = _find_matches(board)
    if not removed:
        board[ar][ac], board[br][bc] = board[br][bc], board[ar][ac]
        state["last_notice"] = "Эта перестановка не собирает ряд. Попробуйте другой ход."
        return state, False, None, {"valid": False}
    combo = 0
    gained = 0
    while removed:
        combo += 1
        tiles = [board[row][col] for row, col in removed]
        state["target_count"] += sum(1 for tile in tiles if tile == state["target_tile"])
        gained += len(removed) * 25 * combo
        _collapse_board(state, removed)
        removed = _find_matches(board)
    state["moves"] -= 1
    state["score"] += gained
    state["last_combo"] = combo
    state["max_combo"] = max(state["max_combo"], combo)
    state["last_notice"] = f"Каскад x{combo}: +{gained} очков."
    finished = state["moves"] <= 0 or state["target_count"] >= state["target_goal"]
    if finished:
        if state["target_count"] >= state["target_goal"]:
            state["score"] += 120
            state["last_notice"] = "Цель уровня выполнена: бонус за собранные книги!"
        return state, True, {"score": state["score"], "outcome": "Уровень завершён", "metric": state["score"], "max_combo": state["max_combo"]}, {"valid": True, "gained": gained}
    return state, False, None, {"valid": True, "gained": gained}


def _safety_action(state: dict, action: dict) -> tuple[dict, bool, dict | None, dict]:
    if action.get("type") != "answer":
        raise ValueError("Выберите вариант ответа.")
    index = state["index"]
    scenes = _learning_scenes(state, "safety")
    if index >= len(scenes):
        raise ValueError("Игра уже завершена.")
    try:
        selected = int(action.get("choice"))
    except (TypeError, ValueError):
        raise ValueError("Некорректный вариант ответа.")
    scene = scenes[index]
    if not 0 <= selected < len(scene["choices"]):
        raise ValueError("Некорректный вариант ответа.")
    correct = selected == scene["correct"]
    state["answers"].append(selected)
    if correct:
        state["correct"] += 1
    state["score"] = state["correct"]
    state["index"] += 1
    state["last_notice"] = scene["principle"]
    feedback = {"correct": correct, "explanation": scene["explanation"], "principle": scene["principle"]}
    finished = state["index"] >= len(scenes)
    final = {"score": state["correct"], "outcome": "Курс завершён", "metric": state["correct"]} if finished else None
    return state, finished, final, feedback


def _mission_action(state: dict, action: dict) -> tuple[dict, bool, dict | None, dict]:
    if action.get("type") != "choose":
        raise ValueError("Выберите вариант действия.")
    index = state["index"]
    scenes = _learning_scenes(state, "mission")
    if index >= len(scenes):
        raise ValueError("История уже завершена.")
    try:
        selected = int(action.get("choice"))
    except (TypeError, ValueError):
        raise ValueError("Некорректный вариант действия.")
    scene = scenes[index]
    if not 0 <= selected < len(scene["choices"]):
        raise ValueError("Некорректный вариант действия.")
    choice, reputation, explanation = scene["choices"][selected]
    state["answers"].append(selected)
    state["reputation"] += reputation
    state["score"] = state["reputation"]
    state["index"] += 1
    state["last_notice"] = explanation
    feedback = {"reputation": reputation, "explanation": explanation, "choice": choice}
    finished = state["index"] >= len(scenes)
    final = {"score": state["reputation"], "outcome": "История завершена", "metric": state["reputation"]} if finished else None
    return state, finished, final, feedback


def _achievement_candidates(game_code: str, state: dict, final: dict, completed_before: int) -> list[str]:
    ids = []
    if completed_before == 0:
        ids.append("first_steps")
    if game_code == "crossing" and int(final.get("score", 0)) >= 180:
        ids.append("crossing_helper")
    if game_code == "dispatch" and int(final.get("metric", 0)) >= 5:
        ids.append("dispatch_organizer")
    if game_code == "match" and int(final.get("max_combo", 0)) >= 3:
        ids.append("match_combo")
    if game_code == "safety" and int(final.get("metric", 0)) >= 5:
        ids.append("safety_expert")
    if game_code == "mission" and int(final.get("metric", 0)) >= 5:
        ids.append("mission_helper")
    return ids


def _available_reward_room(user_id: int, day: str, pending_hp: int = 0) -> int:
    total_row = _db().execute("SELECT COALESCE(SUM(awarded_hp),0) amount FROM game_daily_rewards WHERE user_id=? AND reward_date=?", (user_id, day)).fetchone()
    return max(0, GAME_DAILY_REWARD_CAP - int(total_row["amount"] or 0) - pending_hp)


def _add_game_transaction(user_id: int, amount: int, kind: str, description: str, reference: str) -> None:
    _db().execute(
        "INSERT INTO game_transactions(user_id,amount_hp,kind,description,reference) VALUES(?,?,?,?,?)",
        (user_id, amount, kind, description, reference),
    )
    _db().execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, user_id))
    _db().execute("UPDATE game_profiles SET games_hp_earned=games_hp_earned+?,updated_at=CURRENT_TIMESTAMP WHERE user_id=?", (amount, user_id))


def _complete_session_tx(user_id: int, row: dict, state: dict, final: dict) -> dict:
    game_code = row["game_code"]
    score = max(0, int(final["score"]))
    # Serialise a player's rewards across titles.  This closes the small race
    # where two completed games could otherwise both observe the remaining
    # daily allowance before either one records its transaction.
    _db().execute(_lock_sql("SELECT user_id FROM users WHERE user_id=?"), (user_id,)).fetchone()
    record = _db().execute(_lock_sql("SELECT * FROM game_records WHERE user_id=? AND game_code=?"), (user_id, game_code)).fetchone()
    if not record:
        _db().execute("INSERT INTO game_records(user_id,game_code,best_score,best_meta,plays,completions) VALUES(?,?,?,?,0,0)", (user_id, game_code, 0, "{}"))
        record = _db().execute(_lock_sql("SELECT * FROM game_records WHERE user_id=? AND game_code=?"), (user_id, game_code)).fetchone()
    completed_before = int(record["completions"] or 0)
    best_score = max(int(record["best_score"] or 0), score)
    best_meta = _loads(record["best_meta"], {})
    if score >= int(record["best_score"] or 0):
        best_meta = {"metric": int(final.get("metric", score)), "max_combo": int(final.get("max_combo", 0)), "outcome": final["outcome"]}
    _db().execute(
        """UPDATE game_records SET best_score=?,best_meta=?,completions=completions+1,updated_at=CURRENT_TIMESTAMP
           WHERE user_id=? AND game_code=?""",
        (best_score, _dumps(best_meta), user_id, game_code),
    )
    _db().execute("UPDATE game_profiles SET games_completed=games_completed+1,updated_at=CURRENT_TIMESTAMP WHERE user_id=?", (user_id,))

    unlocked = []
    for achievement_id in _achievement_candidates(game_code, state, final, completed_before):
        changed = _db().execute("INSERT OR IGNORE INTO game_achievements(user_id,achievement_id) VALUES(?,?)", (user_id, achievement_id)).rowcount
        if changed:
            unlocked.append(achievement_id)
    completed_titles = _db().execute("SELECT COUNT(*) amount FROM game_records WHERE user_id=? AND completions>0", (user_id,)).fetchone()["amount"]
    if int(completed_titles or 0) >= len(GAME_CATALOG):
        changed = _db().execute("INSERT OR IGNORE INTO game_achievements(user_id,achievement_id) VALUES(?,?)", (user_id, "all_rounder")).rowcount
        if changed:
            unlocked.append("all_rounder")

    day = _reward_day()
    daily = _db().execute(_lock_sql("SELECT * FROM game_daily_rewards WHERE user_id=? AND game_code=? AND reward_date=?"), (user_id, game_code, day)).fetchone()
    if not daily:
        _db().execute("INSERT INTO game_daily_rewards(user_id,game_code,reward_date,best_score,awarded_hp) VALUES(?,?,?,?,0)", (user_id, game_code, day, 0))
        daily = _db().execute(_lock_sql("SELECT * FROM game_daily_rewards WHERE user_id=? AND game_code=? AND reward_date=?"), (user_id, game_code, day)).fetchone()
    previous_award = int(daily["awarded_hp"] or 0)
    previous_result_award = int(daily["result_hp"] or 0)
    daily_best = max(int(daily["best_score"] or 0), score)
    desired = _score_target(game_code, daily_best)
    reward = min(
        max(0, desired - previous_result_award),
        _available_reward_room(user_id, day),
    )
    reward_events = []
    pending_hp = 0
    if reward:
        _add_game_transaction(user_id, reward, "game_reward", f"Награда за {GAME_CATALOG[game_code]['short_title']}", f"game-reward:{row['id']}")
        reward_events.append({"kind": "result", "hp": reward, "label": "Награда за результат"})
        pending_hp += reward
        previous_result_award += reward
    for achievement_id in unlocked:
        room = _available_reward_room(user_id, day, pending_hp)
        hp = min(int(ACHIEVEMENTS[achievement_id]["hp"]), room)
        if hp:
            _add_game_transaction(user_id, hp, "achievement", f"Достижение «{ACHIEVEMENTS[achievement_id]['title']}»", f"game-achievement:{user_id}:{achievement_id}")
            reward_events.append({"kind": "achievement", "hp": hp, "label": ACHIEVEMENTS[achievement_id]["title"]})
            pending_hp += hp
    challenge_conditions = {
        "daily_start": True,
        "daily_learning": game_code in {"safety", "mission"} and int(final.get("metric", 0)) >= 3,
    }
    completed_challenges = []
    for challenge_id, condition in challenge_conditions.items():
        if not condition:
            continue
        changed = _db().execute(
            "INSERT OR IGNORE INTO game_daily_challenge_claims(user_id,challenge_id,reward_date) VALUES(?,?,?)",
            (user_id, challenge_id, day),
        ).rowcount
        if not changed:
            continue
        completed_challenges.append(challenge_id)
        room = _available_reward_room(user_id, day, pending_hp)
        hp = min(int(DAILY_CHALLENGES[challenge_id]["hp"]), room)
        if hp:
            _add_game_transaction(user_id, hp, "daily_challenge", f"Ежедневное задание «{DAILY_CHALLENGES[challenge_id]['title']}»", f"game-daily:{user_id}:{day}:{challenge_id}")
            reward_events.append({"kind": "daily", "hp": hp, "label": DAILY_CHALLENGES[challenge_id]["title"]})
            pending_hp += hp
    _db().execute(
        "UPDATE game_daily_rewards SET best_score=?,awarded_hp=?,result_hp=? WHERE user_id=? AND game_code=? AND reward_date=?",
        (daily_best, previous_award + pending_hp, previous_result_award, user_id, game_code, day),
    )
    total_reward = sum(int(event["hp"]) for event in reward_events)
    achievements = [{"id": identifier, **ACHIEVEMENTS[identifier]} for identifier in unlocked]
    return {
        "score": score, "outcome": final["outcome"], "metric": int(final.get("metric", score)),
        "reward_hp": total_reward, "reward_events": reward_events, "achievements": achievements,
        "completed_challenges": completed_challenges, "daily_reward": previous_award + pending_hp,
    }


def action_game(user_id: int, session_id: str, action: dict) -> dict:
    if not isinstance(action, dict):
        raise ValueError("Некорректное игровое действие.")
    _begin()
    try:
        row, state = _get_active_session(user_id, session_id)
        if row["status"] != "active":
            _db().execute("COMMIT")
            return _public_session(row, state)
        feedback: dict | None = None
        game_code = row["game_code"]
        if not (game_code == "crossing" and action.get("type") in {"pause", "resume"}):
            _check_action_timing(row)
        if game_code == "crossing":
            state, finished, final = _crossing_action(state, action)
        elif game_code == "dispatch":
            state, finished, final = _dispatch_action(state, action)
        elif game_code == "match":
            state, finished, final, feedback = _match_action(state, action)
        elif game_code == "safety":
            state, finished, final, feedback = _safety_action(state, action)
        elif game_code == "mission":
            state, finished, final, feedback = _mission_action(state, action)
        else:
            raise ValueError("Неизвестная игровая сессия.")
        score = int(final["score"]) if finished and final else int(state.get("score", row["score"] or 0))
        stamp = _now_text()
        if finished and final:
            result = _complete_session_tx(user_id, row, state, final)
            state["result"] = result
            _db().execute(
                "UPDATE game_sessions SET state=?,status='completed',score=?,last_action_at=?,completed_at=? WHERE id=?",
                (_dumps(state), score, stamp, stamp, session_id),
            )
            row.update({"state": _dumps(state), "status": "completed", "score": score, "last_action_at": stamp, "completed_at": stamp})
        else:
            _db().execute("UPDATE game_sessions SET state=?,score=?,last_action_at=? WHERE id=?", (_dumps(state), score, stamp, session_id))
            row.update({"state": _dumps(state), "score": score, "last_action_at": stamp})
        _db().execute("COMMIT")
    except Exception:
        _rollback()
        raise
    response = _public_session(row, state)
    if feedback:
        response["feedback"] = feedback
    return response


def abandon_game(user_id: int, session_id: str) -> dict:
    _begin()
    try:
        row, state = _get_active_session(user_id, session_id)
        if row["status"] == "active":
            _db().execute("UPDATE game_sessions SET status='abandoned',completed_at=? WHERE id=?", (_now_text(), session_id))
            row["status"] = "abandoned"
        _db().execute("COMMIT")
    except Exception:
        _rollback()
        raise
    return _public_session(row, state)


def _daily_challenge_state(user_id: int) -> list[dict]:
    day = _reward_day()
    claimed = {row["challenge_id"] for row in _db().execute("SELECT challenge_id FROM game_daily_challenge_claims WHERE user_id=? AND reward_date=?", (user_id, day)).fetchall()}
    return [{"id": item_id, **item, "completed": item_id in claimed} for item_id, item in DAILY_CHALLENGES.items()]


def game_session(user_id: int, session_id: str) -> dict:
    """Return a player's own session without exposing its private rule state."""
    if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", session_id):
        raise ValueError("Некорректная игровая сессия.")
    row = _db().execute("SELECT * FROM game_sessions WHERE id=? AND user_id=?", (session_id, user_id)).fetchone()
    if not row:
        raise ValueError("Игровая сессия не найдена.")
    row = dict(row)
    if row["status"] == "active" and row["expires_at"] <= _now_text():
        _db().execute("UPDATE game_sessions SET status='expired' WHERE id=?", (session_id,))
        row["status"] = "expired"
    return _public_session(row)


def game_state(user_id: int | None) -> dict:
    if user_id is None:
        return {"ok": True, "authenticated": False, "catalog": catalog(), "economy": {"daily_cap": GAME_DAILY_REWARD_CAP, "per_game_cap": GAME_PER_TITLE_REWARD_CAP}}
    _ensure_profile(user_id)
    user = database.get_user(user_id)
    profile = _db().execute("SELECT * FROM game_profiles WHERE user_id=?", (user_id,)).fetchone()
    record_rows = _db().execute("SELECT * FROM game_records WHERE user_id=?", (user_id,)).fetchall()
    records = {row["game_code"]: {"best_score": int(row["best_score"] or 0), "plays": int(row["plays"] or 0), "completions": int(row["completions"] or 0), "best_meta": _loads(row["best_meta"], {})} for row in record_rows}
    achievements = []
    for row in _db().execute("SELECT achievement_id,unlocked_at FROM game_achievements WHERE user_id=? ORDER BY unlocked_at DESC", (user_id,)).fetchall():
        item = ACHIEVEMENTS.get(row["achievement_id"])
        if item:
            achievements.append({"id": row["achievement_id"], **item, "unlocked_at": row["unlocked_at"]})
    ownership = {row["item_id"]: bool(row["equipped"]) for row in _db().execute("SELECT item_id,equipped FROM game_item_ownership WHERE user_id=?", (user_id,)).fetchall()}
    store = [{"id": item_id, **item, "owned": item_id in ownership, "equipped": ownership.get(item_id, False)} for item_id, item in STORE_ITEMS.items()]
    transactions = [dict(row) for row in _db().execute("SELECT amount_hp,kind,description,created_at FROM game_transactions WHERE user_id=? ORDER BY id DESC LIMIT 20", (user_id,)).fetchall()]
    day = _reward_day()
    daily_total = _db().execute("SELECT COALESCE(SUM(awarded_hp),0) amount FROM game_daily_rewards WHERE user_id=? AND reward_date=?", (user_id, day)).fetchone()["amount"]
    active = _db().execute("SELECT * FROM game_sessions WHERE user_id=? AND status='active' AND expires_at>? ORDER BY started_at DESC LIMIT 1", (user_id, _now_text())).fetchone()
    return {
        "ok": True, "authenticated": True, "catalog": catalog(), "balance": int(user["balance"] or 0) if user else 0,
        "profile": dict(profile) if profile else {"games_played": 0, "games_completed": 0, "games_hp_earned": 0},
        "records": records, "achievements": achievements, "store": store, "transactions": transactions,
        "challenges": _daily_challenge_state(user_id), "economy": {
            "daily_cap": GAME_DAILY_REWARD_CAP, "per_game_cap": GAME_PER_TITLE_REWARD_CAP,
            "earned_today": int(daily_total or 0), "remaining_today": max(0, GAME_DAILY_REWARD_CAP - int(daily_total or 0)), "day": day,
        },
        "active_session": _public_session(dict(active)) if active else None,
    }


def purchase_item(user_id: int, item_id: str, purchase_key: str) -> dict:
    if item_id not in STORE_ITEMS:
        raise ValueError("Неизвестный предмет магазина.")
    if not isinstance(purchase_key, str) or not _PURCHASE_KEY_RE.fullmatch(purchase_key):
        raise ValueError("Некорректный ключ покупки.")
    item = STORE_ITEMS[item_id]
    reference = f"game-purchase:{purchase_key}"
    _begin()
    try:
        _ensure_profile(user_id)
        previous = _db().execute(_lock_sql("SELECT * FROM game_transactions WHERE reference=?"), (reference,)).fetchone()
        if previous:
            if previous["user_id"] != user_id:
                raise ValueError("Ключ покупки уже использован.")
            _db().execute("COMMIT")
            return {"created": False, "balance": int(database.get_user(user_id)["balance"] or 0), "item_id": item_id}
        own = _db().execute(_lock_sql("SELECT 1 FROM game_item_ownership WHERE user_id=? AND item_id=?"), (user_id, item_id)).fetchone()
        if own:
            raise ValueError("Этот предмет уже приобретён.")
        price = int(item["price"])
        changed = _db().execute("UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?", (price, user_id, price)).rowcount
        if changed != 1:
            raise ValueError("Недостаточно H-Points.")
        _db().execute("INSERT INTO game_item_ownership(user_id,item_id) VALUES(?,?)", (user_id, item_id))
        _db().execute("INSERT INTO game_transactions(user_id,amount_hp,kind,description,reference) VALUES(?,?,?,?,?)", (user_id, -price, "purchase", f"Игровой предмет «{item['title']}»", reference))
        # Keep the universal billing history aware of a real H-Points debit.
        _db().execute(
            """INSERT INTO billing_invoices(user_id,item_type,amount_rub,currency,payload,metadata,status,paid_at)
               VALUES(?,?,?,?,?,?, 'paid', CURRENT_TIMESTAMP)""",
            (user_id, f"game:{item_id}", price, "HP", f"hpoint:game:{purchase_key}", _dumps({"game_item": item_id})),
        )
        _db().execute("COMMIT")
    except Exception:
        _rollback()
        raise
    return {"created": True, "balance": int(database.get_user(user_id)["balance"] or 0), "item_id": item_id}


def equip_item(user_id: int, item_id: str, equipped: bool = True) -> dict:
    item = STORE_ITEMS.get(item_id)
    if not item:
        raise ValueError("Неизвестный предмет магазина.")
    _begin()
    try:
        owned = _db().execute(_lock_sql("SELECT 1 FROM game_item_ownership WHERE user_id=? AND item_id=?"), (user_id, item_id)).fetchone()
        if not owned:
            raise ValueError("Сначала приобретите этот предмет.")
        if equipped:
            game_items = tuple(key for key, value in STORE_ITEMS.items() if value["game"] == item["game"])
            placeholders = ",".join("?" for _ in game_items)
            _db().execute(f"UPDATE game_item_ownership SET equipped=0 WHERE user_id=? AND item_id IN ({placeholders})", (user_id, *game_items))
        _db().execute("UPDATE game_item_ownership SET equipped=? WHERE user_id=? AND item_id=?", (1 if equipped else 0, user_id, item_id))
        _db().execute("COMMIT")
    except Exception:
        _rollback()
        raise
    return {"item_id": item_id, "equipped": bool(equipped)}
