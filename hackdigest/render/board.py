"""Табло ближайших хакатонов в стиле split-flap (аэропорт): PNG и анимированный GIF."""
import io
import random
import re
from datetime import datetime, timedelta
from functools import lru_cache

from PIL import Image, ImageDraw, ImageEnhance

from hackdigest.models import Hackathon
from hackdigest.render import font, msk, png
from hackdigest.text import strip_emoji

BG = "#0E0F0F"
TILE = "#1F2121"  # верхняя половина флапа
TILE_LO = "#191B1B"  # нижняя — чуть темнее
SEAM = "#060707"
AMBER = "#FFB52E"
WHITE = "#ECE7DA"
DIM = "#6B6A63"
RED = "#FF5A3C"
GREEN = "#5BD38A"

# Рисуем с двойным разрешением и без колонки города (она есть в приложении): на телефоне табло
# показывается в ширину экрана, и только крупный исходник остаётся чётким после сжатия Telegram.
S = 2
PAD = 36 * S
CW, CH, GAP = 28 * S, 46 * S, 3 * S  # плитка и зазор между плитками
COL_GAP, ROW_GAP = 16 * S, 10 * S
TOP = 134 * S  # первая строка табло
TITLE_TILES = 17
COLS = (("№", 2), ("ДАТА", 5), ("ХАКАТОН", TITLE_TILES), ("СТАТУС", 8))
W = 2 * PAD + sum(n * (CW + GAP) - GAP for _, n in COLS) + COL_GAP * (len(COLS) - 1)

# ---------- текст для плиток ----------

CITY_CODES = {
    "москва": "МСК", "санкт-петербург": "СПБ", "петербург": "СПБ", "спб": "СПБ", "казань": "КЗН",
    "екатеринбург": "ЕКБ", "новосибирск": "НСК", "нижний новгород": "ННВ", "иннополис": "ИНП",
    "владивосток": "ВЛД", "самара": "СМР", "ростов-на-дону": "РНД", "краснодар": "КРД", "пермь": "ПРМ",
    "уфа": "УФА", "воронеж": "ВРН", "челябинск": "ЧЛБ", "красноярск": "КРС", "томск": "ТМС",
    "омск": "ОМС", "тюмень": "ТЮМ", "калининград": "КЛД", "сочи": "СОЧ", "иркутск": "ИРК",
    "хабаровск": "ХБР", "севастополь": "СВП", "ижевск": "ИЖВ", "благовещенск": "БЛГ", "рязань": "РЯЗ",
    "майкоп": "МКП", "звенигород": "ЗВН", "ярославль": "ЯРС", "саратов": "СРТ", "тула": "ТУЛ",
}


def city_code(h: Hackathon) -> str:
    """Трёхбуквенный код города, как на табло аэропорта: ОНЛ, МСК, СПБ… «—», если неизвестно."""
    city = h.location.split(",")[0].strip().lower()
    if h.online is True or city in ("онлайн", "online"):
        return "ОНЛ"
    if city in CITY_CODES:
        return CITY_CODES[city]
    letters = re.sub(r"[^a-zа-яё]", "", city)
    return letters[:3].upper() if len(letters) >= 3 else "—"


_NOISE = re.compile(r"[-–—]?\s*\b(?:хакатон\w*|hackathon|всероссийск\w*|международн\w*)\b", re.I)
_QUOTED = re.compile(r"[«\"“„]([^»\"”“]{3,})[»\"”“]")
_TILE_CHARS = re.compile(r"[^0-9A-ZА-ЯЁ !#&+.,:/'()@%№×-]")


def _clean(text: str) -> str:
    t = _NOISE.sub(" ", strip_emoji(text))
    t = re.sub(r"(?<!\d)20[2-3]\d(?!\d)", " ", t)  # год, в т.ч. приклеенный: EvoHacks2026
    t = re.sub(r"\(\W*\)|[«»\"“”„]", " ", t)  # пустые скобки от «(Хакатон)» и кавычки
    t = _TILE_CHARS.sub("", t.upper().replace("–", "-").replace("—", "-"))
    return re.sub(r"\s+", " ", t).strip(" -.,:;/|(&+")


def short_title(title: str, n: int = TITLE_TILES) -> str:
    """Название для плиток: без эмодзи, «хакатона», года и кавычек, капсом, обрезано по слову."""
    t = _clean(title)
    if len(t) > n and (m := _QUOTED.search(title)) and _clean(m.group(1)):
        t = _clean(m.group(1))  # «Хакатон «ПриморТех» по разработке ПО…» → ПРИМОРТЕХ
    if len(t) > n:
        head = t[: n + 1]
        t = head.rsplit(" ", 1)[0] if " " in head else t[:n]
    return t.rstrip(" -.,:;/|(&+")


def _running(h: Hackathon, now: datetime) -> bool:
    if not h.start or h.start > now:
        return False
    return h.end > now if h.end else msk(h.start).date() == msk(now).date()


def _status(h: Hackathon, now: datetime) -> tuple[str, str]:
    if _running(h, now):
        return "ИДЁТ", GREEN
    if h.reg_deadline:
        if h.reg_deadline <= now:
            return "ЗАКРЫТА", DIM
        return f"ДО {msk(h.reg_deadline):%d.%m}", RED if h.reg_deadline - now <= timedelta(days=3) else AMBER
    return "ОТКРЫТА", AMBER


def _rows(items: list[Hackathon], rows: int) -> tuple[list[Hackathon], int]:
    shown = [h for h in items if h.key_date]  # без дат — и анонсы из каналов, и сайты — на табло не попадают
    return shown[:rows], max(0, len(shown) - rows)


# ---------- плитки ----------


@lru_cache(maxsize=1)
def _glyph_font():
    f = font("JetBrainsMono-ExtraBold", 30 * S)
    cap = -f.getbbox("H", anchor="ls")[1]
    return f, (CH + cap) / 2  # базовая линия, при которой заглавные стоят ровно по центру


@lru_cache(maxsize=2048)
def _tile(ch: str, color: str) -> Image.Image:
    im = Image.new("RGB", (CW, CH), BG)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, CW - 1, CH - 1), radius=4 * S, fill=TILE)
    # нижний флап темнее; скругление у шва даёт зазор на петле, как у настоящих флапов
    d.rounded_rectangle((0, CH // 2, CW - 1, CH - 1), radius=3 * S, fill=TILE_LO)
    if ch != " ":
        f, base = _glyph_font()
        d.text((CW / 2, base), ch, font=f, fill=color, anchor="ms")
    d.line((0, CH // 2 - 1, CW, CH // 2 - 1), fill=SEAM, width=2 * S)
    return im


@lru_cache(maxsize=4096)
def _flip(old: tuple[str, str], new: tuple[str, str], phase: int) -> Image.Image:
    """Плитка посреди переворота: сверху уже новый символ, снизу ещё старый,
    поверх — падающий флап, сжатый перспективой (phase 0 — над швом, 1 — под швом)."""
    a, b = _tile(*old), _tile(*new)
    h = CH // 2
    im = a.copy()
    im.paste(b.crop((0, 0, CW, h)), (0, 0))
    fh = int(h * (0.62 if phase == 0 else 0.48))
    if phase == 0:
        flap = a.crop((0, 0, CW, h)).resize((CW, fh), Image.Resampling.BILINEAR)
        flap = ImageEnhance.Brightness(flap).enhance(1.15)  # ловит свет, наклоняясь к зрителю
        im.paste(flap, (0, h - fh))
    else:
        flap = b.crop((0, h, CW, CH)).resize((CW, fh), Image.Resampling.BILINEAR)
        flap = ImageEnhance.Brightness(flap).enhance(0.8)
        im.paste(flap, (0, h))
        ImageDraw.Draw(im).line((1, h + fh, CW - 2, h + fh), fill=SEAM, width=2 * S)  # тень под кромкой
    return im


# ---------- раскладка ----------


def _layout(items: list[Hackathon], new_uids: set[str], now: datetime, rows: int):
    """Фон без символов и список ячеек (x, y, символ, цвет). None, если показывать нечего."""
    shown, more = _rows(items, rows)
    if not shown:
        return None
    height = TOP + len(shown) * (CH + ROW_GAP) + 64 * S
    im = Image.new("RGB", (W, height), BG)
    d = ImageDraw.Draw(im)
    d.text((PAD, 66 * S), "ХАКАТОНЫ", font=font("JetBrainsMono-ExtraBold", 44 * S), fill=WHITE, anchor="ls")
    d.text((W - PAD, 66 * S), f"{msk(now):%d.%m · %H:%M} МСК", font=font("JetBrainsMono-Medium", 22 * S),
           fill=DIM, anchor="rs")

    xs, x = [], PAD
    for name, n in COLS:
        xs.append(x)
        d.text((x, TOP - 14 * S), name, font=font("JetBrainsMono-Medium", 19 * S), fill=DIM, anchor="ls")
        x += n * (CW + GAP) - GAP + COL_GAP

    cells = []
    for r, h in enumerate(shown):
        y = TOP + r * (CH + ROW_GAP)
        status, color = _status(h, now)
        texts = (f"{r + 1:>2}", f"{msk(h.key_date):%d.%m}", short_title(h.title), status)
        colors = (WHITE, WHITE, AMBER, color)
        for cx, (_, n), text, c in zip(xs, COLS, texts, colors):
            for i, ch in enumerate(text[:n].ljust(n)):
                tx = cx + i * (CW + GAP)
                im.paste(_tile(" ", c), (tx, y))
                if ch != " ":
                    cells.append((tx, y, ch, c))
        if h.uid in new_uids:
            d.rectangle((PAD - 22 * S, y + 8 * S, PAD - 15 * S, y + CH - 8 * S), fill=AMBER)

    # легенда
    y = height - 26 * S
    legend = font("JetBrainsMono-Medium", 19 * S)
    d.rectangle((PAD, y - 15 * S, PAD + 7 * S, y + S), fill=AMBER)
    x = PAD + 16 * S
    for text, c in (("НОВОЕ", DIM), ("   КРАСНЫМ", RED), (" — ГОРИТ ≤ 3 ДНЕЙ", DIM),
                    ("   ЗЕЛЁНЫМ", GREEN), (" — УЖЕ ИДЁТ", DIM)):
        d.text((x, y), text, font=legend, fill=c, anchor="ls")
        x += legend.getlength(text)
    if more:
        d.text((W - PAD, y), f"+{more} НИЖЕ", font=legend, fill=AMBER, anchor="rs")
    return im, cells


def render_board(items: list[Hackathon], new_uids: set[str], now: datetime, rows: int = 10) -> bytes | None:
    """PNG-табло: первые rows событий с датой (порядок задаёт вызывающий). None, если показывать нечего."""
    layout = _layout(items, new_uids, now, rows)
    if not layout:
        return None
    im, cells = layout
    for x, y, ch, c in cells:
        im.paste(_tile(ch, c), (x, y))
    return png(im)


# ---------- анимация ----------

FRAME_MS = 50  # каждый кадр — полфлипа: ~10 перелистываний в секунду, как у настоящего табло
FIRST_MS, LAST_MS = 400, 5000
_POOL = "ABCDEFGHKMNPRSTXZАБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЫЭЮЯ0123456789"


def render_board_gif(items: list[Hackathon], new_uids: set[str], now: datetime, rows: int = 10) -> bytes | None:
    """То же табло, но символы перелистываются и встают на место слева направо, строка за строкой.
    Последний кадр держится 5 с — Telegram крутит GIF по кругу."""
    layout = _layout(items, new_uids, now, rows)
    if not layout:
        return None
    base, cells = layout
    rng = random.Random(0)
    plans = []  # (первый кадр, последовательность символов)
    for x, y, ch, c in cells:
        col, row = (x - PAD) // (CW + GAP), (y - TOP) // (CH + ROW_GAP)
        start = 1 + round(row * 1.1 + col * 0.33) + rng.randint(0, 1)
        seq = [(rng.choice(_POOL), c) for _ in range(rng.randint(2, 4))] + [(ch, c)]
        plans.append((start, seq))
    total = max(start + 2 * len(seq) for start, seq in plans) + 1

    def state(f: int, start: int, seq: list) -> tuple:
        k = f - start
        if k < 0:
            return (" ", seq[-1][1]), None
        i, phase = divmod(k, 2)
        if i >= len(seq):
            return seq[-1], None
        return seq[i], (seq[i - 1] if i else (" ", seq[-1][1]), phase)

    canvas, frames, prev = base.copy(), [], [None] * len(cells)
    for f in range(total):
        for j, ((x, y, _, _), (start, seq)) in enumerate(zip(cells, plans)):
            st = state(f, start, seq)
            if st == prev[j]:
                continue  # перерисовываем только плитки, которые шевелятся
            prev[j] = st
            new, flip = st
            canvas.paste(_flip(flip[0], new, flip[1]) if flip else _tile(*new), (x, y))
        frames.append(canvas.copy())

    # общая палитра по нескольким кадрам; без дизеринга — плоские цвета сжимаются лучше
    picks = frames[2::3] + frames[-1:]
    sample = Image.new("RGB", (W, base.height * len(picks)))
    for i, fr in enumerate(picks):
        sample.paste(fr, (0, i * base.height))
    palette = sample.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    frames = [fr.quantize(palette=palette, dither=Image.Dither.NONE) for fr in frames]
    durations = [FIRST_MS] + [FRAME_MS] * (total - 2) + [LAST_MS]
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=durations, loop=0,
                   disposal=1, optimize=False)
    return buf.getvalue()
