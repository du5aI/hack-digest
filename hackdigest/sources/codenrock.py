from datetime import datetime, timezone

import aiohttp

from hackdigest.models import Hackathon

API_URL = "https://codenrock.com/api/contests"
MAX_PAGES = 4
# стажировки, акселераторы и олимпиады пропускаем — нужны только соревнования-хакатоны
TYPES = {"hackathon": "", "ctf": "CTF", "ml_ai": "ML/AI"}


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _fmt(d: datetime) -> str:
    return d.strftime("%d.%m.%Y")


def parse(data: dict, now: datetime | None = None) -> list[Hackathon]:
    """Возвращает предстоящие соревнования: ещё не начались или открыта регистрация."""
    now = now or datetime.now(timezone.utc)
    items = []
    for c in data.get("contests", []):
        if c.get("status") != "active" or c.get("type") not in TYPES:
            continue
        start, end, reg_end = _dt(c.get("startDate")), _dt(c.get("endDate")), _dt(c.get("endRegistration"))
        registration_open = reg_end is not None and reg_end > now
        if not registration_open and (start is None or start <= now):
            continue
        dates = f"{_fmt(start)} – {_fmt(end)}" if start and end else ""
        if registration_open:
            dates += f" (рег. до {_fmt(reg_end)})"
        tag = TYPES[c["type"]]
        items.append(
            Hackathon(
                uid=f"codenrock:{c['id']}",
                source="codenrock",
                title=c["name"].strip(),
                url=f"https://codenrock.com/contests/{c['slug']}",
                dates=dates.strip(),
                prize=(c.get("prizes") or "").strip(),
                tags=(tag,) if tag else (),
                starts_at=start,
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
    return sorted(result.values(), key=lambda h: h.starts_at or far_future)
