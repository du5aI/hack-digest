from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Hackathon:
    uid: str  # уникальный id вида "<source>:<id>"
    source: str
    title: str
    url: str
    start: datetime | None = None
    end: datetime | None = None
    reg_deadline: datetime | None = None
    online: bool | None = None  # None — неизвестно
    location: str = ""
    prize: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    dates_text: str = ""  # даты как текст, если не удалось разобрать
    summary: str = ""  # короткий текст (для постов из каналов)
    via: str = ""  # где найдено: название канала и т.п.

    def is_upcoming(self, now: datetime) -> bool:
        """Ещё не началось, или уже идёт, но регистрация открыта."""
        if self.reg_deadline and self.reg_deadline > now:
            return True
        if self.start:
            return self.start.date() >= now.date()
        return self.end is None or self.end > now
