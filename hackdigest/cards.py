"""Карточка одного хакатона: подпись к талону, календарь .ics, напоминания и сообщения о переносах."""
from datetime import datetime, timedelta
from html import escape

from hackdigest.dates import MSK
from hackdigest.digest import SOURCE_NAMES, brief, fmt_day, fmt_range, plural
from hackdigest.models import Hackathon
from hackdigest.text import strip_emoji
from hackdigest.topics import labels, topics_of

CAPTION_LIMIT = 1024  # лимит подписи к фото в Telegram
DAYS = ("день", "дня", "дней")
HOURS = ("час", "часа", "часов")


def countdown(when: datetime, now: datetime) -> str:
    """«через 3 дня», «через 5 часов», «сегодня»."""
    left = when - now
    if left < timedelta(hours=1):
        return "меньше чем через час"
    if left < timedelta(days=1):
        h = int(left.total_seconds() // 3600)
        return f"через {h} {plural(h, HOURS)}"
    d = left.days
    return f"через {d} {plural(d, DAYS)}"


def caption(h: Hackathon, now: datetime, tracked: bool = False) -> str:
    title = escape(strip_emoji(h.title))
    lines = [f'<b><a href="{escape(h.url)}">{title}</a></b>']

    when = fmt_range(h.start, h.end, now) if h.start else escape(h.dates_text)
    place = "онлайн" if h.online else escape(h.location) if h.location else ""
    lines.append(" · ".join(p for p in (when, place) if p))

    if h.reg_deadline and h.reg_deadline >= now:
        lines.append(f"<b>Регистрация до {fmt_day(h.reg_deadline, now)}</b> — закроется {countdown(h.reg_deadline, now)}")
    elif h.start and h.start > now:
        lines.append(f"Старт {countdown(h.start, now)}")

    facts = []
    if h.prize:
        facts.append(f"призы: {escape(h.prize)}")
    if h.organizer:
        facts.append(f"организатор: {escape(h.organizer)}")
    if h.participants:
        n = h.participants
        facts.append(f"уже {n:,} {plural(n, ('участник', 'участника', 'участников'))}".replace(",", "\u202f"))
    if facts:
        line = " · ".join(facts)
        lines.append(line[0].upper() + line[1:])

    keys = topics_of(h)
    if topics := labels(keys, "direction", 3) + [t.lower() for t in labels(keys, "industry", 2)]:
        lines.append(f"<i>{escape(', '.join(topics))}</i>")

    about = h.summary if h.source == "telegram" else brief(h, limit=320)
    if about:
        lines.append("")
        lines.append(escape(about))

    source = escape(h.via) if h.source == "telegram" else SOURCE_NAMES.get(h.source, h.source)
    lines.append("")
    lines.append(f"Источник: {source}" + (" · вы следите за событием" if tracked else ""))
    text = "\n".join(lines)
    return text if len(text) <= CAPTION_LIMIT else text[: CAPTION_LIMIT - 1].rsplit("\n", 1)[0]


# ---------- календарь ----------


def _ics_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics_dt(d: datetime) -> str:
    return d.astimezone(MSK).strftime("%Y%m%dT%H%M%S")


def ics(items: list[Hackathon], now: datetime) -> bytes:
    """Календарь: событие на даты проведения (или на дедлайн, если дат нет), напоминание за день до дедлайна."""
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//hack-digest//RU", "CALSCALE:GREGORIAN",
           "BEGIN:VTIMEZONE", "TZID:Europe/Moscow", "BEGIN:STANDARD", "DTSTART:19700101T000000",
           "TZOFFSETFROM:+0300", "TZOFFSETTO:+0300", "TZNAME:MSK", "END:STANDARD", "END:VTIMEZONE"]
    for h in items:
        start = h.start or h.reg_deadline
        if not start:
            continue
        end = h.end or start + timedelta(hours=1)
        notes = [h.url]
        if h.reg_deadline:
            notes.insert(0, f"Регистрация до {fmt_day(h.reg_deadline, now)}")
        summary = strip_emoji(h.title) if h.start else f"Дедлайн регистрации: {strip_emoji(h.title)}"
        out += ["BEGIN:VEVENT", f"UID:{h.uid}@hack-digest", f"DTSTAMP:{now.strftime('%Y%m%dT%H%M%SZ')}",
                f"DTSTART;TZID=Europe/Moscow:{_ics_dt(start)}", f"DTEND;TZID=Europe/Moscow:{_ics_dt(end)}",
                f"SUMMARY:{_ics_text(summary)}", f"URL:{h.url}", f"DESCRIPTION:{_ics_text(chr(10).join(notes))}"]
        if h.location and not h.online:
            out.append(f"LOCATION:{_ics_text(h.location)}")
        if h.reg_deadline and h.start:
            # напоминание о регистрации — относительно начала события, за сутки до дедлайна
            before = start - (h.reg_deadline - timedelta(days=1))
            if before > timedelta(0):
                minutes = int(before.total_seconds() // 60)
                out += ["BEGIN:VALARM", "ACTION:DISPLAY", f"TRIGGER:-PT{minutes}M",
                        f"DESCRIPTION:{_ics_text('Завтра закрывается регистрация: ' + strip_emoji(h.title))}",
                        "END:VALARM"]
        out.append("END:VEVENT")
    out.append("END:VCALENDAR")
    return ("\r\n".join(out) + "\r\n").encode()


# ---------- напоминания ----------

# ключ -> за сколько до момента; проверяются от самого позднего к раннему
REMINDERS = (
    ("reg1", "reg_deadline", timedelta(days=1)),
    ("reg3", "reg_deadline", timedelta(days=3)),
    ("start", "start", timedelta(days=1)),
)


def due_reminder(h: Hackathon, sent: set[str], now: datetime) -> tuple[set[str], str] | None:
    """Какое напоминание пора отправить: (ключи, которые теперь считаются отправленными, текст) или None.
    Если бот пропустил ранние напоминания, отправляется только самое актуальное."""
    for key, attr, before in REMINDERS:
        moment = getattr(h, attr)
        if key in sent or not moment or not now < moment <= now + before:
            continue
        # более ранние напоминания того же типа больше не нужны
        done = sent | {k for k, a, b in REMINDERS if a == attr and b >= before}
        name = f"<b>{escape(strip_emoji(h.title))}</b>"
        if attr == "reg_deadline":
            text = f"Регистрация на {name} закроется {countdown(moment, now)}, {fmt_day(moment, now)}."
        else:
            text = f"{name} начинается {countdown(moment, now)}, {fmt_day(moment, now)}. Удачи команде!"
        return done, text
    return None


def change_notice(old: Hackathon, new: Hackathon, now: datetime) -> str | None:
    """Сообщение о переносе дат или смене формата у события, за которым следят."""
    parts = []
    if old.reg_deadline != new.reg_deadline and new.reg_deadline:
        was = fmt_day(old.reg_deadline, now) if old.reg_deadline else "не указан"
        if was != fmt_day(new.reg_deadline, now):
            parts.append(f"дедлайн регистрации: {was} → {fmt_day(new.reg_deadline, now)}")
    if (old.start, old.end) != (new.start, new.end) and new.start:
        was = fmt_range(old.start, old.end, now) or "не указаны"
        if was != fmt_range(new.start, new.end, now):
            parts.append(f"даты: {was} → {fmt_range(new.start, new.end, now)}")
    if old.online is not None and new.online is not None and old.online != new.online:
        parts.append("формат: " + ("теперь онлайн" if new.online else f"теперь очно{', ' + new.location if new.location else ''}"))
    if not parts:
        return None
    return f"Изменения в <b>{escape(strip_emoji(new.title))}</b>\n" + "\n".join(escape(p) for p in parts)
