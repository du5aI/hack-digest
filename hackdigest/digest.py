import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape

from hackdigest.filters import TOPICS, Filters, topics_of
from hackdigest.models import Hackathon

TG_LIMIT = 4096

SOURCE_NAMES = {
    "devpost": "Devpost",
    "codenrock": "Codenrock",
    "mlh": "MLH",
    "devfolio": "Devfolio",
    "telegram": "Telegram-каналы",
}
SOURCE_LINKS = {
    "devpost": "https://devpost.com/hackathons",
    "codenrock": "https://codenrock.com/contests",
    "mlh": "https://www.mlh.com/seasons",
    "devfolio": "https://devfolio.co/hackathons",
}

# ---------- интервалы ----------

_UNITS = {"m": 60, "h": 3600, "d": 86400, "w": 7 * 86400}
_UNIT_ALIASES = {
    "m": "m", "min": "m", "мин": "m", "м": "m",
    "h": "h", "ч": "h", "час": "h", "часа": "h", "часов": "h",
    "d": "d", "д": "d", "дн": "d", "день": "d", "дня": "d", "дней": "d",
    "w": "w", "н": "w", "нед": "w", "неделя": "w", "недели": "w", "недель": "w",
}
MIN_INTERVAL = 3600


def parse_interval(text: str) -> int | None:
    """'12h', '3d', '1w', '2 дня' -> секунды. None, если не распознано или меньше часа."""
    m = re.fullmatch(r"\s*(\d+)\s*([a-zа-я]+)\s*", text.lower())
    if not m:
        return None
    unit = _UNIT_ALIASES.get(m.group(2))
    if unit is None:
        return None
    seconds = int(m.group(1)) * _UNITS[unit]
    return seconds if seconds >= MIN_INTERVAL else None


_FORMS = {
    "w": ("неделю", "недели", "недель"),
    "d": ("день", "дня", "дней"),
    "h": ("час", "часа", "часов"),
    "m": ("минуту", "минуты", "минут"),
}


def plural(n: int, forms: tuple[str, str, str]) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


def format_interval(seconds: int) -> str:
    """Форма для фраз «раз в …» и «через …»: «2 дня», «5 часов», «неделю»."""
    for unit in ("w", "d", "h", "m"):
        if seconds % _UNITS[unit] == 0:
            n = seconds // _UNITS[unit]
            word = plural(n, _FORMS[unit])
            return word if n == 1 else f"{n} {word}"
    return f"{seconds} с"


# ---------- даты ----------

MONTHS_SHORT = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
MONTHS_FULL = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
               "сентября", "октября", "ноября", "декабря")


def fmt_day(d: datetime, now: datetime) -> str:
    s = f"{d.day} {MONTHS_SHORT[d.month - 1]}"
    return s if d.year == now.year else f"{s} {d.year}"


def fmt_range(start: datetime | None, end: datetime | None, now: datetime) -> str:
    if not start:
        return ""
    if not end or end.date() == start.date():
        return fmt_day(start, now)
    if (start.year, start.month) == (end.year, end.month):
        return f"{start.day}–{fmt_day(end, now)}"
    return f"{fmt_day(start, now)} – {fmt_day(end, now)}"


# ---------- дайджест ----------


@dataclass
class Section:
    title: str
    items: list[str]
    collapsed: bool = False  # свернуть в раскрывающуюся цитату


def format_item(h: Hackathon, is_new: bool, now: datetime) -> str:
    title = f'<a href="{escape(h.url)}"><b>{escape(h.title)}</b></a>'
    if is_new:
        title += " <i>— новое</i>"
    lines = [title]

    if h.source == "telegram":
        meta = [escape(h.via)]
        if h.start:
            meta.append(fmt_range(h.start, h.end, now))
        if h.summary:
            meta.append(escape(h.summary))
        lines.append(" · ".join(meta))
        return "\n".join(lines)

    meta = []
    if h.start:
        meta.append(fmt_range(h.start, h.end, now))
    elif h.dates_text:
        meta.append(escape(h.dates_text))
    if h.online is True:
        meta.append("онлайн")
    elif h.location:
        meta.append(escape(h.location))
    meta.append(escape(SOURCE_NAMES.get(h.source, h.source)))
    if h.prize:
        meta.append(escape(h.prize))
    lines.append(" · ".join(meta))

    extra = []
    if h.reg_deadline:
        extra.append(f"регистрация до {fmt_day(h.reg_deadline, now)}")
    topics = [TOPICS[t][0] for t in sorted(topics_of(h))]
    if topics:
        extra.append(", ".join(topics))
    if extra:
        lines.append(escape(" · ".join(extra)))
    return "\n".join(lines)


def select(items: list[Hackathon], filters: Filters, now: datetime) -> list[Hackathon]:
    """Предстоящие события под фильтр, без дублей по названию, отсортированные по дате."""
    seen_titles = set()
    result = []
    far = now + timedelta(days=10_000)
    for h in sorted(items, key=lambda h: h.start or far):
        key = re.sub(r"\W+", "", h.title.lower())
        if key in seen_titles or not h.is_upcoming(now) or not filters.matches(h, now):
            continue
        seen_titles.add(key)
        result.append(h)
    return result


def build_sections(items: list[Hackathon], new_uids: set[str], now: datetime, limit: int) -> tuple[list[Section], int]:
    week, month, later, ongoing, posts = [], [], [], [], []
    for h in items:
        if h.source == "telegram":
            posts.append(h)
        elif h.start and h.start.date() < now.date():
            ongoing.append(h)
        elif h.start and h.start <= now + timedelta(days=7):
            week.append(h)
        elif h.start and h.start <= now + timedelta(days=31):
            month.append(h)
        else:
            later.append(h)

    groups = [
        ("Стартуют в ближайшие 7 дней", week, False),
        ("В ближайший месяц", month, False),
        ("Уже идут, регистрация открыта", ongoing, True),
        ("Позже", later, True),
        ("Анонсы из Telegram-каналов", posts, False),
    ]
    sections, shown = [], 0
    for title, group, collapsed in groups:
        take = group[: max(limit - shown, 0)]
        if not take:
            continue
        shown += len(take)
        sections.append(Section(f"{title} · {len(group)}", [format_item(h, h.uid in new_uids, now) for h in take], collapsed))
    return sections, len(items) - shown


def build_digest(
    items: list[Hackathon],
    new_uids: set[str],
    now: datetime,
    sources: list[str],
    filters: Filters | None = None,
    limit: int = 30,
) -> list[str]:
    """Собирает дайджест и режет его на сообщения не длиннее лимита Telegram."""
    if not items:
        return []
    new_count = sum(h.uid in new_uids for h in items)
    header = [f"<b>Хакатоны на {now.day} {MONTHS_FULL[now.month - 1]}</b>"]
    summary = f"{len(items)} {plural(len(items), ('событие', 'события', 'событий'))}"
    if new_count:
        summary += f", новых: {new_count}"
    if filters and not filters.is_empty():
        summary += f". Фильтр: {escape(filters.describe())}"
    header.append(summary)

    sections, hidden = build_sections(items, new_uids, now, limit)
    links = [f'<a href="{SOURCE_LINKS[s]}">{SOURCE_NAMES[s]}</a>' for s in sources if s in SOURCE_LINKS]
    footer = []
    if hidden:
        footer.append(f"Не поместилось ещё {hidden}. Сузить список можно через /filter.")
    if links:
        footer.append("Полные списки: " + " · ".join(links))
    return pack("\n".join(header), sections, "\n".join(footer))


def pack(header: str, sections: list[Section], footer: str) -> list[str]:
    """Раскладывает секции по сообщениям; раскрывающаяся цитата не рвётся между сообщениями."""
    messages: list[str] = []
    current = header

    def push(chunk: str) -> None:
        nonlocal current
        candidate = f"{current}\n\n{chunk}" if current else chunk
        if len(candidate) > TG_LIMIT and current:
            messages.append(current)
            current = chunk
        else:
            current = candidate

    for sec in sections:
        title = f"<b>{escape(sec.title)}</b>"
        chunks, buf = [], []
        overhead = len(title) + 40
        for item in sec.items:
            if buf and overhead + len("\n\n".join([*buf, item])) > TG_LIMIT:
                chunks.append(buf)
                buf = []
            buf.append(item)
        if buf:
            chunks.append(buf)
        for i, chunk in enumerate(chunks):
            body = "\n\n".join(chunk)
            if sec.collapsed:
                body = f"<blockquote expandable>{body}</blockquote>"
            push(f"{title}\n{body}" if i == 0 else body)
    if footer:
        push(footer)
    if current:
        messages.append(current)
    return messages
