import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from html import escape

from hackdigest.dates import MSK
from hackdigest.filters import Filters
from hackdigest.topics import labels, topics_of
from hackdigest.models import Hackathon
from hackdigest.text import strip_emoji

TG_LIMIT = 4096

SOURCE_NAMES = {
    "hackathons_rus": "хакатоны.рус",
    "leader_id": "Leader-ID",
    "devpost": "Devpost",
    "codenrock": "Codenrock",
    "mlh": "MLH",
    "devfolio": "Devfolio",
    "telegram": "Telegram-каналы",
}
SOURCE_LINKS = {
    "hackathons_rus": "https://www.xn--80aa3anexr8c.xn--p1acf/",
    "leader_id": "https://leader-id.ru/events",
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
    d = d.astimezone(MSK)
    s = f"{d.day} {MONTHS_SHORT[d.month - 1]}"
    return s if d.year == now.year else f"{s} {d.year}"


def fmt_range(start: datetime | None, end: datetime | None, now: datetime) -> str:
    if not start:
        return ""
    start, end = start.astimezone(MSK), end and end.astimezone(MSK)
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
    rest: list[str] = field(default_factory=list)  # не вошедшие в лимит — одной строкой каждое, свёрнуто
    hidden: int = 0  # сколько событий не вошло в лимит

URGENT = timedelta(days=3)  # регистрация закрывается скоро — событие поднимается в «Горит»
REST_LIMIT = 40  # сколько событий показывать в свёрнутом хвосте секции

def brief(h: Hackathon, limit: int = 180) -> str:
    """Первая фраза описания — о чём хакатон. Пусто, если описание просто повторяет название."""
    text = strip_emoji(re.sub(r"\s+", " ", h.description)).strip()
    if not text:
        return ""
    # конец первой фразы, но не раньше 40 символов: «О! Хакатон» — не конец предложения
    ends = [m.start() for m in re.finditer(r"(?<=[.!?])\s+(?=[A-ZА-ЯЁ«\"])", text) if m.start() >= 40]
    sentence = text[: ends[0]] if ends else text
    if title_key(sentence) == title_key(h.title):
        return ""
    if len(sentence) > limit:
        sentence = sentence[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:—-") + "…"
    return sentence


def topics_line(h: Hackathon) -> str:
    keys = topics_of(h)
    parts = []
    # длинные описания с несколькими треками упоминают всё подряд — показываем самое выраженное
    if direction := labels(keys, "direction", limit=3):
        parts.append("Направление: " + ", ".join(direction))
    if industry := labels(keys, "industry", limit=2):
        parts.append("Сфера: " + ", ".join(industry).lower())
    if audience := labels(keys, "audience"):
        parts.append(", ".join(audience))
    return " · ".join(parts)


CardUrl = Callable[[Hackathon], str]  # ссылка, открывающая карточку события в боте


def format_item(h: Hackathon, is_new: bool, now: datetime, card_url: CardUrl | None = None) -> str:
    title = f'<a href="{escape(h.url)}"><b>{escape(strip_emoji(h.title))}</b></a>'
    if is_new:
        title += " <i>— новое</i>"
    lines = [title]

    meta = []
    if h.source == "telegram":
        meta.append(escape(h.via))
    if h.start:
        meta.append(fmt_range(h.start, h.end, now))
    elif h.dates_text:
        meta.append(escape(h.dates_text))
    if h.source != "telegram":
        if h.online is True:
            meta.append("онлайн")
        elif h.location:
            meta.append(escape(h.location))
        meta.append(escape(SOURCE_NAMES.get(h.source, h.source)))
        if h.prize:
            meta.append(escape(h.prize))
    if h.reg_deadline and h.reg_deadline >= now:
        meta.append(f"регистрация до {fmt_day(h.reg_deadline, now)}")
    if card_url:
        meta.append(f'<a href="{escape(card_url(h))}">карточка</a>')
    lines.append(" · ".join(meta))

    if topics := topics_line(h):
        lines.append(f"<i>{escape(topics)}</i>")
    about = h.summary if h.source == "telegram" else brief(h)
    if about:
        lines.append(escape(about))
    return "\n".join(lines)


def format_line(h: Hackathon, now: datetime) -> str:
    """Событие одной строкой — для свёрнутого хвоста секции."""
    parts = [f'<a href="{escape(h.url)}">{escape(strip_emoji(h.title))}</a>']
    if h.start:
        parts.append(fmt_range(h.start, h.end, now))
    if h.reg_deadline and h.reg_deadline >= now:
        parts.append(f"рег. до {fmt_day(h.reg_deadline, now)}")
    return " · ".join(parts)


def title_key(title: str) -> str:
    """Название без года, служебных слов и пунктуации — для поиска дублей между источниками."""
    t = re.sub(r"20\d\d|хакатон\w*|hackathon|всероссийск\w*|международн\w*", "", title.lower())
    return re.sub(r"\W+", "", t)


def _raw_key(text: str) -> str:
    """Текст без пунктуации и года, но со словом «хакатон»: «О! Хакатон 2026» -> «охакатон»."""
    return re.sub(r"20\d\d|\W+|_", "", text.lower())


def _name_keys(title: str, min_len: int = 5) -> set[str]:
    """Ключи для поиска упоминаний: всё название, имя в «ёлочках» («Точка сборки»),
    а для коротких названий вроде «О! Хакатон» — название вместе со словом «хакатон»."""
    keys = {title_key(title)} | {title_key(q) for q in re.findall(r"«([^»]{3,})»", title)}
    keys = {k for k in keys if len(k) >= min_len}
    if not keys and len(raw := _raw_key(title)) >= 6:
        keys.add(raw)
    return keys


_MERGEABLE = ("start", "end", "reg_deadline", "online", "location", "prize", "description")


def merge(main: Hackathon, extra: Hackathon) -> Hackathon:
    """Дополняет пустые поля записи данными дубля с другого источника."""
    updates = {f: getattr(extra, f) for f in _MERGEABLE
               if getattr(main, f) in (None, "") and getattr(extra, f) not in (None, "")}
    if len(extra.description) > 2 * len(main.description):  # одна рекламная фраза против нормального описания
        updates["description"] = extra.description
    if updates.get("start") and main.end and not updates.get("end"):
        updates["end"] = extra.end  # не смешиваем начало одного источника с концом другого
    if main.reg_deadline and extra.reg_deadline and extra.reg_deadline < main.reg_deadline:
        updates["reg_deadline"] = extra.reg_deadline  # источники расходятся — честнее ранний дедлайн
    if main.online and extra.online is False:
        # один источник пишет «онлайн», другой знает город — скорее всего, событие очное
        updates.update(online=False, location=main.location or extra.location)
    return replace(main, tags=tuple(dict.fromkeys(main.tags + extra.tags)), **updates)


def select(items: list[Hackathon], filters: Filters, now: datetime) -> list[Hackathon]:
    """Предстоящие события под фильтр, без дублей, отсортированные по ближайшей дате.
    Анонсы из каналов о событиях, которые уже есть с сайтов, и репосты одного анонса отбрасываются."""
    far = now + timedelta(days=10_000)
    # сначала склеиваем дубли (с дополнением данных), потом фильтруем — иначе фильтр по теме
    # мог бы отбросить запись с описанием и оставить её «бедный» дубль
    sites: list[Hackathon] = []
    posts, seen = [], []
    for h in sorted(items, key=lambda h: h.key_date or far):
        if h.source == "telegram":
            posts.append(h)
            continue
        key = title_key(h.title)
        if len(key) < 4:  # «О! Хакатон» -> «о»: такой ключ ничего не значит, сравниваем название целиком
            key = "=" + re.sub(r"20\d\d|\W+", "", h.title.lower())
        # «KubSTU CTF 2026» и «KubSTU CTF 2026 Autumn Edition» — одно и то же
        same = next((i for i, k in enumerate(seen)
                     if key == k or (min(len(key), len(k)) >= 6 and (key.startswith(k) or k.startswith(key)))), None)
        if same is not None:
            sites[same] = merge(sites[same], h)
            continue
        seen.append(key)
        sites.append(h)
    sites = [h for h in sites if h.is_upcoming(now) and filters.matches(h, now)]
    sites.sort(key=lambda h: h.key_date or far)
    posts = [p for p in posts if p.is_upcoming(now) and filters.matches(p, now)]
    known = set().union(*(_name_keys(h.title) for h in sites)) if sites else set()
    fresh_posts, taken = [], []  # taken — (ключи названия, текст) уже принятых анонсов
    for p in posts:
        full = f"{p.title} {p.description or p.summary}"
        text = title_key(full) + "|" + _raw_key(full)
        own = _name_keys(p.title, 4)
        # тот же хакатон уже есть с сайта или в другом канале (репост, анонс от вуза-партнёра)
        if any(k in text for k in known) or any(k in t or any(o in text for o in keys)
                                                for keys, t in taken for k in own):
            continue
        taken.append((own, text))
        fresh_posts.append(p)
    return sites + fresh_posts


def board_order(items: list[Hackathon], now: datetime) -> list[Hackathon]:
    """События для табло: только с датами, по ближайшему действию — старту или концу регистрации."""
    far = now + timedelta(days=10_000)

    def next_moment(h: Hackathon) -> datetime:
        return min((d for d in (h.start, h.reg_deadline) if d and d >= now), default=far)

    dated = [h for h in items if (h.start or h.reg_deadline) and next_moment(h) < far]
    return sorted(dated, key=next_moment)


def build_sections(items: list[Hackathon], new_uids: set[str], now: datetime, limit: int,
                   card_url: CardUrl | None = None) -> list[Section]:
    """limit — сколько событий показывать в каждой секции; остальные сворачиваются в «и ещё N»."""
    urgent, week, month, later, ongoing, posts = [], [], [], [], [], []
    for h in items:
        when = h.key_date
        if h.reg_deadline and now <= h.reg_deadline <= now + URGENT:
            urgent.append(h)
        elif h.source == "telegram":
            posts.append(h)
        elif h.start and h.start.astimezone(MSK).date() < now.astimezone(MSK).date():
            ongoing.append(h)
        elif when and when <= now + timedelta(days=7):
            week.append(h)
        elif when and when <= now + timedelta(days=31):
            month.append(h)
        else:
            later.append(h)
    # сначала новые для чата анонсы
    posts.sort(key=lambda h: h.uid not in new_uids)
    urgent.sort(key=lambda h: h.reg_deadline)

    groups = [
        ("Горит: регистрация закрывается в ближайшие 3 дня", urgent, False),
        ("Ближайшие 7 дней", week, False),
        ("В ближайший месяц", month, False),
        ("Уже идут, регистрация открыта", ongoing, True),
        ("Позже", later, True),
        ("Анонсы из Telegram-каналов", posts, False),
    ]
    sections = []
    for title, group, collapsed in groups:
        if not group:
            continue
        lines = [format_item(h, h.uid in new_uids, now, card_url) for h in group[:limit]]
        rest = [format_line(h, now) for h in group[limit:limit + REST_LIMIT]]
        if len(group) > limit + REST_LIMIT:
            rest.append(f"<i>и ещё {len(group) - limit - REST_LIMIT}</i>")
        sections.append(Section(f"{title} · {len(group)}", lines, collapsed, rest, max(len(group) - limit, 0)))
    return sections


def build_digest(
    items: list[Hackathon],
    new_uids: set[str],
    now: datetime,
    sources: list[str],
    filters: Filters | None = None,
    limit: int = 10,
    failed: list[str] = (),
    card_url: CardUrl | None = None,
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

    sections = build_sections(items, new_uids, now, limit, card_url)
    links = [f'<a href="{SOURCE_LINKS[s]}">{SOURCE_NAMES[s]}</a>' for s in sources if s in SOURCE_LINKS]
    footer = []
    if failed:
        footer.append("<i>Не ответили: " + ", ".join(SOURCE_NAMES.get(s, s) for s in failed)
                      + " — их событий в этот раз может не хватать</i>")
    footer.append("Настроить, что попадает в дайджест: /filter")
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

    def chunked(lines: list[str], sep: str, overhead: int) -> list[str]:
        chunks, buf = [], []
        for line in lines:
            if buf and overhead + len(sep.join([*buf, line])) > TG_LIMIT:
                chunks.append(sep.join(buf))
                buf = []
            buf.append(line)
        return [*chunks, sep.join(buf)] if buf else chunks

    for sec in sections:
        title = f"<b>{escape(sec.title)}</b>"
        for i, body in enumerate(chunked(sec.items, "\n\n", len(title) + 40)):
            if sec.collapsed:
                body = f"<blockquote expandable>{body}</blockquote>"
            push(f"{title}\n{body}" if i == 0 else body)
        if sec.rest:
            for i, body in enumerate(chunked(sec.rest, "\n", 80)):
                head = f"<i>Ещё {sec.hidden} — нажмите, чтобы раскрыть</i>\n" if i == 0 else ""
                push(f"{head}<blockquote expandable>{body}</blockquote>")
    if footer:
        push(footer)
    if current:
        messages.append(current)
    return messages
