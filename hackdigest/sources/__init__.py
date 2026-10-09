import asyncio
import logging
import time

import aiohttp

from hackdigest.models import Hackathon
from hackdigest.sources import codenrock, devfolio, devpost, hackathons_rus, leader_id, mlh, telegram

log = logging.getLogger(__name__)

# сайты-агрегаторы: имя -> async fetch(session) -> list[Hackathon]
SOURCES = {
    "hackathons_rus": hackathons_rus.fetch,
    "codenrock": codenrock.fetch,
    "leader_id": leader_id.fetch,
    "devpost": devpost.fetch,
    "mlh": mlh.fetch,
    "devfolio": devfolio.fetch,
}

CACHE_TTL = 30 * 60
_cache: dict[str, tuple[float, list[Hackathon]]] = {}


async def _cached(key: str, loader) -> list[Hackathon]:
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_TTL:
        return cached[1]
    try:
        items = await loader()
    except Exception:
        log.exception("Не удалось загрузить %s", key)
        # отдаём устаревший кэш, если он есть: лучше, чем ничего
        return cached[1] if cached else []
    _cache[key] = (time.monotonic(), items)
    return items


async def fetch_all(names: list[str], channels: list[str] = ()) -> list[Hackathon]:
    timeout = aiohttp.ClientTimeout(total=30)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; hack-digest-bot/1.0)"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers, trust_env=True) as session:
        jobs = [_cached(n, lambda n=n: SOURCES[n](session)) for n in names if n in SOURCES]
        if "telegram" in names:
            # каналы читаем не все разом, чтобы не упереться в ограничения t.me
            sem = asyncio.Semaphore(4)

            async def channel(c: str) -> list[Hackathon]:
                async with sem:
                    return await telegram.fetch_channel(session, c)

            jobs += [_cached(f"tg:{c}", lambda c=c: channel(c)) for c in channels]
        results = await asyncio.gather(*jobs)
    return [h for items in results for h in items]
