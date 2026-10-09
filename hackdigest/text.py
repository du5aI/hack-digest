import re

_EMOJI = re.compile("[\U0001F000-\U0001FAFF←-⇿⌀-⏿①-➿⤀-⯿"
                    "️‍⃣]+")


def strip_emoji(text: str) -> str:
    return re.sub(r"\s{2,}", " ", _EMOJI.sub(" ", text)).strip()
