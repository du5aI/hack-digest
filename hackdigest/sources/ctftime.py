"""CTFtime: календарь CTF-соревнований со всего мира, публичный JSON API."""
import re
import time
from datetime import datetime, timezone

import aiohttp

from hackdigest.models import Hackathon

API_URL = "https://ctftime.org/api/v1/events/"
LIST_URL = "https://ctftime.org/event/list/upcoming"
HORIZON = 60 * 86400  # на сколько вперёд смотрим
MIN_TEAMS = 20  # без рейтинга CTFtime берём только те, куда уже записалось заметное число команд
_RUSSIA = re.compile(r"russia|росси|moscow|москв|petersburg|петербург", re.IGNORECASE)


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def is_notable(e: dict) -> bool:
    """Отсекаем шум: квалифицированные финалы, CTF без рейтинга и почти без участников — кроме российских."""
    if (e.get("restrictions") or "") == "Prequalified":
        return False
    where = f"{e.get('title') or ''} {e.get('location') or ''}"
    return bool((e.get("weight") or 0) > 0 or (e.get("participants") or 0) >= MIN_TEAMS or _RUSSIA.search(where))


def parse(data: list, now: datetime | None = None) -> list[Hackathon]:
    now = now or datetime.now(timezone.utc)
    items = []
    for e in data or []:
        start, end = _dt(e.get("start")), _dt(e.get("finish"))
        if (end and end <= now) or not is_notable(e):
            continue
        online = not e.get("onsite")
        fmt = (e.get("format") or "").strip()
        items.append(Hackathon(
            uid=f"ctftime:{e['id']}",
            source="ctftime",
            title=(e.get("title") or "").strip(),
            url=e.get("ctftime_url") or f"https://ctftime.org/event/{e['id']}/",
            start=start,
            end=end,
            online=online,
            location="" if online else (e.get("location") or "").strip(),
            tags=("CTF", fmt) if fmt else ("CTF",),
            description=(e.get("description") or "").strip()[:2000],
            organizer=", ".join(o.get("name") or "" for o in e.get("organizers") or () if o.get("name")),
            participants=e.get("participants") or None,
        ))
    return items


async def fetch(session: aiohttp.ClientSession) -> list[Hackathon]:
    now = int(time.time())
    params = {"limit": "100", "start": str(now), "finish": str(now + HORIZON)}
    async with session.get(API_URL, params=params) as resp:
        resp.raise_for_status()
        return parse(await resp.json(content_type=None))
