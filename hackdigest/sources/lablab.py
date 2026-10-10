"""lablab.ai: онлайн AI-хакатоны; список событий зашит в поток Next.js на странице."""
import json
import re
from datetime import datetime, timezone

import aiohttp

from hackdigest.models import Hackathon

LIST_URL = "https://lablab.ai/ai-hackathons"
_PUSH = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
_MARK = '{"sortedEvents":'


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def events(page_html: str) -> list[dict]:
    """Склеиваем куски потока self.__next_f.push([1, "..."]) и достаём JSON со списком событий."""
    stream = "".join(json.loads(s) for s in _PUSH.findall(page_html))
    pos = stream.find(_MARK)
    if pos < 0:
        raise ValueError("lablab: не найден список событий")
    data, _ = json.JSONDecoder().raw_decode(stream, pos)
    return data.get("sortedEvents") or []


def parse(page_html: str, now: datetime | None = None) -> list[Hackathon]:
    now = now or datetime.now(timezone.utc)
    items = []
    for e in events(page_html):
        start, end = _dt(e.get("startAt")), _dt(e.get("endAt"))
        if e.get("type") != "HACKATHON" or not e.get("slug") or not end or end <= now:
            continue
        # HYBRID у lablab — онлайн-сборка проекта и необязательный очный финал
        online = e.get("eventType") in ("ONLINE", "HYBRID")
        started = start is not None and start <= now
        if started and not e.get("signupActive"):
            continue
        techs = [t.get("techName") or "" for t in e.get("technologyList") or () if isinstance(t, dict)]
        items.append(Hackathon(
            uid=f"lablab:{e.get('id') or e['slug']}",
            source="lablab",
            title=(e.get("name") or "").strip(),
            url=f"{LIST_URL}/{e['slug']}",
            start=start,
            end=end,
            # уже идёт, но запись открыта — присоединиться можно до конца
            reg_deadline=end if started else None,
            online=online,
            tags=("AI", *[t for t in techs if t][:5]),
            description=(e.get("description") or "").strip()[:2000],
            participants=(e.get("_count") or {}).get("participants") or None,
        ))
    return items


async def fetch(session: aiohttp.ClientSession) -> list[Hackathon]:
    async with session.get(LIST_URL) as resp:
        resp.raise_for_status()
        return parse(await resp.text())
