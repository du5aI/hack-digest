from dataclasses import dataclass, field
from datetime import datetime

from hackdigest.dates import MSK


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
    description: str = ""  # описание из источника: по нему определяется тематика и «о чём»
    via: str = ""  # где найдено: название канала и т.п.
    organizer: str = ""
    participants: int | None = None  # сколько уже зарегистрировалось, если источник это сообщает

    @property
    def key_date(self) -> datetime | None:
        """Ближайшая значимая дата: старт, а если он неизвестен — конец регистрации."""
        return self.start or self.reg_deadline

    def is_upcoming(self, now: datetime) -> bool:
        """Ещё не началось, или уже идёт, но регистрация открыта."""
        if self.reg_deadline and self.reg_deadline > now:
            return True
        if self.start:  # начинается сегодня по Москве — ещё показываем
            return self.start.astimezone(MSK).date() >= now.astimezone(MSK).date()
        return self.end is None or self.end > now
