import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (BotCommand, BufferedInputFile, CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, LinkPreviewOptions, Message)

from hackdigest import config as config_module
from hackdigest.digest import SOURCE_NAMES, build_digest, format_interval, parse_interval, select
from hackdigest.filters import FORMATS, PERIODS, REGIONS
from hackdigest.topics import GROUPS, TOPICS
from hackdigest.sources import SOURCES, fetch_all
from hackdigest.sources.telegram import normalize_channel
from hackdigest.storage import Chat, Storage
from hackdigest.timeline import render_timeline

log = logging.getLogger(__name__)
router = Router()
CHECK_EVERY = 60  # как часто планировщик проверяет, кому пора отправлять дайджест
MAX_CHANNELS = 40
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

HELP = (
    "Бот присылает дайджест ближайших хакатонов: Devpost, Codenrock и другие сайты, "
    "а также анонсы из Telegram-каналов вузов и компаний.\n\n"
    "/digest — дайджест прямо сейчас\n"
    "/timeline — только картинка-таймлайн\n"
    "/filter — фильтр по формату, темам и датам\n"
    "/sources — какие сайты учитывать\n"
    "/channels — Telegram-каналы, которые читает бот\n"
    "/interval <code>3d</code> — как часто присылать (<code>12h</code>, <code>3d</code>, <code>1w</code>)\n"
    "/settings — текущие настройки\n"
    "/stop — отписаться"
)


# ---------- сборка и отправка ----------


async def collect(chat: Chat, db: Storage):
    now = datetime.now(timezone.utc)
    raw = await fetch_all(chat.sources, chat.channels)
    items = select(raw, chat.filters, now)
    uids = [h.uid for h in items]
    new = db.unseen(chat.chat_id, uids)
    if len(new) == len(uids):  # первый дайджест: «новым» было бы всё, пометки ничего не дают
        new = set()
    return now, items, new


async def send_digest(bot: Bot, db: Storage, chat: Chat, limit: int, manual: bool = False,
                      with_text: bool = True) -> None:
    now, items, new = await collect(chat, db)
    if not items:
        if manual:
            await bot.send_message(chat.chat_id, "Под текущий фильтр ничего не нашлось. Ослабить его можно в /filter.")
        return
    png = await asyncio.to_thread(render_timeline, items, new, now)
    if png:
        await bot.send_photo(chat.chat_id, BufferedInputFile(png, "timeline.png"))
    if with_text:
        for text in build_digest(items, new, now, chat.sources, chat.filters, limit=limit):
            await bot.send_message(chat.chat_id, text, link_preview_options=NO_PREVIEW)
        db.mark_seen(chat.chat_id, [h.uid for h in items])
    elif not png and manual:
        await bot.send_message(chat.chat_id, "В ближайшие недели нет событий с точными датами.")


def settings_text(chat: Chat) -> str:
    sources = ", ".join(SOURCE_NAMES.get(s, s) for s in chat.sources) or "не выбраны"
    status = "включена" if chat.active else "выключена, включить: /start"
    return (
        f"Подписка: {status}\n"
        f"Интервал: раз в {format_interval(chat.interval_sec)}\n"
        f"Источники: {sources}\n"
        f"Каналов: {len(chat.channels)} (/channels)\n"
        f"Фильтр: {chat.filters.describe()}"
    )


# ---------- клавиатуры ----------


def _mark(on: bool, text: str) -> str:
    return f"✓ {text}" if on else text


def sources_keyboard(chat: Chat) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=_mark(name in chat.sources, SOURCE_NAMES.get(name, name)),
                                  callback_data=f"src:{name}")] for name in [*SOURCES, "telegram"]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def filter_keyboard(chat: Chat) -> InlineKeyboardMarkup:
    f = chat.filters
    rows = [[InlineKeyboardButton(text=_mark(f.region == k, v.capitalize()), callback_data=f"flt:reg:{k}")]
            for k, v in REGIONS.items()]
    rows.append([InlineKeyboardButton(text=_mark(f.format == k, v.capitalize()), callback_data=f"flt:fmt:{k}")
                 for k, v in FORMATS.items()])
    group_buttons = []
    for group, title in GROUPS.items():
        n = sum(TOPICS[t].group == group for t in f.topics)
        group_buttons.append(InlineKeyboardButton(text=f"{title}: {n}" if n else f"{title}…",
                                                  callback_data=f"flt:menu:{group}"))
    rows.append(group_buttons)
    rows.append([InlineKeyboardButton(text=_mark(f.period_days == k, v), callback_data=f"flt:per:{k}")
                 for k, v in PERIODS.items()])
    rows.append([InlineKeyboardButton(text="Сбросить", callback_data="flt:reset"),
                 InlineKeyboardButton(text="Показать дайджест", callback_data="flt:show")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def topics_keyboard(chat: Chat, group: str) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=_mark(t.key in chat.filters.topics, t.label), callback_data=f"flt:top:{t.key}")
               for t in TOPICS.values() if t.group == group]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text="Любые", callback_data=f"flt:clear:{group}"),
                 InlineKeyboardButton(text="Готово", callback_data="flt:menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


FILTER_TEXT = (
    "<b>Фильтр</b>\n"
    "Регион: «Россия + онлайн в мире» — российские события и международные онлайн-хакатоны.\n"
    "Тематика разбита на три раздела: направление (что разрабатывают), сфера (для какой отрасли) "
    "и для кого. Внутри раздела подходит любая из отмеченных тем, между разделами — все сразу: "
    "AI + медицина значит AI-хакатоны в медицине.\n"
    "Последняя строка — насколько далеко вперёд смотреть по дате старта."
)
TOPICS_TEXT = {
    "direction": "<b>Направление</b> — что разрабатывают. Отметьте интересные; если ничего не отмечено, подходят любые.",
    "industry": "<b>Сфера</b> — для какой отрасли задачи. Если ничего не отмечено, подходят любые.",
    "audience": "<b>Для кого</b> — студентам, новичкам. Если ничего не отмечено, подходят все.",
}


# ---------- команды ----------


@router.message(CommandStart())
async def cmd_start(message: Message, db: Storage, cfg: config_module.Config) -> None:
    chat = db.subscribe(message.chat.id, cfg.default_interval, cfg.default_sources, cfg.default_channels)
    await message.answer(f"Подписка оформлена, дайджест будет приходить раз в {format_interval(chat.interval_sec)}.\n\n{HELP}")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP)


@router.message(Command("stop"))
async def cmd_stop(message: Message, db: Storage) -> None:
    db.unsubscribe(message.chat.id)
    await message.answer("Подписка выключена. Вернуться: /start")


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
        await bot.send_chat_action(chat.chat_id, "upload_photo")
        await send_digest(bot, db, chat, cfg.limit, manual=True)


@router.message(Command("timeline"))
async def cmd_timeline(message: Message, bot: Bot, db: Storage, cfg: config_module.Config) -> None:
    if chat := await _require_chat(message, db):
        await bot.send_chat_action(chat.chat_id, "upload_photo")
        await send_digest(bot, db, chat, cfg.limit, manual=True, with_text=False)


@router.message(Command("interval"))
async def cmd_interval(message: Message, command: CommandObject, db: Storage) -> None:
    chat = await _require_chat(message, db)
    if chat is None:
        return
    seconds = parse_interval(command.args or "")
    if seconds is None:
        await message.answer(
            f"Сейчас: раз в {format_interval(chat.interval_sec)}.\n"
            "Укажите интервал не меньше часа, например <code>/interval 12h</code>, "
            "<code>/interval 3d</code> или <code>/interval 1w</code>."
        )
        return
    db.set_interval(chat.chat_id, seconds)
    await message.answer(f"Готово, следующий дайджест через {format_interval(seconds)}.")


@router.message(Command("sources"))
async def cmd_sources(message: Message, db: Storage) -> None:
    if chat := await _require_chat(message, db):
        await message.answer("Откуда собирать хакатоны:", reply_markup=sources_keyboard(chat))


@router.message(Command("filter"))
async def cmd_filter(message: Message, db: Storage) -> None:
    if chat := await _require_chat(message, db):
        await message.answer(FILTER_TEXT, reply_markup=filter_keyboard(chat))


@router.message(Command("channels"))
async def cmd_channels(message: Message, command: CommandObject, db: Storage, cfg: config_module.Config) -> None:
    chat = await _require_chat(message, db)
    if chat is None:
        return
    args = (command.args or "").split()
    action, names = (args[0].lower(), args[1:]) if args else ("", [])
    if action in ("add", "del", "remove", "rm") and names:
        parsed = [normalize_channel(n) for n in names]
        bad = [n for n, p in zip(names, parsed) if p is None]
        good = [p for p in parsed if p]
        if action == "add":
            channels = list(dict.fromkeys([*chat.channels, *good]))[:MAX_CHANNELS]
        else:
            channels = [c for c in chat.channels if c not in good]
        db.set_channels(chat.chat_id, channels)
        reply = f"Каналов в списке: {len(channels)}."
        if bad:
            reply += f"\nНе похоже на username канала: {', '.join(bad)}"
        if action == "add" and "telegram" not in chat.sources:
            db.set_sources(chat.chat_id, [*chat.sources, "telegram"])
            reply += "\nИсточник «Telegram-каналы» включён."
        await message.answer(reply)
        return
    if action == "reset":
        db.set_channels(chat.chat_id, cfg.default_channels)
        await message.answer(f"Вернул стандартный список ({len(cfg.default_channels)} каналов).")
        return
    listing = "\n".join(f'<a href="https://t.me/{c}">@{c}</a>' for c in chat.channels) or "список пуст"
    await message.answer(
        f"<b>Каналы, из которых бот берёт анонсы</b>\n{listing}\n\n"
        "Добавить: <code>/channels add @username</code> (можно несколько через пробел)\n"
        "Убрать: <code>/channels del @username</code>\n"
        "Вернуть стандартный список: <code>/channels reset</code>\n\n"
        "Подходят только публичные каналы. Бот читает их веб-версию t.me/s/… "
        "и берёт посты, где упоминаются хакатоны.",
        link_preview_options=NO_PREVIEW,
    )


# ---------- кнопки ----------


@router.callback_query(F.data.startswith("src:"))
async def toggle_source(query: CallbackQuery, db: Storage) -> None:
    name = query.data.removeprefix("src:")
    chat = db.get(query.message.chat.id)
    if chat is None or (name not in SOURCES and name != "telegram"):
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


@router.callback_query(F.data.startswith("flt:"))
async def filter_action(query: CallbackQuery, bot: Bot, db: Storage, cfg: config_module.Config) -> None:
    chat = db.get(query.message.chat.id)
    if chat is None:
        await query.answer()
        return
    parts = query.data.split(":")
    f = chat.filters
    action, value = parts[1], parts[2] if len(parts) > 2 else ""
    if action == "show":
        await query.answer()
        await send_digest(bot, db, chat, cfg.limit, manual=True)
        return
    if action == "menu":
        # переключаем экран: главное меню фильтра или список тем одной группы
        if value in GROUPS:
            await query.message.edit_text(TOPICS_TEXT[value], reply_markup=topics_keyboard(chat, value))
        else:
            await query.message.edit_text(FILTER_TEXT, reply_markup=filter_keyboard(chat))
        await query.answer(f"Фильтр: {f.describe()}" if value not in GROUPS else None)
        return

    group = None
    if action == "reset":
        f.format, f.topics, f.period_days, f.region = "any", [], 0, "ru_online"
    elif action == "reg" and value in REGIONS:
        f.region = value
    elif action == "fmt" and value in FORMATS:
        f.format = value
    elif action == "top" and value in TOPICS:
        group = TOPICS[value].group
        f.topics = [t for t in f.topics if t != value] if value in f.topics else [*f.topics, value]
    elif action == "clear" and value in GROUPS:
        group = value
        f.topics = [t for t in f.topics if TOPICS[t].group != value]
    elif action == "per" and value.isdigit() and int(value) in PERIODS:
        f.period_days = int(value)
    db.set_filters(chat.chat_id, f)
    markup = topics_keyboard(chat, group) if group else filter_keyboard(chat)
    try:
        await query.message.edit_reply_markup(reply_markup=markup)
    except TelegramBadRequest:  # «message is not modified» при повторном нажатии
        pass
    await query.answer(f"Фильтр: {f.describe()}")


# ---------- планировщик ----------


async def scheduler(bot: Bot, db: Storage, cfg: config_module.Config) -> None:
    while True:
        for chat in db.due():
            # переносим следующий запуск заранее, чтобы ошибка отправки не приводила к спаму каждую минуту
            db.schedule_next(chat)
            try:
                await send_digest(bot, db, chat, cfg.limit)
            except TelegramForbiddenError:
                log.info("Чат %s заблокировал бота, отписываю", chat.chat_id)
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
        BotCommand(command="timeline", description="Картинка-таймлайн"),
        BotCommand(command="filter", description="Фильтр: формат, темы, даты"),
        BotCommand(command="sources", description="Сайты-источники"),
        BotCommand(command="channels", description="Telegram-каналы"),
        BotCommand(command="interval", description="Как часто присылать"),
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
