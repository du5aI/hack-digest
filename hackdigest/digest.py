import re
from html import escape

from hackdigest.models import Hackathon

SOURCE_TITLES = {
    "devpost": "🌍 Devpost (международные)",
    "codenrock": "🇷🇺 Codenrock",
}
TG_LIMIT = 4096

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


def _plural(n: int, forms: tuple[str, str, str]) -> str:
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
            word = _plural(n, _FORMS[unit])
            return word if n == 1 else f"{n} {word}"
    return f"{seconds} с"


def format_item(h: Hackathon, is_new: bool) -> str:
    line = f"{'🆕 ' if is_new else '• '}<a href=\"{escape(h.url)}\">{escape(h.title)}</a>"
    details = [d for d in (h.dates and f"📅 {h.dates}", h.location and f"📍 {h.location}",
                           h.prize and f"🏆 {h.prize}") if d]
    if h.tags:
        details.append("🏷 " + ", ".join(h.tags[:3]))
    if details:
        line += "\n    " + escape(" · ".join(details))
    return line


def build_digest(
    by_source: dict[str, list[Hackathon]], new_uids: set[str], per_source: int = 10, only_new: bool = False
) -> list[str]:
    """Собирает дайджест и режет его на сообщения не длиннее лимита Telegram."""
    blocks = []
    for source, items in by_source.items():
        if only_new:
            items = [h for h in items if h.uid in new_uids]
        if not items:
            continue
        shown = items[:per_source]
        block = [f"<b>{SOURCE_TITLES.get(source, source)}</b>"]
        block += [format_item(h, h.uid in new_uids) for h in shown]
        if len(items) > len(shown):
            block.append(f"<i>…и ещё {len(items) - len(shown)}</i>")
        blocks.append("\n".join(block))
    if not blocks:
        return []

    header = "🗓 <b>Дайджест ближайших хакатонов</b>"
    messages, current = [], header
    for block in blocks:
        for part in _split(block):
            candidate = f"{current}\n\n{part}"
            if len(candidate) > TG_LIMIT:
                messages.append(current)
                current = part
            else:
                current = candidate
    messages.append(current)
    return messages


def _split(block: str) -> list[str]:
    """Разбивает слишком длинный блок по элементам, не отрывая строку деталей от названия."""
    if len(block) <= TG_LIMIT:
        return [block]
    parts, current = [], ""
    for line in re.split(r"\n(?! )", block):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > TG_LIMIT:
            parts.append(current)
            current = line
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts
