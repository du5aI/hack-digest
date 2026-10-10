import os
import re
from dataclasses import dataclass
from pathlib import Path

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
    webapp_url: str = ""  # адрес Mini App; если задан, дайджест — это табло и кнопка вместо текста


TOKEN_RE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$")


def read_dotenv(path: str | Path = ".env") -> dict[str, str]:
    """KEY=VALUE из файла; пустые строки и строки с # пропускаются, кавычки вокруг значения снимаются."""
    values = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip().removeprefix("export ").strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if re.fullmatch(r"[A-Z_][A-Z0-9_]*", key):
            values[key] = value
    return values


def load_dotenv(path: str | Path = ".env") -> None:
    """Значения из .env важнее переменных, оставшихся в терминале от прошлых запусков."""
    os.environ.update(read_dotenv(path))


def mask(token: str) -> str:
    return f"{token[:6]}…{token[-2:]}" if len(token) > 10 else "…"


def _list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    return default if raw is None else [s.strip() for s in raw.split(",") if s.strip()]


def load() -> Config:
    load_dotenv()
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Нет BOT_TOKEN. Запустите мастер настройки: python3 -m hackdigest.setup")
    if not TOKEN_RE.match(token):
        raise SystemExit(f"BOT_TOKEN выглядит неправильно ({mask(token)}, длина {len(token)}): токен от @BotFather "
                         "похож на 123456789:AAH… и длиной около 46 символов. "
                         "Запустите мастер настройки: python3 -m hackdigest.setup")
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
        limit=int(os.environ.get("SECTION_LIMIT", "6")),
        webapp_url=_webapp_url(),
    )


def _webapp_url() -> str:
    url = os.environ.get("WEBAPP_URL", "").strip()
    if url and not url.startswith("https://"):
        raise SystemExit("WEBAPP_URL должен начинаться с https:// — Telegram открывает Mini App только по HTTPS")
    return url
