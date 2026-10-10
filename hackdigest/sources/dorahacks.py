"""DoraHacks: публичный JSON API, в основном Web3- и AI-хакатоны."""
from datetime import datetime, timezone

import aiohttp

from hackdigest.models import Hackathon

API_URL = "https://dorahacks.io/api/v1/hub/hackathons"
LIST_URL = "https://dorahacks.io/hackathon"
# upcoming — ещё не начались; ongoing — идут, но присоединиться ещё можно
STATUSES = ("upcoming", "ongoing")
MAX_PAGES = 3  # по 50 штук
# API закрыт AWS WAF: с «ботовым» User-Agent отдаёт 405 и капчу, с браузерным — JSON
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/128.0 Safari/537.36", "Accept": "application/json"}
_CURRENCY = {"USD": "$", "USDT": "$", "USDC": "$", "EUR": "€"}


def _ts(value) -> datetime | None:
    return datetime.fromtimestamp(value, timezone.utc) if value else None


def prize(amount, token: str) -> str:
    if not amount:
        return ""
    sign = _CURRENCY.get((token or "").upper())
    return f"{sign}{amount:,.0f}" if sign else f"{amount:,.0f} {token or ''}".strip()


def parse(data: dict, now: datetime | None = None) -> list[Hackathon]:
    now = now or datetime.now(timezone.utc)
    items, seen = [], set()
    for h in data.get("results") or []:
        start, end = _ts(h.get("timeline_start")), _ts(h.get("timeline_end"))
        if end and end <= now:
            continue
        owner = ((h.get("owner") or {}).get("name") or "").strip()
        # одно событие часто заведено отдельно на каждом языке — склеиваем по организатору и датам
        key = (owner.lower(), end and end.date())
        if owner and key in seen:
            continue
        seen.add(key)
        online = h.get("venue_form") != "IRL"
        place = ", ".join(p.strip() for p in (h.get("venue_name"), h.get("venue_address")) if p and p.strip())
        tags = [t.strip() for t in (h.get("tags") or "").split(",") if t.strip()]
        items.append(Hackathon(
            uid=f"dorahacks:{h['id']}",
            source="dorahacks",
            title=(h.get("title") or "").strip(),
            url=f"{LIST_URL}/{h.get('uname') or h['id']}",
            start=start,
            end=end,
            # уже идущий хакатон: работы принимают до конца — присоединиться ещё можно
            reg_deadline=end if start and start <= now else None,
            online=online,
            location="" if online else place,
            prize=prize(h.get("bonus_price"), h.get("bonus_token") or ""),
            tags=tuple(tags),
            organizer=owner,
            participants=h.get("hackers_count") or None,
        ))
    return items


async def fetch(session: aiohttp.ClientSession) -> list[Hackathon]:
    result: dict[str, Hackathon] = {}
    for status in STATUSES:
        for page in range(1, MAX_PAGES + 1):
            params = {"page": str(page), "page_size": "50", "status": status}
            async with session.get(API_URL, params=params, headers=HEADERS) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
            for h in parse(data):
                result.setdefault(h.uid, h)
            if not data.get("next"):
                break
    return list(result.values())
