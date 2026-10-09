"""Пользовательские фильтры: формат, темы, горизонт по датам."""
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from hackdigest.models import Hackathon

TOPICS: dict[str, tuple[str, tuple[str, ...]]] = {
    "ai": ("AI / ML", ("ai", "ml", "machine learning", "llm", "gpt", "нейро", "ии", "искусственн",
                       "data science", "ml/ai", "агент", "agent", "computer vision", "nlp")),
    "web": ("Web", ("web", "веб", "frontend", "backend", "фронтенд", "бэкенд", "сайт")),
    "mobile": ("Mobile", ("mobile", "мобил", "ios", "android", "мини-прилож")),
    "security": ("Безопасность / CTF", ("ctf", "security", "cyber", "кибер", "безопасн", "infosec")),
    "fintech": ("Финтех", ("fintech", "финтех", "bank", "банк", "finance", "финанс", "tender")),
    "gamedev": ("Геймдев", ("game", "гейм", "игр")),
    "blockchain": ("Web3", ("blockchain", "web3", "crypto", "блокчейн", "ethereum", "defi", "solana")),
    "hardware": ("Железо / IoT", ("hardware", "iot", "robot", "робот", "embedded", "arduino", "дрон")),
    "data": ("Данные", ("data", "данн", "analytics", "аналитик", "bigdata")),
    "social": ("Соц. и эко", ("social good", "eco", "эколог", "health", "медиц", "education", "образов",
                              "climate", "sustainab", "город")),
}
PERIODS = {7: "неделя", 30: "месяц", 90: "3 месяца", 0: "без ограничений"}
FORMATS = {"any": "любой", "online": "онлайн", "offline": "офлайн"}
REGIONS = {"ru_online": "Россия + онлайн в мире", "ru": "Россия", "world": "весь мир"}
RU_SOURCES = {"hackathons_rus", "codenrock", "leader_id", "telegram"}


def _pattern(word: str) -> str:
    w = re.escape(word)
    # короткие латинские слова — только целиком («ai» не должно находиться в «chain»),
    # остальные — как начало слова, чтобы ловить окончания («игр» → «игры», «игровой»)
    tail = r"(?![a-zа-яё])" if len(word) <= 3 and word.isascii() else ""
    return rf"(?<![a-zа-яё]){w}{tail}"


_TOPIC_RE = {key: re.compile("|".join(_pattern(w) for w in words)) for key, (_, words) in TOPICS.items()}


def topics_of(h: Hackathon) -> set[str]:
    haystack = " | ".join((h.title, *h.tags)).lower()
    return {key for key, rx in _TOPIC_RE.items() if rx.search(haystack)}


@dataclass
class Filters:
    format: str = "any"
    topics: list[str] = field(default_factory=list)
    period_days: int = 0
    region: str = "ru_online"

    @classmethod
    def from_dict(cls, data: dict) -> "Filters":
        f = cls(
            format=data.get("format", "any"),
            topics=[t for t in data.get("topics", []) if t in TOPICS],
            period_days=int(data.get("period_days", 0)),
            region=data.get("region", "ru_online"),
        )
        if f.format not in FORMATS:
            f.format = "any"
        if f.region not in REGIONS:
            f.region = "ru_online"
        return f

    def to_dict(self) -> dict:
        return asdict(self)

    def is_empty(self) -> bool:
        return self.format == "any" and not self.topics and not self.period_days and self.region == "world"

    def matches(self, h: Hackathon, now: datetime) -> bool:
        if self.region != "world" and h.source not in RU_SOURCES:
            if self.region == "ru" or h.online is not True:
                return False
        if self.format == "online" and h.online is False:
            return False
        if self.format == "offline" and h.online is True:
            return False
        if self.topics and not topics_of(h) & set(self.topics):
            return False
        if self.period_days and h.start and h.start > now + timedelta(days=self.period_days):
            return False
        return True

    def describe(self) -> str:
        parts = [REGIONS[self.region]] if self.region != "world" else []
        if self.format != "any":
            parts.append(FORMATS[self.format])
        if self.topics:
            parts.append(", ".join(TOPICS[t][0] for t in self.topics))
        if self.period_days:
            parts.append(f"старт в пределах: {PERIODS[self.period_days]}")
        return "; ".join(parts) or "нет"
