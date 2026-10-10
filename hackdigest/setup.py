"""Мастер настройки: python3 -m hackdigest.setup

Спрашивает токен бота, сразу проверяет его в Telegram и записывает .env —
без ручного редактирования файла и команд оболочки.
"""
import asyncio
import getpass
import re
import subprocess
from pathlib import Path

import aiohttp

from hackdigest.config import TOKEN_RE, mask, read_dotenv

ENV = Path(".env")


def pages_url() -> str:
    """Адрес GitHub Pages по адресу репозитория: github.com/Owner/repo → https://owner.github.io/repo/."""
    try:
        remote = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""
    m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", remote)
    return f"https://{m[1].lower()}.github.io/{m[2]}/" if m else ""


async def check_token(token: str) -> str:
    """Имя бота, если Telegram принял токен; иначе SystemExit с понятной причиной."""
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15), trust_env=True) as s:
            async with s.get(url) as r:
                data = await r.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError):
        raise SystemExit("Нет связи с api.telegram.org. Похоже, Telegram заблокирован — включите VPN и повторите.")
    if not data.get("ok"):
        raise SystemExit(f"Telegram не принял токен {mask(token)}: {data.get('description', 'неизвестная ошибка')}.\n"
                         "Откройте @BotFather → /mybots → ваш бот → API Token и скопируйте токен целиком.")
    return data["result"]["username"]


def write_env(values: dict[str, str]) -> None:
    ENV.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    try:
        ENV.chmod(0o600)  # токен — пароль от бота: читать файл может только владелец
    except OSError:
        pass


def main() -> None:
    print("Настройка бота Hack Digest.\n")
    token = getpass.getpass("Вставьте токен от @BotFather (символы не отображаются) и нажмите Enter: ").strip()
    token = token.strip("'\"<> ")
    if not TOKEN_RE.match(token):
        raise SystemExit(f"Это не похоже на токен ({mask(token)}, длина {len(token)}). "
                         "Он выглядит как 123456789:AAH… и длиной около 46 символов.")
    username = asyncio.run(check_token(token))
    print(f"Токен подходит: бот @{username}")

    values = read_dotenv(ENV)
    default_url = values.get("WEBAPP_URL") or pages_url()
    answer = input(f"Адрес Mini App [{default_url or 'пусто — без приложения'}]: ").strip()
    url = answer or default_url
    if url and not url.startswith("https://"):
        raise SystemExit("Адрес Mini App должен начинаться с https://")

    values.update({"BOT_TOKEN": token, "WEBAPP_URL": url})
    values.setdefault("DB_PATH", "hackdigest.db")
    if values["DB_PATH"].startswith("/data/") and not Path("/data").exists():
        values["DB_PATH"] = "hackdigest.db"  # /data — путь внутри Docker
    if not url:
        values.pop("WEBAPP_URL")
    write_env(values)
    print(f"\nГотово, настройки записаны в {ENV.resolve()}.\nЗапуск бота: python3 -m hackdigest.bot")


if __name__ == "__main__":
    main()
