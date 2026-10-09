import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from hackdigest import config as config_module
from hackdigest.digest import SOURCE_TITLES, build_digest, format_interval, parse_interval
from hackdigest.sources import SOURCES, fetch_all
from hackdigest.storage import Chat, Storage

log = logging.getLogger(__name__)
router = Router()
CHECK_EVERY = 60  # как часто планировщик проверяет, кому пора отправлять дайджест

HELP = (
    "Я присылаю дайджест ближайших хакатонов с Devpost и Codenrock.\n\n"
    "/digest — прислать дайджест сейчас\n"
    "/interval <code>3d</code> — как часто присылать (<code>12h</code>, <code>3d</code>, <code>1w</code>…)\n"
    "/sources — выбрать источники\n"
    "/settings — текущие настройки\n"
    "/stop — отписаться\n\n"
    "🆕 отмечены хакатоны, которых не было в прошлых дайджестах."
)


async def send_digest(bot: Bot, db: Storage, chat: Chat, per_source: int, manual: bool = False) -> None:
    by_source = await fetch_all(chat.sources)
    uids = [h.uid for items in by_source.values() for h in items]
    new = db.unseen(chat.chat_id, uids)
    messages = build_digest(by_source, new, per_source=per_source)
    if not messages:
        if manual:
            await bot.send_message(chat.chat_id, "Сейчас не нашлось предстоящих хакатонов 🤷")
        return
    for text in messages:
        await bot.send_message(chat.chat_id, text, disable_web_page_preview=True)
    db.mark_seen(chat.chat_id, uids)


def settings_text(chat: Chat) -> str:
    sources = ", ".join(SOURCE_TITLES.get(s, s) for s in chat.sources) or "не выбраны"
    status = "включена" if chat.active else "выключена (/start, чтобы включить)"
    return (
        f"Подписка: {status}\n"
        f"Интервал: раз в {format_interval(chat.interval_sec)}\n"
        f"Источники: {sources}"
    )


def sources_keyboard(chat: Chat) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"{'✅' if name in chat.sources else '⬜️'} {SOURCE_TITLES.get(name, name)}",
            callback_data=f"src:{name}",
        )]
        for name in SOURCES
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(CommandStart())
async def cmd_start(message: Message, db: Storage, cfg: config_module.Config) -> None:
    chat = db.subscribe(message.chat.id, cfg.default_interval, cfg.default_sources)
    await message.answer(
        f"Привет! Буду присылать дайджест раз в {format_interval(chat.interval_sec)}.\n\n{HELP}"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP)


@router.message(Command("stop"))
async def cmd_stop(message: Message, db: Storage) -> None:
    db.unsubscribe(message.chat.id)
    await message.answer("Отписал. Вернуться можно командой /start.")


async def _require_chat(message: Message, db: Storage) -> Chat | None:
    chat = db.get(message.chat.id)
    if chat is None:
        await message.answer("Сначала подпишитесь: /start")
    return chat


@router.message(Command("settings"))
async def cmd_settings(message: Message, db: Storage) -> None:
    if chat := await _require_chat(message, db):
        await message.answer(settings_text(chat))


@router.message(Command("digest"))
async def cmd_digest(message: Message, bot: Bot, db: Storage, cfg: config_module.Config) -> None:
    if chat := await _require_chat(message, db):
        await message.answer("Собираю хакатоны… ⏳")
        await send_digest(bot, db, chat, cfg.per_source, manual=True)


@router.message(Command("interval"))
async def cmd_interval(message: Message, command: CommandObject, db: Storage) -> None:
    chat = await _require_chat(message, db)
    if chat is None:
        return
    seconds = parse_interval(command.args or "")
    if seconds is None:
        await message.answer(
            f"Сейчас: раз в {format_interval(chat.interval_sec)}.\n"
            "Укажите интервал не меньше часа, например: <code>/interval 12h</code>, "
            "<code>/interval 3d</code>, <code>/interval 1w</code>"
        )
        return
    db.set_interval(chat.chat_id, seconds)
    await message.answer(f"Готово, следующий дайджест — через {format_interval(seconds)}.")


@router.message(Command("sources"))
async def cmd_sources(message: Message, db: Storage) -> None:
    if chat := await _require_chat(message, db):
        await message.answer("Откуда собирать хакатоны:", reply_markup=sources_keyboard(chat))


@router.callback_query(F.data.startswith("src:"))
async def toggle_source(query: CallbackQuery, db: Storage) -> None:
    name = query.data.removeprefix("src:")
    chat = db.get(query.message.chat.id)
    if chat is None or name not in SOURCES:
        await query.answer()
        return
    sources = [s for s in chat.sources if s != name] if name in chat.sources else [*chat.sources, name]
    if not sources:
        await query.answer("Нужен хотя бы один источник", show_alert=True)
        return
    db.set_sources(chat.chat_id, sources)
    chat.sources = sources
    await query.message.edit_reply_markup(reply_markup=sources_keyboard(chat))
    await query.answer()


async def scheduler(bot: Bot, db: Storage, cfg: config_module.Config) -> None:
    while True:
        for chat in db.due():
            # переносим следующий запуск заранее, чтобы ошибка отправки не приводила к спаму каждую минуту
            db.schedule_next(chat)
            try:
                await send_digest(bot, db, chat, cfg.per_source)
            except TelegramForbiddenError:
                log.info("Чат %s заблокировал бота — отписываю", chat.chat_id)
                db.unsubscribe(chat.chat_id)
            except Exception:
                log.exception("Не удалось отправить дайджест в чат %s", chat.chat_id)
        await asyncio.sleep(CHECK_EVERY)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = config_module.load()
    db = Storage(cfg.db_path)
    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    dp["db"] = db
    dp["cfg"] = cfg
    await bot.set_my_commands([
        BotCommand(command="digest", description="Дайджест сейчас"),
        BotCommand(command="interval", description="Как часто присылать"),
        BotCommand(command="sources", description="Выбрать источники"),
        BotCommand(command="settings", description="Текущие настройки"),
        BotCommand(command="stop", description="Отписаться"),
    ])
    task = asyncio.create_task(scheduler(bot, db, cfg))
    try:
        await dp.start_polling(bot)
    finally:
        task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
