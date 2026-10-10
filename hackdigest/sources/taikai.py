"""TAIKAI: европейская платформа онлайн-хакатонов, публичный GraphQL API."""
import re
from datetime import datetime, timezone

import aiohttp

from hackdigest.models import Hackathon

API_URL = "https://api.taikai.network/api/graphql"
LIST_URL = "https://taikai.network/hackathons"
MAX_PAGES = 2  # по 20 штук, свежие сначала
QUERY = """query Q($page: Int) { challenges(where: {publishInfo: {state: {equals: ACTIVE}}}, page: $page,
 orderBy: {createdAt: desc}) { id name slug isClosed prize prizeCurrency { name } shortDescription
 organization { slug name } steps { name startDate } participantsCount industries { title } } }"""
_CURRENCY = {"USD": "$", "EUR": "€", "GBP": "£"}
# у этапов есть только дата начала; этап «Registration» — это открытие регистрации, а не дедлайн
_REG = re.compile(r"regist|inscri", re.IGNORECASE)
_REG_END = re.compile(r"deadline|clos|last call|end|fim|encerr", re.IGNORECASE)
# площадки в API нет; TAIKAI — платформа онлайн-хакатонов, очный формат видно только по описанию
_OFFLINE = re.compile(r"in[- ]person|on[- ]?site|presencial|hybrid|híbrid|venue", re.IGNORECASE)


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def parse(data: dict, now: datetime | None = None) -> list[Hackathon]:
    """Предстоящие: не закрыты и последний этап ещё впереди."""
    now = now or datetime.now(timezone.utc)
    items = []
    for c in ((data.get("data") or {}).get("challenges")) or []:
        steps = [(s.get("name") or "", d) for s in c.get("steps") or () if (d := _dt(s.get("startDate")))]
        if c.get("isClosed") or not steps or max(d for _, d in steps) <= now:
            continue
        work = [d for name, d in steps if not _REG.search(name)]
        start = min(work) if work else None
        end = max(work) if work else None
        deadline = max((d for name, d in steps if _REG.search(name) and _REG_END.search(name)), default=None)
        # без явного дедлайна регистрация открыта до старта
        deadline = deadline or (start if any(_REG.search(name) for name, _ in steps) else None)
        if start and start <= now and not (deadline and deadline > now):
            continue  # уже идёт, присоединиться нельзя
        org = c.get("organization") or {}
        amount, currency = c.get("prize") or 0, (c.get("prizeCurrency") or {}).get("name") or ""
        sign = _CURRENCY.get(currency.upper())
        prize = "" if not amount else f"{sign}{amount:,.0f}" if sign else f"{amount:,.0f} {currency}".strip()
        about = (c.get("shortDescription") or "").strip()
        items.append(Hackathon(
            uid=f"taikai:{c['id']}",
            source="taikai",
            title=(c.get("name") or "").strip(),
            url=f"https://taikai.network/{org.get('slug') or ''}/hackathons/{c.get('slug') or ''}",
            start=start,
            end=end,
            reg_deadline=deadline if deadline and deadline > now else None,
            online=not _OFFLINE.search(about),
            prize=prize,
            tags=tuple(i["title"] for i in c.get("industries") or () if i.get("title")),
            description=about,
            organizer=(org.get("name") or "").strip(),
            participants=c.get("participantsCount") or None,
        ))
    return items


async def fetch(session: aiohttp.ClientSession) -> list[Hackathon]:
    result: dict[str, Hackathon] = {}
    for page in range(MAX_PAGES):
        payload = {"query": QUERY, "variables": {"page": page}}
        async with session.post(API_URL, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
        if data.get("errors"):
            raise RuntimeError(f"TAIKAI: {data['errors'][0].get('message')}")
        for h in parse(data):
            result.setdefault(h.uid, h)
        if not (data.get("data") or {}).get("challenges"):
            break
    return list(result.values())
