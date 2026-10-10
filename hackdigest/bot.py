import asyncio
import logging
from html import escape
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramUnauthorizedError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (BotCommand, BufferedInputFile, CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, LinkPreviewOptions, MenuButtonWebApp, Message, WebAppInfo)

from hackdigest import config as config_module
from hackdigest.cards import caption, change_notice, due_reminder, ics
from hackdigest.digest import (MONTHS_FULL, SOURCE_NAMES, board_order, build_digest, format_interval, format_line,
                               URGENT, parse_interval, plural, select)
from hackdigest.models import Hackathon
from hackdigest.render.board import render_board, render_board_gif
from hackdigest.render.ticket import render_ticket
from hackdigest.filters import FORMATS, PERIODS, REGIONS, Filters
from hackdigest.text import strip_emoji
from hackdigest.topics import GROUPS, TOPICS
from hackdigest.sources import SOURCES, fetch_all
from hackdigest.sources.telegram import normalize_channel
from hackdigest.storage import Chat, Storage, event_id
from hackdigest.timeline import render_timeline

log = logging.getLogger(__name__)
router = Router()
CHECK_EVERY = 60  # как часто планировщик проверяет, кому пора отправлять дайджест
MAX_CHANNELS = 40
BOARD_ROWS = 10
VOTE_OPTIONS = 6
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

HELP = (
    "Бот присылает дайджест ближайших хакатонов: Devpost, Codenrock и другие сайты, "
    "а также анонсы из Telegram-каналов вузов и компаний.\n\n"
    "/digest — дайджест прямо сейчас\n"
    "/board — табло ближайших хакатонов; номер на кнопке открывает карточку\n"
    "/tracked — за чем вы следите: напомню о дедлайне за 3 дня и за день, а о старте — накануне\n"
    "/vote — голосование в группе: на какой хакатон идём\n"
    "/timeline — картинка-таймлайн\n"
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
    raw, failed = await fetch_all(chat.sources, chat.channels)
    items = select(raw, chat.filters, now)
    uids = [h.uid for h in items]
    new = db.unseen(chat.chat_id, uids)
    if len(new) == len(uids):  # первый дайджест: «новым» было бы всё, пометки ничего не дают
        new = set()
    changes = db.save_events(items)
    return now, items, new, failed, changes


async def notify_changes(bot: Bot, db: Storage, changes: list[tuple[Hackathon, Hackathon]], now: datetime) -> None:
    """Тем, кто следит за событием, — сообщение о переносе дат или смене формата."""
    for old, new in changes:
        if text := change_notice(old, new, now):
            for chat_id in db.watchers(event_id(new)):
                await _safe_send(bot, chat_id, text, reply_markup=card_button(new))


async def _safe_send(bot: Bot, chat_id: int, text: str, **kw) -> None:
    try:
        await bot.send_message(chat_id, text, link_preview_options=NO_PREVIEW, **kw)
    except (TelegramBadRequest, TelegramForbiddenError):
        log.info("Не удалось написать в чат %s", chat_id)


def board_caption(items: list[Hackathon], new: set[str], now: datetime) -> str:
    n = len(items)
    text = f"<b>Табло на {now.day} {MONTHS_FULL[now.month - 1]}</b> · {n} {plural(n, ('событие', 'события', 'событий'))}"
    if new:
        text += f", новых: {len(new)}"
    return text + "\nНомер на кнопке открывает посадочный талон хакатона."


def board_keyboard(rows: list[Hackathon], group: bool) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=str(i), callback_data=f"ev:{event_id(h)}") for i, h in enumerate(rows, 1)]
    keyboard = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
    if group:
        keyboard.append([InlineKeyboardButton(text="Голосовать: куда идём", callback_data="vote")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def app_caption(items: list[Hackathon], now: datetime) -> str:
    """Одна строка под табло в режиме Mini App: всё остальное — в приложении."""
    items = [h for h in items if h.source != "telegram"]  # в приложении посты каналов не показываются
    n = len(items)
    hot = sum(1 for h in items if h.reg_deadline and now < h.reg_deadline <= now + URGENT)
    text = f"<b>Табло на {now.day} {MONTHS_FULL[now.month - 1]}</b> · {n} {plural(n, ('рейс', 'рейса', 'рейсов'))}"
    return text + (f", горят {hot}" if hot else "")


def app_url(url: str, bot_username: str | None) -> str:
    """Адрес Mini App с именем бота: по нему кнопка «Напомнить» в приложении открывает чат с ботом."""
    return f"{url}{'&' if '?' in url else '?'}bot={bot_username}" if bot_username else url


def app_keyboard(url: str, group: bool) -> InlineKeyboardMarkup:
    # в группах Telegram не открывает Mini App из inline-кнопки — там обычная ссылка
    button = (InlineKeyboardButton(text="Открыть табло", url=url) if group
              else InlineKeyboardButton(text="Открыть табло", web_app=WebAppInfo(url=url)))
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


async def send_board(bot: Bot, db: Storage, chat_id: int, items: list[Hackathon], new: set[str], now: datetime,
                     group: bool, animate: bool = False, webapp_url: str = "") -> bool:
    rows = board_order(items, now)[:BOARD_ROWS]
    if not rows:
        return False
    db.set_board(chat_id, [event_id(h) for h in rows])
    if webapp_url:
        markup, text = app_keyboard(app_url(webapp_url, (await bot.me()).username), group), app_caption(items, now)
    else:
        markup, text = board_keyboard(rows, group), board_caption(items, new, now)
    gif = await asyncio.to_thread(render_board_gif, rows, new, now, BOARD_ROWS) if animate else None
    if gif:
        await bot.send_animation(chat_id, BufferedInputFile(gif, "board.gif"), caption=text, reply_markup=markup)
    else:
        png = await asyncio.to_thread(render_board, rows, new, now, BOARD_ROWS)
        await bot.send_photo(chat_id, BufferedInputFile(png, "board.png"), caption=text, reply_markup=markup)
    return True


async def send_digest(bot: Bot, db: Storage, chat: Chat, limit: int, manual: bool = False, webapp_url: str = "") -> None:
    now, items, new, failed, changes = await collect(chat, db)
    await notify_changes(bot, db, changes, now)
    if not items:
        if manual:
            await bot.send_message(chat.chat_id, "Под текущий фильтр ничего не нашлось. Ослабить его можно в /filter.")
        return
    await send_board(bot, db, chat.chat_id, items, new, now, group=chat.chat_id < 0, webapp_url=webapp_url)
    if webapp_url:  # режим Mini App: одно сообщение-табло, без текстовых простыней
        db.mark_seen(chat.chat_id, [h.uid for h in items])
        return
    username = (await bot.me()).username
    card_url = lambda h: f"https://t.me/{username}?start=e_{event_id(h)}"  # noqa: E731
    for text in build_digest(items, new, now, chat.sources, chat.filters, limit=limit, failed=failed,
                             card_url=card_url):
        await bot.send_message(chat.chat_id, text, link_preview_options=NO_PREVIEW)
    db.mark_seen(chat.chat_id, [h.uid for h in items])


# ---------- карточка события ----------


def card_button(h: Hackathon) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Открыть карточку", callback_data=f"ev:{event_id(h)}")]])


def card_keyboard(h: Hackathon, tracked: bool) -> InlineKeyboardMarkup:
    eid = event_id(h)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Регистрация и детали ↗", url=h.url)],
        [InlineKeyboardButton(text="Не следить" if tracked else "Следить и напоминать", callback_data=f"trk:{eid}"),
         InlineKeyboardButton(text="В календарь", callback_data=f"ics:{eid}")],
    ])


async def send_card(bot: Bot, db: Storage, chat_id: int, eid: str) -> None:
    h = db.event(eid)
    if h is None:
        await bot.send_message(chat_id, "Это событие уже не найти — возможно, оно прошло. Свежий список: /digest")
        return
    now = datetime.now(timezone.utc)
    tracked = db.is_tracked(chat_id, eid)
    png = await asyncio.to_thread(render_ticket, h, now)
    await bot.send_photo(chat_id, BufferedInputFile(png, "ticket.png"), caption=caption(h, now, tracked),
                         reply_markup=card_keyboard(h, tracked))


async def send_reminders(bot: Bot, db: Storage) -> None:
    now = datetime.now(timezone.utc)
    for chat_id, h, sent in db.tracked():
        if due := due_reminder(h, sent, now):
            keys, text = due
            db.mark_reminded(chat_id, event_id(h), keys)  # сначала отмечаем — без повторов при ошибке отправки
            await _safe_send(bot, chat_id, text, reply_markup=card_button(h))


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


@router.message(CommandStart(deep_link=True, magic=F.args.startswith("e_")))
async def cmd_start_card(message: Message, command: CommandObject, bot: Bot, db: Storage) -> None:
    """Ссылка «карточка» из текста дайджеста: t.me/<бот>?start=e_<id>."""
    await send_card(bot, db, message.chat.id, command.args.removeprefix("e_"))


@router.message(CommandStart(deep_link=True, magic=F.args.startswith("t_")))
async def cmd_start_track(message: Message, command: CommandObject, db: Storage, cfg: config_module.Config) -> None:
    """Кнопка «Напомнить в Telegram» в Mini App: t.me/<бот>?start=t_<id>."""
    eid = command.args.removeprefix("t_")
    db.subscribe(message.chat.id, cfg.default_interval, cfg.default_sources, cfg.default_channels)
    if db.event(eid) is None:
        # событие могло ещё не попасть в базу бота (приложение видит весь мир, а дайджест — фильтр чата)
        raw, _ = await fetch_all(list(SOURCES), [])
        db.save_events(select(raw, Filters(region="world"), datetime.now(timezone.utc)))
    h = db.event(eid)
    if h is None:
        await message.answer("Не нашёл это событие. Добавьте его в календарь прямо из талона в приложении.")
        return
    db.track(message.chat.id, eid, True)
    await message.answer(f"Напомню про <b>{escape(strip_emoji(h.title))}</b>: за 3 дня и за день до конца регистрации "
                         "и перед стартом.", reply_markup=card_button(h))


@router.message(CommandStart())
async def cmd_start(message: Message, db: Storage, cfg: config_module.Config) -> None:
    chat = db.subscribe(message.chat.id, cfg.default_interval, cfg.default_sources, cfg.default_channels)
    if cfg.webapp_url:
        await message.answer(
            f"Раз в {format_interval(chat.interval_sec)} пришлю табло ближайших хакатонов. "
            "Всё остальное — в приложении: кнопка «Табло» рядом с полем ввода.",
            reply_markup=app_keyboard(app_url(cfg.webapp_url, (await message.bot.me()).username), message.chat.id < 0))
        return
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
        await send_digest(bot, db, chat, cfg.limit, manual=True, webapp_url=cfg.webapp_url)


@router.message(Command("timeline"))
async def cmd_timeline(message: Message, bot: Bot, db: Storage) -> None:
    if chat := await _require_chat(message, db):
        await bot.send_chat_action(chat.chat_id, "upload_photo")
        now, items, new, _, _ = await collect(chat, db)
        png = await asyncio.to_thread(render_timeline, items, new, now)
        if png:
            await bot.send_photo(chat.chat_id, BufferedInputFile(png, "timeline.png"))
        else:
            await message.answer("В ближайшие недели нет событий с точными датами.")


@router.message(Command("board"))
async def cmd_board(message: Message, bot: Bot, db: Storage) -> None:
    if chat := await _require_chat(message, db):
        await bot.send_chat_action(chat.chat_id, "upload_video")
        now, items, new, _, _ = await collect(chat, db)
        if not await send_board(bot, db, chat.chat_id, items, new, now, group=chat.chat_id < 0):
            await message.answer("Под текущий фильтр ничего не нашлось. Ослабить его можно в /filter.")


@router.message(Command("tracked"))
async def cmd_tracked(message: Message, db: Storage) -> None:
    now = datetime.now(timezone.utc)
    items = sorted((h for _, h, _ in db.tracked(message.chat.id)),
                   key=lambda h: min((d for d in (h.reg_deadline, h.start) if d), default=now))
    if not items:
        await message.answer("Вы пока ни за чем не следите. Откройте карточку хакатона — кнопкой с номером под "
                             "табло или ссылкой «карточка» в дайджесте — и нажмите «Следить».")
        return
    lines = ["<b>Вы следите</b>", *(f"{i}. {format_line(h, now)}" for i, h in enumerate(items, 1))]
    buttons = [InlineKeyboardButton(text=str(i), callback_data=f"ev:{event_id(h)}") for i, h in enumerate(items, 1)]
    keyboard = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
    keyboard.append([InlineKeyboardButton(text="Всё в календарь", callback_data="ics:all")])
    await message.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
                         link_preview_options=NO_PREVIEW)


@router.message(Command("vote"))
async def cmd_vote(message: Message, bot: Bot, db: Storage) -> None:
    await start_vote(bot, db, message.chat.id)


async def start_vote(bot: Bot, db: Storage, chat_id: int) -> None:
    events = [h for h in (db.event(e) for e in db.board(chat_id)[:VOTE_OPTIONS]) if h]
    if len(events) < 2:
        await bot.send_message(chat_id, "Сначала нужно табло: /board")
        return
    options = [h.title if len(h.title) <= 100 else h.title[:99] + "…" for h in events]
    await bot.send_poll(chat_id, "На какой хакатон идём?", options, is_anonymous=False,
                        allows_multiple_answers=True)


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
        await send_digest(bot, db, chat, cfg.limit, manual=True, webapp_url=cfg.webapp_url)
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


@router.callback_query(F.data.startswith("ev:"))
async def open_card(query: CallbackQuery, bot: Bot, db: Storage) -> None:
    await query.answer()
    await send_card(bot, db, query.message.chat.id, query.data.removeprefix("ev:"))


@router.callback_query(F.data.startswith("trk:"))
async def toggle_track(query: CallbackQuery, db: Storage) -> None:
    eid = query.data.removeprefix("trk:")
    h = db.event(eid)
    if h is None:
        await query.answer("Событие не найдено", show_alert=True)
        return
    chat_id = query.message.chat.id
    on = not db.is_tracked(chat_id, eid)
    db.track(chat_id, eid, on)
    now = datetime.now(timezone.utc)
    try:
        await query.message.edit_caption(caption=caption(h, now, on), reply_markup=card_keyboard(h, on))
    except TelegramBadRequest:
        pass
    await query.answer("Напомню о дедлайне и старте" if on else "Больше не слежу")


@router.callback_query(F.data.startswith("ics:"))
async def send_ics(query: CallbackQuery, bot: Bot, db: Storage) -> None:
    eid = query.data.removeprefix("ics:")
    chat_id = query.message.chat.id
    items = [h for _, h, _ in db.tracked(chat_id)] if eid == "all" else [h for h in [db.event(eid)] if h]
    await query.answer()
    if not items:
        return
    name = "hackathons.ics" if eid == "all" else f"hackathon-{eid}.ics"
    await bot.send_document(chat_id, BufferedInputFile(ics(items, datetime.now(timezone.utc)), name),
                            caption="Откройте файл — события добавятся в календарь вместе с напоминанием о регистрации.")


@router.callback_query(F.data == "vote")
async def vote_button(query: CallbackQuery, bot: Bot, db: Storage) -> None:
    await query.answer()
    await start_vote(bot, db, query.message.chat.id)


# ---------- планировщик ----------


async def scheduler(bot: Bot, db: Storage, cfg: config_module.Config) -> None:
    while True:
        try:
            chats = db.due()
        except Exception:  # без этого одна ошибка базы молча остановила бы все рассылки
            log.exception("Планировщик: не удалось прочитать подписки")
            chats = []
        for chat in chats:
            # переносим следующий запуск заранее, чтобы ошибка отправки не приводила к спаму каждую минуту
            db.schedule_next(chat)
            try:
                await send_digest(bot, db, chat, cfg.limit, webapp_url=cfg.webapp_url)
            except TelegramForbiddenError:
                log.info("Чат %s заблокировал бота, отписываю", chat.chat_id)
                db.unsubscribe(chat.chat_id)
            except Exception:
                log.exception("Не удалось отправить дайджест в чат %s", chat.chat_id)
        try:
            await send_reminders(bot, db)
        except Exception:
            log.exception("Планировщик: не удалось разослать напоминания")
        await asyncio.sleep(CHECK_EVERY)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = config_module.load()
    db = Storage(cfg.db_path)
    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        me = await bot.me()
    except TelegramUnauthorizedError:
        await bot.session.close()
        raise SystemExit(f"Telegram не принял токен {config_module.mask(cfg.bot_token)}. Возьмите актуальный в @BotFather "
                         "(/mybots → бот → API Token) и запустите: python3 -m hackdigest.setup")
    log.info("Бот @%s запущен. Mini App: %s", me.username, cfg.webapp_url or "не задан (дайджест текстом)")
    dp = Dispatcher()
    dp.include_router(router)
    dp["db"] = db
    dp["cfg"] = cfg
    if cfg.webapp_url:
        # минимум команд: всё остальное делается в приложении
        url = app_url(cfg.webapp_url, (await bot.me()).username)
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Табло", web_app=WebAppInfo(url=url)))
        await bot.set_my_commands([
            BotCommand(command="digest", description="Табло сейчас"),
            BotCommand(command="interval", description="Как часто присылать"),
            BotCommand(command="stop", description="Отписаться"),
        ])
    else:
        await set_full_commands(bot)
    task = asyncio.create_task(scheduler(bot, db, cfg))
    try:
        await dp.start_polling(bot)
    finally:
        task.cancel()


async def set_full_commands(bot: Bot) -> None:
    await bot.set_my_commands([
        BotCommand(command="digest", description="Дайджест сейчас"),
        BotCommand(command="board", description="Табло с карточками хакатонов"),
        BotCommand(command="tracked", description="За чем я слежу"),
        BotCommand(command="vote", description="Голосование: куда идём"),
        BotCommand(command="timeline", description="Картинка-таймлайн"),
        BotCommand(command="filter", description="Фильтр: формат, темы, даты"),
        BotCommand(command="sources", description="Сайты-источники"),
        BotCommand(command="channels", description="Telegram-каналы"),
        BotCommand(command="interval", description="Как часто присылать"),
        BotCommand(command="settings", description="Текущие настройки"),
        BotCommand(command="stop", description="Отписаться"),
    ])


if __name__ == "__main__":
    asyncio.run(main())
