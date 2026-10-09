import asyncio
import logging
import time

import aiohttp

from hackdigest.models import Hackathon
from hackdigest.sources import codenrock, devpost

log = logging.getLogger(__name__)

SOURCES = {
    "devpost": devpost.fetch,
    "codenrock": codenrock.fetch,
}

CACHE_TTL = 30 * 60
_cache: dict[str, tuple[float, list[Hackathon]]] = {}


async def fetch_source(session: aiohttp.ClientSession, name: str) -> list[Hackathon]:
    cached = _cache.get(name)
    if cached and time.monotonic() - cached[0] < CACHE_TTL:
        return cached[1]
    try:
        items = await SOURCES[name](session)
    except Exception:
        log.exception("Не удалось загрузить источник %s", name)
        # отдаём устаревший кэш, если он есть, лучше чем ничего
        return cached[1] if cached else []
    _cache[name] = (time.monotonic(), items)
    return items


async def fetch_all(names: list[str]) -> dict[str, list[Hackathon]]:
    timeout = aiohttp.ClientTimeout(total=30)
    headers = {"User-Agent": "hack-digest-bot/1.0"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers, trust_env=True) as session:
        results = await asyncio.gather(*(fetch_source(session, n) for n in names))
    return dict(zip(names, results))
