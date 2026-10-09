from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Hackathon:
    uid: str  # уникальный id вида "<source>:<id>"
    source: str
    title: str
    url: str
    dates: str  # человекочитаемые даты
    location: str = ""
    prize: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    starts_at: datetime | None = None  # для сортировки, если известно
