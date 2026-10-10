"""Changellenge >>: кейс-чемпионаты и хакатоны для студентов, карточки на странице чемпионатов."""
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

import aiohttp
from bs4 import BeautifulSoup

from hackdigest.dates import extract_dates
from hackdigest.models import Hackathon
from hackdigest.text import guess_online

LIST_URL = "https://changellenge.com/championships/"
# бизнес-кейсы (консалтинг, страхование, маркетинг) пропускаем — берём хакатоны и IT-чемпионаты
_IT = re.compile(r"хакатон|hack|(?<![a-zа-я])(?:it|ит|ии|ai|ml|data)(?![a-zа-я])|дата|разработ|программ|инженер|engineer"
                 r"|аналитик данных|machine learning|машинн\w* обуч", re.IGNORECASE)


def _url(href: str) -> str:
    url = urljoin(LIST_URL, href)
    # у своих страниц убираем служебный ?src=chemp, у внешних ссылок оставляем как есть
    return url.split("?")[0] if urlsplit(url).netloc == urlsplit(LIST_URL).netloc else url


def parse(page_html: str, now: datetime | None = None) -> list[Hackathon]:
    now = now or datetime.now(timezone.utc)
    soup = BeautifulSoup(page_html, "html.parser")
    items = []
    for card in soup.select("article.champ-card[data-code]"):
        link = card.select_one("h3.champ-card__title a") or card.select_one("a[href]")
        if not link:
            continue
        title = link.get_text(" ", strip=True)
        descr_tag = card.select_one(".champ-card__descr")
        descr = descr_tag.get_text(" ", strip=True) if descr_tag else ""
        if not _IT.search(f"{title} {descr}"):
            continue
        chips = " ".join(c.get_text(" ", strip=True) for c in card.select(".champ-card__chip"))
        # на карточке — дата старта без года («09 ноября»)
        start, _, _ = extract_dates(chips, now)
        if start and start.date() < now.date():
            continue  # уже начался
        company = card.select_one(".champ-card__company")
        items.append(Hackathon(
            uid=f"changellenge:{card['data-code']}",
            source="changellenge",
            title=title,
            url=_url(link.get("href") or ""),
            start=start,
            online=guess_online(descr),
            dates_text="" if start else chips,
            description=descr,
            organizer=company.get_text(" ", strip=True).rstrip("> ").strip() if company else "",
        ))
    return items


async def fetch(session: aiohttp.ClientSession) -> list[Hackathon]:
    async with session.get(LIST_URL) as resp:
        resp.raise_for_status()
        return parse(await resp.text())
