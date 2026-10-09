"""Анонсы хакатонов из публичных Telegram-каналов через веб-версию t.me/s/<channel>."""
import re
from datetime import datetime, timedelta, timezone

import aiohttp
from bs4 import BeautifulSoup

from hackdigest.dates import extract_dates
from hackdigest.models import Hackathon

# стандартный список; дополняется после проверки каналов
DEFAULT_CHANNELS: list[str] = []

KEYWORDS = re.compile(r"хакатон|hackathon|хакатн|\bctf\b|геймджем|game ?jam|дататон|datathon|кейс-чемпионат",
                      re.IGNORECASE)
MAX_AGE = timedelta(days=21)  # посты старше не берём
_USERNAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{3,31}")


def normalize_channel(value: str) -> str | None:
    """'@name', 'https://t.me/name', 't.me/s/name' -> 'name'."""
    value = value.strip()
    value = re.sub(r"^(https?://)?(www\.)?(t\.me|telegram\.me)/(s/)?", "", value)
    value = value.lstrip("@").split("/")[0].split("?")[0]
    return value.lower() if _USERNAME.fullmatch(value) else None


def _title(text: str) -> str:
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first if len(first) <= 120 else first[:119].rstrip() + "…"


def _summary(text: str, title: str) -> str:
    rest = " ".join(line.strip() for line in text.splitlines() if line.strip() and line.strip() != title)
    return rest if len(rest) <= 160 else rest[:159].rstrip() + "…"


def parse(html: str, channel: str, now: datetime | None = None) -> list[Hackathon]:
    now = now or datetime.now(timezone.utc)
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.select_one(".tgme_channel_info_header_title")
    channel_title = title_tag.get_text(strip=True) if title_tag else f"@{channel}"
    items = []
    for msg in soup.select(".tgme_widget_message[data-post]"):
        text_tag = msg.select_one(".tgme_widget_message_text")
        time_tag = msg.select_one("time[datetime]")
        if not text_tag or not time_tag:
            continue
        posted = datetime.fromisoformat(time_tag["datetime"])
        if now - posted > MAX_AGE:
            continue
        for br in text_tag.find_all("br"):
            br.replace_with("\n")
        text = text_tag.get_text()
        if not KEYWORDS.search(text):
            continue
        start, end, deadline = extract_dates(text, posted)
        if end and end < now:
            continue  # событие из поста уже прошло
        title = _title(text)
        items.append(Hackathon(
            uid=f"telegram:{msg['data-post']}",
            source="telegram",
            title=title,
            url=f"https://t.me/{msg['data-post']}",
            start=start,
            end=end,
            reg_deadline=deadline if deadline and deadline > now else None,
            summary=_summary(text, title),
            via=channel_title,
        ))
    return items


async def fetch_channel(session: aiohttp.ClientSession, channel: str) -> list[Hackathon]:
    async with session.get(f"https://t.me/s/{channel}") as resp:
        resp.raise_for_status()
        html = await resp.text()
    # несуществующий или закрытый канал отдаёт страницу без ленты сообщений
    if "tgme_channel_history" not in html:
        return []
    return parse(html, channel)
