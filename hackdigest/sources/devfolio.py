"""Devfolio: публичный JSON API, в основном индийские и международные хакатоны."""
from datetime import datetime

import aiohttp

from hackdigest.models import Hackathon

API_URL = "https://api.devfolio.co/api/hackathons"
LIST_URL = "https://devfolio.co/hackathons"
# application_open — регистрация открыта, upcoming — регистрация ещё не открылась
FILTERS = ("application_open", "upcoming")


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def parse(data: dict) -> list[Hackathon]:
    items = []
    for h in data.get("result", []):
        settings = h.get("hackathon_setting") or {}
        subdomain = settings.get("subdomain") or h.get("slug")
        online = h.get("is_online")
        place = ", ".join(p for p in (h.get("city"), h.get("country")) if p) or (h.get("location") or "")
        items.append(Hackathon(
            uid=f"devfolio:{h['uuid']}",
            source="devfolio",
            title=h["name"].strip(),
            url=f"https://{subdomain}.devfolio.co/",
            start=_dt(h.get("starts_at")),
            end=_dt(h.get("ends_at")),
            reg_deadline=_dt(settings.get("reg_ends_at")),
            online=online,
            location="" if online else place,
            tags=tuple(t["name"] for t in h.get("themes") or () if t.get("name") != "No Restrictions"),
        ))
    return items


async def fetch(session: aiohttp.ClientSession) -> list[Hackathon]:
    result: dict[str, Hackathon] = {}
    for flt in FILTERS:
        async with session.get(API_URL, params={"filter": flt, "page": "1"}) as resp:
            resp.raise_for_status()
            for h in parse(await resp.json()):
                result.setdefault(h.uid, h)
    return list(result.values())
