import html
import re

import aiohttp

from hackdigest.models import Hackathon

API_URL = "https://devpost.com/api/hackathons"
MAX_PAGES = 5  # по 9 штук на странице


def parse(data: dict) -> list[Hackathon]:
    items = []
    for h in data.get("hackathons", []):
        if h.get("invite_only"):
            continue
        prize = html.unescape(re.sub(r"<[^>]+>", "", h.get("prize_amount") or ""))
        if not re.search(r"[1-9]", prize):  # "$0", "₹ 0" и т.п.
            prize = ""
        items.append(
            Hackathon(
                uid=f"devpost:{h['id']}",
                source="devpost",
                title=h["title"].strip(),
                url=h["url"],
                dates=h.get("submission_period_dates", ""),
                location=(h.get("displayed_location") or {}).get("location", ""),
                prize=prize,
                tags=tuple(t["name"] for t in h.get("themes", [])),
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
        items = parse(data)
        result.extend(items)
        if not data.get("hackathons"):
            break
    return result
