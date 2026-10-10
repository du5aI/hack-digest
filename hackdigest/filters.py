"""Пользовательские фильтры: регион, формат, тематика, горизонт по датам."""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from hackdigest.models import Hackathon
from hackdigest.topics import GROUPS, TOPICS, topics_of

PERIODS = {7: "неделя", 30: "месяц", 90: "3 месяца", 0: "без ограничений"}
FORMATS = {"any": "любой", "online": "онлайн", "offline": "офлайн"}
REGIONS = {"ru_online": "Россия + онлайн в мире", "ru": "Россия", "world": "весь мир"}
RU_SOURCES = {"hackathons_rus", "codenrock", "leader_id", "changellenge", "telegram"}


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
        if self.topics:
            # внутри группы — «или», между группами — «и»: AI + медицина = AI-хакатоны в медицине
            mine = set(topics_of(h))
            for group in GROUPS:
                wanted = {t for t in self.topics if TOPICS[t].group == group}
                if wanted and not wanted & mine:
                    return False
        if self.period_days and h.start and h.start > now + timedelta(days=self.period_days):
            return False
        return True

    def describe(self) -> str:
        parts = [REGIONS[self.region]] if self.region != "world" else []
        if self.format != "any":
            parts.append(FORMATS[self.format])
        if self.topics:
            parts.append(", ".join(TOPICS[t].label for t in self.topics))
        if self.period_days:
            parts.append(f"старт в пределах: {PERIODS[self.period_days]}")
        return "; ".join(parts) or "нет"
