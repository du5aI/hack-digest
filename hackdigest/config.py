import os
from dataclasses import dataclass

from hackdigest.digest import parse_interval
from hackdigest.sources import SOURCES


@dataclass(frozen=True)
class Config:
    bot_token: str
    db_path: str
    default_interval: int
    default_sources: list[str]
    per_source: int


def load() -> Config:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("Не задана переменная окружения BOT_TOKEN (токен от @BotFather)")
    interval = parse_interval(os.environ.get("DEFAULT_INTERVAL", "7d"))
    if interval is None:
        raise SystemExit("DEFAULT_INTERVAL должен выглядеть как 12h, 3d или 1w (не меньше часа)")
    sources = [s.strip() for s in os.environ.get("DEFAULT_SOURCES", ",".join(SOURCES)).split(",") if s.strip()]
    unknown = set(sources) - set(SOURCES)
    if unknown:
        raise SystemExit(f"Неизвестные источники в DEFAULT_SOURCES: {', '.join(sorted(unknown))}")
    return Config(
        bot_token=token,
        db_path=os.environ.get("DB_PATH", "hackdigest.db"),
        default_interval=interval,
        default_sources=sources,
        per_source=int(os.environ.get("PER_SOURCE", "10")),
    )
