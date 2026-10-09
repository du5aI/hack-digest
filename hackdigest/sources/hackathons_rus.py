"""хакатоны.рус — крупнейший российский агрегатор; лента «Ближайшие хакатоны» отдаётся через Tilda Feeds API."""
import re
from datetime import datetime, timedelta, timezone

import aiohttp

from hackdigest.dates import extract_dates
from hackdigest.models import Hackathon

API_URL = "https://feeds.tildaapi.com/api/getfeed/"
LIST_URL = "https://www.xn--80aa3anexr8c.xn--p1acf/"  # хакатоны.рус
FEED_UID = "617755803461"
MSK = timezone(timedelta(hours=3))
TAGS = {"CTF": "CTF", "DS/ML/AI": "AI / ML", "Game": "Game", "Blockchain": "Blockchain",
        "Для школьников": "для школьников"}
_PRIZE = re.compile(r"призов\w*\s+фонд\w*[^0-9]{0,20}([\d\s.,]+\s?(?:млн\.?\s?)?(?:₽|руб\w*))", re.IGNORECASE)


def parse(data: dict, now: datetime | None = None) -> list[Hackathon]:
    now = now or datetime.now(timezone.utc)
    items = []
    for p in data.get("posts", []):
        parts = [s.strip() for s in (p.get("parts") or "").split(",") if s.strip()]
        if "Регистрация закрыта" in parts:
            continue
        # дата в ленте — обычно конец регистрации (её выставляет редактор, время московское)
        key_date = datetime.strptime(p["date"], "%Y-%m-%d %H:%M").replace(tzinfo=MSK) if p.get("date") else None
        descr = re.sub(r"<[^>]+>", " ", p.get("descr") or "")
        start, end, deadline = extract_dates(descr, key_date or now)
        reg = deadline or key_date
        if start and reg and start < reg and not end:
            start = None  # единственная найденная дата — скорее всего та же регистрация
        prize = _PRIZE.search(descr)
        online = None
        if "online" in parts and "offline" not in parts:
            online = True
        elif "offline" in parts and "online" not in parts:
            online = False
        cities = [s for s in parts if s not in TAGS and s not in ("online", "offline") and not s.startswith("Регистрация")]
        items.append(Hackathon(
            uid=f"hackathons_rus:{p['uid']}",
            source="hackathons_rus",
            title=p["title"].strip(),
            url=p["url"],
            start=start,
            end=end,
            reg_deadline=reg if reg and reg > now else None,
            online=online,
            location=", ".join(cities),
            prize=re.sub(r"\s+", " ", prize.group(1)).strip() if prize else "",
            tags=tuple(TAGS[s] for s in parts if s in TAGS),
            description=re.sub(r"\s+", " ", descr).strip(),
        ))
    return items


async def fetch(session: aiohttp.ClientSession) -> list[Hackathon]:
    result: list[Hackathon] = []
    for page in range(1, 4):
        params = {"feeduid": FEED_UID, "size": "50", "slice": str(page),
                  "sort[date]": "asc", "filters[date][>]": "now"}
        async with session.get(API_URL, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
        result.extend(parse(data))
        if not data.get("nextslice"):
            break
    return result
