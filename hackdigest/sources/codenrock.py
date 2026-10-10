from datetime import datetime, timedelta, timezone

import aiohttp

from hackdigest.dates import MSK
from hackdigest.models import Hackathon
from hackdigest.text import guess_online

API_URL = "https://codenrock.com/api/contests"
LIST_URL = "https://codenrock.com/contests"
MAX_PAGES = 4
# стажировки, акселераторы и олимпиады пропускаем — нужны только соревнования-хакатоны
TYPES = {"hackathon": "", "ctf": "CTF", "ml_ai": "ML/AI"}


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _day(value: str | None) -> datetime | None:
    """Дата проведения. Организаторы с востока ставят полночь своего часового пояса — по Москве это
    поздний вечер предыдущего дня («4 окт 22:00» вместо «5 окт»), поэтому такие времена округляем вперёд."""
    d = _dt(value)
    if d is None:
        return None
    d = d.astimezone(MSK)
    return (d + timedelta(days=1)).replace(hour=0, minute=0, second=0) if d.hour >= 20 else d


def parse(data: dict, now: datetime | None = None) -> list[Hackathon]:
    """Возвращает предстоящие соревнования: ещё не начались или открыта регистрация."""
    now = now or datetime.now(timezone.utc)
    items = []
    for c in data.get("contests", []):
        if c.get("status") != "active" or c.get("type") not in TYPES:
            continue
        start, end, reg_end = _day(c.get("startDate")), _day(c.get("endDate")), _dt(c.get("endRegistration"))
        registration_open = reg_end is not None and reg_end > now
        if not registration_open and (start is None or start <= now):
            continue
        tag = TYPES[c["type"]]
        items.append(
            Hackathon(
                uid=f"codenrock:{c['id']}",
                source="codenrock",
                title=c["name"].strip(),
                url=f"https://codenrock.com/contests/{c['slug']}",
                start=start,
                end=end,
                reg_deadline=reg_end if registration_open else None,
                online=guess_online(c.get("description") or ""),
                prize=(c.get("prizes") or "").strip(),
                description=(c.get("description") or "").strip(),
                tags=(tag,) if tag else (),
            )
        )
    return items


async def fetch(session: aiohttp.ClientSession) -> list[Hackathon]:
    result: dict[str, Hackathon] = {}
    for page in range(1, MAX_PAGES + 1):
        async with session.get(API_URL, params={"page": str(page)}) as resp:
            resp.raise_for_status()
            data = await resp.json()
        for h in parse(data):
            result.setdefault(h.uid, h)
        contests = data.get("contests", [])
        total_pages = (data.get("pagination") or {}).get("totalPages", 1)
        # активные идут в начале списка; страница без активных — дальше только архив
        if page >= total_pages or not any(c.get("status") == "active" for c in contests):
            break
    far_future = datetime.max.replace(tzinfo=timezone.utc)
    return sorted(result.values(), key=lambda h: h.start or far_future)
