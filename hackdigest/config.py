import os
from dataclasses import dataclass

from hackdigest.digest import parse_interval
from hackdigest.sources import SOURCES
from hackdigest.sources.telegram import DEFAULT_CHANNELS, normalize_channel

ALL_SOURCES = [*SOURCES, "telegram"]


@dataclass(frozen=True)
class Config:
    bot_token: str
    db_path: str
    default_interval: int
    default_sources: list[str]
    default_channels: list[str]
    limit: int


def _list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    return default if raw is None else [s.strip() for s in raw.split(",") if s.strip()]


def load() -> Config:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("Не задана переменная окружения BOT_TOKEN (токен от @BotFather)")
    interval = parse_interval(os.environ.get("DEFAULT_INTERVAL", "7d"))
    if interval is None:
        raise SystemExit("DEFAULT_INTERVAL должен выглядеть как 12h, 3d или 1w (не меньше часа)")
    sources = _list("DEFAULT_SOURCES", ALL_SOURCES)
    unknown = set(sources) - set(ALL_SOURCES)
    if unknown:
        raise SystemExit(f"Неизвестные источники в DEFAULT_SOURCES: {', '.join(sorted(unknown))}")
    channels = [normalize_channel(c) for c in _list("DEFAULT_CHANNELS", DEFAULT_CHANNELS)]
    if None in channels:
        raise SystemExit("DEFAULT_CHANNELS: ожидаются username каналов через запятую")
    return Config(
        bot_token=token,
        db_path=os.environ.get("DB_PATH", "hackdigest.db"),
        default_interval=interval,
        default_sources=sources,
        default_channels=channels,
        limit=int(os.environ.get("SECTION_LIMIT", "10")),
    )
