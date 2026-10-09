import html
import re
from datetime import datetime, timezone

import aiohttp

from hackdigest.models import Hackathon

API_URL = "https://devpost.com/api/hackathons"
LIST_URL = "https://devpost.com/hackathons"
MAX_PAGES = 5  # по 9 штук на странице

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}
_PART = re.compile(r"(?:(?P<mon>[A-Za-z]{3})\w*\s+)?(?P<day>\d{1,2})(?:,\s*(?P<year>\d{4}))?")


def parse_dates(text: str) -> tuple[datetime | None, datetime | None]:
    """'Oct 09 - 12, 2026', 'Oct 30 - Nov 02, 2026', 'Dec 28, 2026 - Jan 02, 2027', 'Oct 10, 2026'."""
    pieces = [p.strip() for p in text.split(" - ")]
    parsed = [_PART.fullmatch(p) for p in pieces]
    if not pieces or len(pieces) > 2 or not all(parsed):
        return None, None
    end_m = parsed[-1]
    start_m = parsed[0]
    year_end = end_m["year"] or start_m["year"]
    mon_end = end_m["mon"] or start_m["mon"]
    if not year_end or not start_m["mon"]:
        return None, None
    try:
        end = datetime(int(year_end), _MONTHS[mon_end.lower()], int(end_m["day"]), tzinfo=timezone.utc)
        start_year = int(start_m["year"] or year_end)
        start = datetime(start_year, _MONTHS[start_m["mon"].lower()], int(start_m["day"]), tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return None, None
    if start > end:  # 'Dec 28 - Jan 02, 2027' без года у начала
        start = start.replace(year=start.year - 1)
    return start, end.replace(hour=23, minute=59)


def parse(data: dict) -> list[Hackathon]:
    items = []
    for h in data.get("hackathons", []):
        if h.get("invite_only"):
            continue
        prize = html.unescape(re.sub(r"<[^>]+>", "", h.get("prize_amount") or "")).strip()
        if not re.search(r"[1-9]", prize):  # "$0", "₹ 0" и т.п.
            prize = ""
        location = h.get("displayed_location") or {}
        online = location.get("icon") == "globe" or location.get("location", "").lower() == "online"
        dates = h.get("submission_period_dates", "")
        start, end = parse_dates(dates)
        items.append(
            Hackathon(
                uid=f"devpost:{h['id']}",
                source="devpost",
                title=h["title"].strip(),
                url=h["url"],
                start=start,
                end=end,
                online=online,
                location="" if online else location.get("location", ""),
                prize=prize,
                tags=tuple(t["name"] for t in h.get("themes", [])),
                dates_text="" if start else dates,
            )
        )
    return items


async def fetch(session: aiohttp.ClientSession) -> list[Hackathon]:
    result: list[Hackathon] = []
    for page in range(1, MAX_PAGES + 1):
        params = [("status[]", "upcoming"), ("order_by", "deadline"), ("page", str(page))]
        async with session.get(API_URL, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()
        result.extend(parse(data))
        if not data.get("hackathons"):
            break
    return result
