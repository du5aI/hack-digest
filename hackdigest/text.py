import re

_EMOJI = re.compile("[\U0001F000-\U0001FAFF←-⇿⌀-⏿①-➿⤀-⯿"
                    "️‍⃣]+")


def strip_emoji(text: str) -> str:
    return re.sub(r"\s{2,}", " ", _EMOJI.sub(" ", text)).strip()


_ONLINE = re.compile(r"онлайн[- ]?(?:хакатон|формат|соревнован|чемпионат)|в онлайн-формате|формат\W{0,3}онлайн|online hackathon"
                     r"|дистанционн", re.IGNORECASE)
_OFFLINE = re.compile(r"офлайн[- ]?(?:хакатон|формат|соревнован|чемпионат)|оффлайн|в офлайн-формате|формат\W{0,3}оч|очн\w+ (?:формат|этап|финал)"
                      r"|гибридн", re.IGNORECASE)


def guess_online(text: str) -> bool | None:
    """Формат по описанию: True — онлайн, False — очно (в т.ч. гибрид и очный финал), None — непонятно."""
    online, offline = bool(_ONLINE.search(text)), bool(_OFFLINE.search(text))
    if offline:
        return False
    return True if online else None
