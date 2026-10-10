import asyncio
import logging
import time

import aiohttp

from hackdigest.models import Hackathon
from hackdigest.sources import (changellenge, codenrock, ctftime, devfolio, devpost, dorahacks, hackathons_rus, lablab,
                                leader_id, mlh, taikai, telegram)

log = logging.getLogger(__name__)

# сайты-агрегаторы: имя -> async fetch(session) -> list[Hackathon]
SOURCES = {
    "hackathons_rus": hackathons_rus.fetch,
    "codenrock": codenrock.fetch,
    "leader_id": leader_id.fetch,
    "devpost": devpost.fetch,
    "mlh": mlh.fetch,
    "devfolio": devfolio.fetch,
    "changellenge": changellenge.fetch,
    "dorahacks": dorahacks.fetch,
    "taikai": taikai.fetch,
    "lablab": lablab.fetch,
    "ctftime": ctftime.fetch,
}

CACHE_TTL = 30 * 60
_cache: dict[str, tuple[float, list[Hackathon]]] = {}


async def _cached(key: str, loader) -> tuple[list[Hackathon], bool]:
    """(события, удалось ли обновить). При ошибке — устаревший кэш, если он есть: лучше, чем ничего."""
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_TTL:
        return cached[1], True
    try:
        items = await loader()
    except Exception:
        log.exception("Не удалось загрузить %s", key)
        return (cached[1] if cached else []), False
    _cache[key] = (time.monotonic(), items)
    return items, True


async def fetch_all(names: list[str], channels: list[str] = ()) -> tuple[list[Hackathon], list[str]]:
    """Все события из выбранных источников и список сайтов, которые сейчас не ответили."""
    timeout = aiohttp.ClientTimeout(total=30)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; hack-digest-bot/1.0)"}
    sites = [n for n in names if n in SOURCES]
    async with aiohttp.ClientSession(timeout=timeout, headers=headers, trust_env=True) as session:
        jobs = [_cached(n, lambda n=n: SOURCES[n](session)) for n in sites]
        if "telegram" in names:
            # каналы читаем не все разом, чтобы не упереться в ограничения t.me
            sem = asyncio.Semaphore(4)

            async def channel(c: str) -> list[Hackathon]:
                async with sem:
                    return await telegram.fetch_channel(session, c)

            jobs += [_cached(f"tg:{c}", lambda c=c: channel(c)) for c in channels]
        results = await asyncio.gather(*jobs)
    failed = [n for n, (_, ok) in zip(sites, results) if not ok]
    return [h for items, _ in results for h in items], failed
