"""Leader-ID — платформа мероприятий (АСИ, «Точки кипения»): события с типом «Хакатон»."""
import re
from datetime import datetime, timedelta, timezone

import aiohttp

from hackdigest.models import Hackathon

API_URL = "https://leader-id.ru/api/v4/events/search"
LIST_URL = "https://leader-id.ru/events"
HACKATHON_TYPE = "88"
# тип «Хакатон» ставят и питч-сессиям, и лекциям о хакатонах — требуем слово в названии
_TITLE = re.compile(r"хакат|hack|джем|jam|ctf|дататон", re.IGNORECASE)
_NOT_EVENT = re.compile(r"с чего начать|как (?:выиграть|подготов|участв)|лекци|встреча|мастер-класс|питч|вебинар",
                        re.IGNORECASE)


def _tz(value: str | None) -> timezone:
    m = re.fullmatch(r"([+-])(\d{2}):(\d{2})", value or "")
    if not m:
        return timezone(timedelta(hours=3))
    sign = 1 if m[1] == "+" else -1
    return timezone(sign * timedelta(hours=int(m[2]), minutes=int(m[3])))


def _dt(value: str | None, tz: timezone) -> datetime | None:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz) if value else None


def parse(data: dict) -> list[Hackathon]:
    items = []
    for e in (data.get("data") or {}).get("_items", []):
        title = (e.get("full_name") or "").strip()
        if e.get("finished") or not _TITLE.search(title) or _NOT_EVENT.search(title):
            continue
        tz = _tz((e.get("timezone") or {}).get("value"))
        online = e.get("format") == "online"
        items.append(Hackathon(
            uid=f"leader_id:{e['id']}",
            source="leader_id",
            title=title,
            url=f"https://leader-id.ru/events/{e['id']}",
            start=_dt(e.get("date_start"), tz),
            end=_dt(e.get("date_end"), tz),
            reg_deadline=_dt(e.get("registration_date_end"), tz),
            online=online,
            location="" if online else (e.get("city") or ""),
            tags=tuple(t["name"] for t in e.get("themes") or () if t.get("name")),
        ))
    return items


async def fetch(session: aiohttp.ClientSession) -> list[Hackathon]:
    result: list[Hackathon] = []
    for page in range(1, 6):
        params = [("typeIds[]", HACKATHON_TYPE), ("actual", "1"), ("paginationSize", "50"),
                  ("paginationPage", str(page)), ("expand", "themes,type")]
        async with session.get(API_URL, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()
        result.extend(parse(data))
        meta = (data.get("data") or {}).get("_meta") or {}
        if page >= meta.get("pageCount", 1):
            break
    return result
