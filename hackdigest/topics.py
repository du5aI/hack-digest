"""Тематика хакатона: направление (что делают), отрасль (для кого) и аудитория.

Тема определяется по ключевым словам в названии, тегах источника и описании.
Совпадение в названии или тегах весит 2 балла, каждое упоминание в описании — 1;
тема засчитывается от 2 баллов, так что одно случайное слово в длинном описании её не добавит.
Исключения: аудиторию («для студентов») и темы из короткого описания (одна-две фразы,
как на хакатоны.рус) достаточно упомянуть один раз.
"""
import re
from dataclasses import dataclass
from functools import lru_cache

from hackdigest.models import Hackathon


@dataclass(frozen=True)
class Topic:
    key: str
    label: str
    group: str
    words: tuple[str, ...]


GROUPS = {
    "direction": "Направление",
    "industry": "Сфера",
    "audience": "Для кого",
}

_TOPICS = [
    # --- направление: что разрабатывают ---
    Topic("ai", "AI / ML", "direction", (
        "ai", "ml", "machine learning", "llm", "gpt", "нейросет", "нейронн", "ии", "искусственн",
        "машинн", "ml/ai", "ds/ml/ai", "ии-", "ai-", "агент", "agent", "computer vision",
        "компьютерн зрени", "компьютерному зрени", "компьютерное зрение", "nlp", "genai", "generative",
        "генеративн", "rag", "deep learning", "nvidia", "интеллектуальн", "нейро")),
    Topic("data", "Данные и аналитика", "direction", (
        "data science", "data analytics", "big data", "bigdata", "datathon", "дататон", "датасет",
        "dataset", "аналитик", "анализ данн", "аналитика данн", "data engineering", "bi")),
    Topic("web", "Веб", "direction", (
        "web", "веб", "frontend", "backend", "фронтенд", "бэкенд", "fullstack", "full-stack",
        "сайт", "web-сервис", "веб-сервис", "веб-приложен")),
    Topic("mobile", "Мобильная разработка", "direction", (
        "mobile", "мобильн", "ios", "android", "мини-приложен", "mini app", "flutter", "kotlin", "swift")),
    Topic("security", "Кибербезопасность / CTF", "direction", (
        "ctf", "security", "cybersecurity", "cyber", "кибер", "безопасност", "infosec", "pentest",
        "уязвимост", "защит информац", "защиты информац", "криптограф", "capture the flag")),
    Topic("gamedev", "Геймдев", "direction", (
        "game", "gamedev", "гейм", "игр", "game jam", "геймджем", "unity", "unreal", "game", "gaming")),
    Topic("web3", "Блокчейн / Web3", "direction", (
        "blockchain", "web3", "crypto", "блокчейн", "ethereum", "defi", "solana", "смарт-контракт",
        "smart contract", "nft", "dao", "крипт")),
    Topic("hardware", "Железо, IoT и роботы", "direction", (
        "hardware", "iot", "интернет вещей", "robot", "робот", "embedded", "встраиваем", "arduino",
        "дрон", "бпла", "беспилот", "микроконтроллер", "радиосвяз", "электроник", "схемотехн",
        "сигнал", "плис", "fpga")),
    Topic("algo", "Алгоритмы и олимпиадное", "direction", (
        "алгоритм", "спортивн программ", "спортивное программирование", "олимпиад", "competitive programming",
        "codeforces", "icpc", "cup")),
    Topic("product", "Продукт и бизнес", "direction", (
        "продукт", "product", "стартап", "startup", "бизнес-кейс", "бизнес кейс", "кейс-чемпионат",
        "mvp", "акселератор", "предпринимат", "entrepreneur", "pitch", "бизнес-модел")),
    Topic("design", "Дизайн и UX", "direction", (
        "design", "дизайн", "ux", "ui/ux", "ux/ui", "интерфейс", "figma", "3d", "vr", "ar", "xr",
        "виртуальн", "дополненн реальн")),
    Topic("opensource", "Open source", "direction", (
        "open source", "open-source", "opensource", "открыт код", "открытым кодом", "открытого кода",
        "contribution", "github")),
    Topic("quantum", "Квантовые технологии", "direction", (
        "quantum", "квантов")),
    Topic("open", "Свободная тема", "direction", (
        "no restrictions", "open ended", "open track", "open innovation", "любая тема", "свободн тем",
        "любой тематик")),
    # --- отрасль: для кого или в какой сфере ---
    Topic("fintech", "Финтех и банки", "industry", (
        "fintech", "финтех", "bank", "банк", "finance", "финанс", "платеж", "payment", "инвест",
        "страхов", "tender", "тендер", "закупк")),
    Topic("health", "Медицина и здоровье", "industry", (
        "health", "медиц", "здоров", "healthcare", "medtech", "медтех", "biotech", "биотех", "био",
        "клиник", "пациент", "протез", "фарм", "лекарств", "сеченов")),
    Topic("edu", "Образование", "industry", (
        "education", "edtech", "образовательн", "образовани", "учебн", "lms")),
    Topic("eco", "Экология и энергетика", "industry", (
        "climate", "sustainab", "eco", "green", "эколог", "энергет", "энерги", "климат", "нефт",
        "газ", "лесн", "лес", "углерод", "carbon", "energy")),
    Topic("city", "Город и транспорт", "industry", (
        "smart city", "умн город", "умные город", "городск сред", "городск хозяйств", "транспорт", "transport",
        "mobility", "логистик", "logistics", "урбанист", "жкх", "умный дом", "умные дома")),
    Topic("industry", "Промышленность", "industry", (
        "промышлен", "industrial", "производств", "manufacturing", "завод", "индустри", "моспром",
        "металлург", "машиностро", "1с", "морск", "судостро", "авиа", "космос", "космич", "space")),
    Topic("gov", "Госсектор и общество", "industry", (
        "govtech", "госуслуг", "государственн услуг", "государственн управлен", "госсектор", "госорган", "социальн", "social good", "social impact",
        "волонтер", "волонтёр", "некоммерч", "нко", "civic", "инклюзи", "доступн сред")),
    Topic("retail", "Ритейл, туризм и сервисы", "industry", (
        "retail", "ритейл", "e-commerce", "ecommerce", "маркетплейс", "торгов", "магазин", "м.видео",
        "travel", "тревел", "туризм", "путешеств", "отел", "бронирован", "food", "еда", "ресторан")),
    Topic("media", "Медиа и креатив", "industry", (
        "media", "медиа", "креатив", "creative", "музык", "music", "кино", "видео", "контент",
        "журналист", "искусств", "art")),
    Topic("science", "Наука", "industry", (
        "наук", "научн", "science", "research", "исследоват", "физик", "хими", "математ")),
    # --- аудитория ---
    Topic("students", "Студентам", "audience", (
        "студент", "student", "вуз", "university", "collegiate", "college", "магистр", "бакалавр",
        "university students")),
    Topic("beginners", "Новичкам", "audience", (
        "beginner", "beginner friendly", "новичк", "для начинающ", "без опыта", "first hackathon",
        "первый хакатон")),
]

TOPICS: dict[str, Topic] = {t.key: t for t in _TOPICS}
# короткие подписи для картинки-таймлайна
SHORT = {
    "ai": "AI", "data": "Данные", "web": "Веб", "mobile": "Mobile", "security": "ИБ / CTF",
    "gamedev": "Геймдев", "web3": "Web3", "hardware": "Железо", "algo": "Алгоритмы", "product": "Продукт",
    "design": "Дизайн", "opensource": "Open source", "quantum": "Квант", "open": "Своб. тема",
    "fintech": "Финтех", "health": "Медицина", "edu": "Образование", "eco": "Эко / энергетика",
    "city": "Город", "industry": "Промышленность", "gov": "Общество", "retail": "Ритейл / туризм",
    "media": "Медиа", "science": "Наука",
}
LETTERS = "a-zа-яё0-9"


def _pattern(word: str) -> str:
    w = re.escape(word).replace(r"\ ", r"\w*\s+")  # «компьютерн зрени» → «компьютерного зрения»
    # короткие латинские слова — только целиком («ai» не должно находиться в «chain»),
    # остальные — как начало слова, чтобы ловить окончания («игр» → «игры», «игровой»)
    tail = rf"(?![{LETTERS}])" if word.isascii() and len(word) <= 4 else ""
    return rf"(?<![{LETTERS}]){w}{tail}"


_TOPIC_RE = {t.key: re.compile("|".join(_pattern(w) for w in dict.fromkeys(t.words))) for t in _TOPICS}
TITLE_WEIGHT = 2
SHORT_DESCRIPTION = 300  # в коротком описании каждое слово на счету
THRESHOLD = {"direction": 2, "industry": 2, "audience": 1}


def classify(title: str, tags: tuple[str, ...] = (), description: str = "") -> list[str]:
    """Ключи тем: по группам в порядке GROUPS, внутри группы — от самой выраженной."""
    head = " | ".join((title, *tags)).lower()
    body = description.lower()
    body_weight = 2 if len(body) < SHORT_DESCRIPTION else 1
    scored = []
    for key, rx in _TOPIC_RE.items():
        score = TITLE_WEIGHT * bool(rx.search(head)) + body_weight * len(rx.findall(body))
        if score >= THRESHOLD[TOPICS[key].group]:
            scored.append((key, score))
    group_order = list(GROUPS)
    scored.sort(key=lambda ks: (group_order.index(TOPICS[ks[0]].group), -ks[1]))
    return [k for k, _ in scored]


@lru_cache(maxsize=4096)
def _classify_cached(title: str, tags: tuple[str, ...], description: str) -> tuple[str, ...]:
    return tuple(classify(title, tags, description))


def topics_of(h: Hackathon) -> tuple[str, ...]:
    """Ключи тем события в порядке словаря (сначала направления, потом отрасли, аудитория)."""
    return _classify_cached(h.title, h.tags, h.description)


def labels(keys, group: str | None = None, limit: int | None = None) -> list[str]:
    return [TOPICS[k].label for k in keys if group is None or TOPICS[k].group == group][:limit]
