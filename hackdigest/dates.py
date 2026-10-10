"""Достаём даты из свободного текста анонса: «15–17 ноября», «до 15 октября», «15.10.2026»."""
import re
from datetime import datetime, timedelta, timezone

# Москва без перехода на летнее время; даты из текста анонсов и показ дат — по московскому времени
MSK = timezone(timedelta(hours=3), "MSK")

_MONTHS = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "ма": 5, "июн": 6, "июл": 7, "авг": 8,
    "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
}
_MONTH_RE = r"(январ[яь]|феврал[яь]|марта?|апрел[яь]|ма[йя]|июн[яь]|июл[яь]|августа?|сентябр[яь]|октябр[яь]|ноябр[яь]|декабр[яь])"
# «15–17 ноября», «15 - 17 ноября», «30 октября – 2 ноября», «15 ноября»
_RANGE_WORDS = re.compile(
    rf"(?<!\d)(\d{{1,2}})(?:\s*{_MONTH_RE})?(?:\s*(?:[–—-]|по|до)\s*(\d{{1,2}}))?\s*{_MONTH_RE}(?:\s*(\d{{4}}))?",
    re.IGNORECASE,
)
# «15.10.2026», «до 06.10»; не цепляем «2.500.000» и время «10.30»
_NUMERIC = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})(?:\.(\d{4}|\d{2}))?(?![\d.]*\d)"
                      r"(?:\s*[–—-]\s*(\d{1,2})\.(\d{1,2})(?:\.(\d{4}|\d{2}))?)?")
_DEADLINE_CUE = re.compile(r"(регистрац|заявк|до\s*$|deadline|дедлайн|приём|прием)", re.IGNORECASE)


def _month(word: str) -> int:
    word = word.lower()
    if word.startswith("мар"):
        return 3
    if word.startswith("ма"):
        return 5
    return _MONTHS[word[:3]]


def _make(year: int, month: int, day: int, ref: datetime) -> datetime | None:
    try:
        d = datetime(year, month, day, tzinfo=MSK)
    except ValueError:
        return None
    # без явного года: дата «в прошлом» больше чем на 2 месяца — значит, следующий год
    if (ref - d).days > 60:
        d = d.replace(year=year + 1)
    return d


def _candidates(text: str, ref: datetime):
    for m in _RANGE_WORDS.finditer(text):
        d1, mon1, d2, mon2, year = m.groups()
        y = int(year) if year else ref.year
        end_month = _month(mon2)
        start_month = _month(mon1) if mon1 else end_month
        start = _make(y, start_month, int(d1), ref)
        end = _make(y, end_month, int(d2), ref) if d2 else None
        if start:
            yield m.start(), start, end
    for m in _NUMERIC.finditer(text):
        d1, m1, y1, d2, m2, y2 = m.groups()
        if not 1 <= int(m1) <= 12:
            continue
        year = int(y1) if y1 else ref.year
        year += 2000 if year < 100 else 0
        start = _make(year, int(m1), int(d1), ref)
        end = None
        if d2 and 1 <= int(m2) <= 12:
            year2 = int(y2) + (2000 if y2 and int(y2) < 100 else 0) if y2 else year
            end = _make(year2, int(m2), int(d2), ref)
        if start:
            yield m.start(), start, end


def extract_dates(text: str, ref: datetime) -> tuple[datetime | None, datetime | None, datetime | None]:
    """(начало, конец, дедлайн регистрации). Дедлайн — дата, перед которой в той же фразе
    говорится о регистрации/заявках; первая другая дата считается датой проведения."""
    start = end = deadline = None
    for pos, d_start, d_end in sorted(_candidates(text, ref), key=lambda c: c[0]):
        before = text[max(0, pos - 40):pos]
        if deadline is None and _DEADLINE_CUE.search(before):
            # «регистрация до 27 октября» — включая весь день 27-го
            deadline = (d_end or d_start).replace(hour=23, minute=59)
        elif start is None:
            start, end = d_start, d_end
    if end and start and end < start:
        end = None
    if end:
        end = end.replace(hour=23, minute=59)
    return start, end, deadline
