"""Снимок событий для Mini App: python -m hackdigest.export webapp/data.json

Тот же конвейер, что у бота (сбор → отбор → тематика), но на выходе JSON, а не сообщения.
Фильтры пользователя применяются уже в самом Mini App, поэтому здесь берётся «весь мир».
"""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from hackdigest.digest import SOURCE_NAMES, brief, select
from hackdigest.filters import RU_SOURCES, Filters
from hackdigest.models import Hackathon
from hackdigest.render.ticket import ticket_code
from hackdigest.sources import SOURCES, fetch_all
from hackdigest.sources.telegram import DEFAULT_CHANNELS
from hackdigest.storage import event_id
from hackdigest.text import strip_emoji
from hackdigest.topics import TOPICS, topics_of


def _iso(d: datetime | None) -> str | None:
    return d.astimezone(timezone.utc).isoformat(timespec="minutes") if d else None


def event_json(h: Hackathon) -> dict:
    return {
        "id": event_id(h),
        "code": ticket_code(h),
        "title": strip_emoji(h.title),
        "url": h.url,
        "start": _iso(h.start),
        "end": _iso(h.end),
        "deadline": _iso(h.reg_deadline),
        "online": h.online,
        "place": h.location,
        "prize": h.prize,
        "source": SOURCE_NAMES.get(h.source, h.source),
        "ru": h.source in RU_SOURCES,
        "topics": list(topics_of(h)),
        "about": brief(h, limit=220) if h.source != "telegram" else h.summary,
    }


def snapshot(items: list[Hackathon], now: datetime, failed: list[str]) -> dict:
    return {
        "generated": _iso(now),
        "topics": {k: {"label": t.label, "group": t.group} for k, t in TOPICS.items()},
        "failed": [SOURCE_NAMES.get(s, s) for s in failed],
        "events": [event_json(h) for h in items],
    }


async def build(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    raw, failed = await fetch_all([*SOURCES, "telegram"], DEFAULT_CHANNELS)
    return snapshot(select(raw, Filters(region="world"), now), now, failed)


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "webapp/data.json")
    data = asyncio.run(build())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    print(f"{out}: {len(data['events'])} событий, не ответили: {', '.join(data['failed']) or 'нет'}")


if __name__ == "__main__":
    main()
