"""Анонсы хакатонов из публичных Telegram-каналов через веб-версию t.me/s/<channel>."""
import asyncio
import re
from datetime import datetime, timedelta, timezone

import aiohttp
from bs4 import BeautifulSoup

from hackdigest.dates import extract_dates
from hackdigest.models import Hackathon
from hackdigest.text import _EMOJI, guess_online

# Агрегаторы почти целиком состоят из анонсов — читаем их ленту.
AGGREGATORS = [
    "hackathonsrus",  # хакатоны.рус
    "hackathons",  # Хакатоны || Hackathon list
    "russianhackers_channel",  # Russian Hackers, в т.ч. сводки дедлайнов
    "codenrock",
    "markhack_ural",  # ИНАЧЕ | Хакатоны (Урал)
    "leaders_hack",  # Лидеры цифровой трансформации
    "ctfnews",  # CTF News: анонсы российских CTF
    "hackrnd",  # Хакатон Осень (Ростов-на-Дону)
]
# Вузы и компании пишут о хакатонах редко — у них ищем посты по слову «хакатон».
UNIVERSITIES = [
    "fcs_hse",  # ФКН ВШЭ
    "bmstu1830",  # МГТУ им. Баумана
    "mephi_of",  # МИФИ
    "universityinnopolis",
    "dx_itmo",  # ФТИИ ИТМО
    "urfu_ru",
    "miptru",  # МФТИ
    "t_central_university",  # Центральный университет
]
COMPANIES = [
    "changellenge",
    "sberstudent",
    "vkeducation_about",
    "tbank_education",
    "education_yandex",
    "truetechcommunity",  # МТС True Tech
    "alfastudents",  # Альфа-Будущее
]
# Команды и клубы CTF: про хакатоны не пишут, ищем по слову CTF.
CTF_TEAMS = [
    "kubctf",  # KubSTU CTF (Кубанский ГТУ)
]
DEFAULT_CHANNELS = [*AGGREGATORS, *UNIVERSITIES, *COMPANIES, *CTF_TEAMS]
_FEED_CHANNELS = set(AGGREGATORS)
DEFAULT_QUERY = "хакатон"
QUERIES = {c: "CTF" for c in CTF_TEAMS}  # своё слово для поиска там, где «хакатон» не встречается

STRONG = re.compile(r"хакатон|hackathon|геймджем|game ?jam|datathon|дататон|датасон|(?<![a-zа-я])ctf(?![a-zа-я])"
                    r"|кейс-чемпионат|чемпионат по программированию", re.IGNORECASE)
SIGNALS = re.compile(r"регистрац|зарегистр|подать заявку|заявк[иу]|дедлайн|призов\w* фонд|₽|руб|\$|"
                     r"даты проведения|когда:|формат:|онлайн|офлайн|участ", re.IGNORECASE)
# итоги и рассказы о прошедшем; просто «победители получат…» в анонсе — не итоги
RECAP = re.compile(r"итоги|победител\w* (?:хакатона|стали|определ|объявлен)|поздрав\w* победител|(?:стали|наши \w+ —) победител"
                   r"|подвели|наградили|состоял|прош[её]л(?! отбор)|вебинар|рассказыва", re.IGNORECASE)
NOT_EVENT = re.compile(r"курс|вакансi|ваканси|подкаст|стажировк|интенсив", re.IGNORECASE)
MAX_AGE = timedelta(days=45)  # посты старше не берём; у оставшихся ещё должна быть дата в будущем
# строка сводки дедлайнов: «до 16.10 — О!Хакатон 2026», следом ссылка
_ROUNDUP_LINE = re.compile(r"^до\s+(\d{1,2}\.\d{1,2}(?:\.\d{2,4})?)\s*[—–-]\s*(.{3,120})$", re.IGNORECASE)
RETRIES = 3


def is_announcement(text: str) -> bool:
    """Анонс — есть слово «хакатон» и признаки приглашения (регистрация, призы, даты), а не итоги."""
    return bool(STRONG.search(text) and SIGNALS.search(text) and not RECAP.search(text[:300]))


def clean(text: str) -> str:
    text = _EMOJI.sub(" ", text)
    return "\n".join(re.sub(r"[ \t]+", " ", line).strip(" -—•|:") for line in text.splitlines())
_USERNAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{3,31}")


def normalize_channel(value: str) -> str | None:
    """'@name', 'https://t.me/name', 't.me/s/name' -> 'name'."""
    value = value.strip()
    value = re.sub(r"^(https?://)?(www\.)?(t\.me|telegram\.me)/(s/)?", "", value)
    value = value.lstrip("@").split("/")[0].split("?")[0]
    return value.lower() if _USERNAME.fullmatch(value) else None


def _is_hashtags(line: str) -> bool:
    return bool(re.fullmatch(r"(#\w+\s*)+", line))


def _title(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip() and not _is_hashtags(line.strip())]
    # заголовок поста — короткая строка с заглавной буквы, а не вопрос или зачин истории
    first = next((line for line in lines[:5] if len(line) <= 100 and (line[0].isupper() or line[0] in "«\"")
                  and not line.endswith(("?", "…"))), lines[0] if lines else "")
    if first and first[0].islower():
        # пост без заголовка, со строчной буквы: берём имя события — «Точка сборки», Hack&Change
        name = re.search(r"«([^»]{3,60})»|\b((?:[A-Z][\w!]*\s*(?:&|x|×)\s*)?Hack\w*(?:\s*&\s*[A-Z]\w+)?)", text)
        if name:
            first = name[1] or name[2]
    return first if len(first) <= 120 else first[:119].rstrip() + "…"


def parse_roundup(text: str, post: str, via: str, now: datetime) -> list[Hackathon]:
    """Пост-сводка «до 16.10 — Название / ссылка» — каждая строка становится отдельным событием."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    items = []
    for i, line in enumerate(lines):
        m = _ROUNDUP_LINE.match(line)
        if not m:
            continue
        _, _, deadline = extract_dates(f"до {m[1]}", now)
        if not deadline or deadline < now:
            continue
        link = lines[i + 1] if i + 1 < len(lines) and re.match(r"(https?://)?[\w-]+(\.[\w-]+)+/?\S*$", lines[i + 1]) else ""
        url = (link if link.startswith("http") else f"https://{link}") if link else f"https://t.me/{post}"
        items.append(Hackathon(uid=f"telegram:{post}#{i}", source="telegram", title=m[2].strip(), url=url,
                               reg_deadline=deadline, summary="", via=via))
    return items


def _summary(text: str, title: str) -> str:
    rest = " ".join(line.strip() for line in text.splitlines()
                    if line.strip() and line.strip() != title and not _is_hashtags(line.strip()))
    rest = re.sub(r"^(описание|подробнее|о чём|что):\s*", "", rest, flags=re.IGNORECASE)
    return rest if len(rest) <= 160 else rest[:159].rstrip() + "…"


def parse(html: str, channel: str, now: datetime | None = None) -> list[Hackathon]:
    now = now or datetime.now(timezone.utc)
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.select_one(".tgme_channel_info_header_title")
    seen_posts = set()
    channel_title = title_tag.get_text(strip=True) if title_tag else f"@{channel}"
    items = []
    for msg in soup.select(".tgme_widget_message[data-post]"):
        if "service_message" in msg.get("class", []) or msg["data-post"] in seen_posts:
            continue
        seen_posts.add(msg["data-post"])
        # js-message_text — сам пост; у цитаты в ответе тот же базовый класс, но js-message_reply_text
        text_tag = msg.select_one(".tgme_widget_message_text.js-message_text") or msg.select_one(
            ".tgme_widget_message_text:not(.js-message_reply_text)")
        time_tag = msg.select_one("time[datetime]")
        if not text_tag or not time_tag:
            continue
        posted = datetime.fromisoformat(time_tag["datetime"])
        if now - posted > MAX_AGE:
            continue
        for br in text_tag.find_all("br"):
            br.replace_with("\n")
        text = clean(text_tag.get_text())
        if sum(bool(_ROUNDUP_LINE.match(line.strip())) for line in text.splitlines()) >= 3:
            items += parse_roundup(text, msg["data-post"], channel_title, now)
            continue
        if not is_announcement(text):
            continue
        start, end, deadline = extract_dates(text, posted)
        if not start and not deadline:
            continue  # в анонсе всегда есть даты; без них это скорее статья или история
        if deadline and deadline < now:
            continue  # регистрация уже закрыта
        last_day = end or (start and start.replace(hour=23, minute=59))
        if last_day and last_day < now and not deadline:
            continue  # событие из поста уже прошло
        title = _title(text)
        if NOT_EVENT.search(title) and not STRONG.search(title):
            continue  # курс или вакансия, где хакатон — лишь часть программы
        items.append(Hackathon(
            uid=f"telegram:{msg['data-post']}",
            source="telegram",
            title=title,
            url=f"https://t.me/{msg['data-post']}",
            start=start,
            end=end,
            reg_deadline=deadline if deadline and deadline > now else None,
            online=guess_online(text),
            summary=_summary(text, title),
            description=text,
            via=channel_title,
        ))
    return items


class ChannelNotFound(Exception):
    pass


async def _get(session: aiohttp.ClientSession, url: str, params: dict) -> str:
    for attempt in range(RETRIES):
        try:
            async with session.get(url, params=params, allow_redirects=False) as resp:
                # несуществующий канал, пользователь, бот или группа — редирект на t.me/<name>
                if resp.status in (301, 302):
                    raise ChannelNotFound(url)
                resp.raise_for_status()
                return await resp.text()
        except (aiohttp.ClientConnectionError, asyncio.TimeoutError):
            if attempt == RETRIES - 1:
                raise
            await asyncio.sleep(2 ** attempt)
    raise AssertionError("unreachable")


async def fetch_channel(session: aiohttp.ClientSession, channel: str) -> list[Hackathon]:
    params = {} if channel in _FEED_CHANNELS else {"q": QUERIES.get(channel, DEFAULT_QUERY)}
    try:
        html = await _get(session, f"https://t.me/s/{channel}", params)
    except ChannelNotFound:
        return []
    return parse(html, channel)


async def channel_exists(session: aiohttp.ClientSession, channel: str) -> bool:
    try:
        html = await _get(session, f"https://t.me/s/{channel}", {})
    except ChannelNotFound:
        return False
    return "data-post=" in html
