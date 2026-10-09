"""Major League Hacking: список событий сезона вшит в страницу как JSON (Inertia)."""
import json
import re
from datetime import datetime, timezone

import aiohttp

from hackdigest.models import Hackathon

BASE = "https://www.mlh.com"
LIST_URL = f"{BASE}/seasons/{{season}}/events"
_DATA = re.compile(r'<script data-page="app" type="application/json">(.*?)</script>', re.S)


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def season(now: datetime) -> int:
    # сезон MLH начинается летом: осенью 2026 идёт сезон 2027
    return now.year + 1 if now.month >= 7 else now.year


def parse(page_html: str) -> list[Hackathon]:
    m = _DATA.search(page_html)
    if not m:
        raise ValueError("MLH: не найден JSON со списком событий")
    data = json.loads(m.group(1))
    items = []
    for e in data.get("props", {}).get("upcomingEvents", []):
        fmt = e.get("formatType", "")
        items.append(Hackathon(
            uid=f"mlh:{e['id']}",
            source="mlh",
            title=e["name"].strip(),
            url=e.get("websiteUrl") or BASE + e.get("url", ""),
            start=_dt(e.get("startsAt")),
            end=_dt(e.get("endsAt")),
            online=fmt == "digital",
            location="" if fmt == "digital" else e.get("location", ""),
            tags=tuple((e.get("customFields") or {}).get("hackathon_focus") or ()),
        ))
    return items


async def fetch(session: aiohttp.ClientSession) -> list[Hackathon]:
    url = LIST_URL.format(season=season(datetime.now(timezone.utc)))
    async with session.get(url) as resp:
        resp.raise_for_status()
        return parse(await resp.text())
