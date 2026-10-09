# hack-digest

Telegram-бот, который раз в N часов/дней/недель присылает дайджест ближайших хакатонов.

**Источники**
- 🌍 [Devpost](https://devpost.com/hackathons): международные хакатоны (онлайн и офлайн)
- 🇷🇺 [Codenrock](https://codenrock.com/contests): российские хакатоны, CTF и ML-соревнования

Хакатоны, которых не было в прошлых дайджестах чата, помечаются 🆕.

## Команды

| Команда | Что делает |
|---|---|
| `/start` | подписаться (или снова включить подписку) |
| `/digest` | прислать дайджест прямо сейчас |
| `/interval 3d` | как часто присылать: `12h`, `3d`, `1w`, `2 дня`… (не меньше часа) |
| `/sources` | включить или выключить источники кнопками |
| `/settings` | текущие настройки |
| `/stop` | отписаться |

Бот работает и в личке, и в группах: настройки хранятся отдельно для каждого чата.

## Запуск

1. Создайте бота у [@BotFather](https://t.me/BotFather) и получите токен.
2. `cp .env.example .env` и впишите `BOT_TOKEN`.

**Через Docker:**
```bash
docker compose up -d --build
```

**Локально (Python 3.11+):**
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export $(grep -v '^#' .env | xargs) DB_PATH=hackdigest.db
python -m hackdigest.bot
```

## Настройки (переменные окружения)

| Переменная | По умолчанию | Описание |
|---|---|---|
| `BOT_TOKEN` | — | токен бота (обязательно) |
| `DEFAULT_INTERVAL` | `7d` | интервал для новых подписчиков |
| `DEFAULT_SOURCES` | `devpost,codenrock` | источники для новых подписчиков |
| `PER_SOURCE` | `10` | сколько хакатонов показывать из каждого источника |
| `DB_PATH` | `hackdigest.db` | путь к SQLite-базе |

## Как устроено

- `hackdigest/sources/`: загрузчики, по одному на сайт. Ответы кэшируются на 30 минут. Новый источник добавляется так: файл с функцией `async fetch(session) -> list[Hackathon]` и запись в `SOURCES`.
- `hackdigest/storage.py`: SQLite с подписками (интервал, время следующей отправки, источники) и списком уже показанных хакатонов.
- `hackdigest/bot.py`: команды на aiogram 3 и планировщик. Раз в минуту он находит чаты, которым пора отправить дайджест.
- `hackdigest/digest.py`: форматирование. Длинный дайджест режется на сообщения по 4096 символов.

## Тесты

```bash
pip install -r requirements-dev.txt
pytest
```
