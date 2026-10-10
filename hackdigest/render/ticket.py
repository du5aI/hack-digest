"""Карточка события в виде посадочного талона (PNG 1280×640)."""
import hashlib
import math
import random
import re
from datetime import datetime

from PIL import Image, ImageDraw

from hackdigest.digest import MONTHS_FULL, SOURCE_NAMES, plural
from hackdigest.models import Hackathon
from hackdigest.render import font, msk, png
from hackdigest.text import strip_emoji
from hackdigest.topics import labels, topics_of

PAPER = "#F2EDE1"
INK = "#17171A"
SPOT = "#E8432B"
MUTE = "#7A766C"
RULE = "#CFC8B7"
HOLE = "#D9D3C4"

W, H = 1280, 640
STUB = 930  # линия отрыва
LEFT, STUB_X = 48, STUB + 40
MAIN_W, STUB_W = STUB - 40 - LEFT, W - 40 - STUB_X

PREFIX = {"hackathons_rus": "HRU", "codenrock": "CNR", "leader_id": "LDR", "devpost": "DVP",
          "mlh": "MLH", "devfolio": "DVF", "telegram": "TGM"}
DAYS = ("день", "дня", "дней")
HOURS = ("час", "часа", "часов")


def ticket_code(h: Hackathon) -> str:
    """Номер талона: префикс источника и четыре цифры из хэша uid (стабильно между запусками)."""
    n = int.from_bytes(hashlib.sha1(h.uid.encode()).digest()[:4]) % 10000
    return f"{PREFIX.get(h.source, h.source[:3].upper())}-{n:04d}"


def _fit(d: ImageDraw.ImageDraw, text: str, f, width: float) -> str:
    """Обрезает текст с многоточием под ширину."""
    if d.textlength(text, font=f) <= width:
        return text
    while text and d.textlength(text + "…", font=f) > width:
        text = text[:-1]
    return text.rstrip(" ,·-–—") + "…"


def _wrap(d: ImageDraw.ImageDraw, text: str, f, width: float) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        if lines and d.textlength(f"{lines[-1]} {word}", font=f) <= width:
            lines[-1] += f" {word}"
        else:
            lines.append(word)
    return lines


def _title(d: ImageDraw.ImageDraw, text: str) -> None:
    """Название крупно, с уменьшением шрифта: одна строка 72, две до 50, три до 36."""
    for size, max_lines in ((72, 1), (64, 2), (56, 2), (50, 2), (44, 3), (40, 3), (36, 3)):
        f = font("Unbounded-ExtraBold", size)
        lines = _wrap(d, text, f, MAIN_W)
        if len(lines) <= max_lines and all(d.textlength(ln, font=f) <= MAIN_W for ln in lines):
            break
    else:  # не влезло и в три строки мелким — режем с многоточием
        cut = len(lines) > 3
        lines = [_fit(d, ln, f, MAIN_W) for ln in lines[:3]]
        if cut and not lines[2].endswith("…"):
            lines[2] = _fit(d, lines[2] + "…", f, MAIN_W)
    # подпись и название — одним блоком по центру между шапкой и датами
    lh = round(size * 1.2)
    top = 84 + (216 - 28 - len(lines) * lh) // 2
    d.text((LEFT, top + 14), "НАЗВАНИЕ", font=font("JetBrainsMono-Medium", 17), fill=MUTE, anchor="ls")
    for i, ln in enumerate(lines):
        d.text((LEFT - 3, top + 28 + round(size * 0.95) + i * lh), ln, font=f, fill=INK, anchor="ls")


def _day(dt: datetime, now: datetime) -> str:
    s = f"{dt.day} {MONTHS_FULL[dt.month - 1]}"
    return s if dt.year == msk(now).year else f"{s} {dt.year}"


def _route(d: ImageDraw.ImageDraw, h: Hackathon, now: datetime) -> None:
    """Строка дат «откуда → куда»: старт → финиш, либо конец регистрации → «??.??»."""
    lab, big = font("JetBrainsMono-Medium", 17), font("Unbounded-ExtraBold", 96)
    year = msk(now).year

    def point(x: float, dt: datetime | None, label: str, color: str = INK) -> float:
        text = f"{msk(dt):%d.%m}" if dt else "??.??"
        if dt and msk(dt).year != year:
            label += f" · {msk(dt).year}"
        d.text((x, 414), text, font=big, fill=color, anchor="ls")
        d.text((x + 4, 444), label, font=lab, fill=MUTE, anchor="ls")
        return x + d.textlength(text, font=big)

    def arrow(x: float) -> float:
        d.text((x + 36, 386), "→", font=font("JetBrainsMono-ExtraBold", 60), fill=SPOT, anchor="lm")
        return x + 136

    if h.start:
        same_day = not h.end or msk(h.end).date() == msk(h.start).date()
        x = point(LEFT, h.start, "ДЕНЬ ХАКАТОНА" if h.end and same_day else "СТАРТ")
        if not same_day:
            point(arrow(x), h.end, "ФИНИШ")
    elif h.reg_deadline:
        point(arrow(point(LEFT, h.reg_deadline, "КОНЕЦ РЕГИСТРАЦИИ")), None, "СТАРТ УТОЧНЯЕТСЯ", RULE)
    else:
        f = font("Unbounded-ExtraBold", 52)
        d.text((LEFT, 400), _fit(d, strip_emoji(h.dates_text) or "Даты уточняются", f, MAIN_W),
               font=f, fill=INK, anchor="ls")
        d.text((LEFT + 4, 444), "ДАТЫ", font=lab, fill=MUTE, anchor="ls")


def _fields(h: Hackathon) -> list[tuple[str, str]]:
    place = h.location.strip()
    if h.online is True:
        fmt = "Онлайн"
    elif h.online is False:
        fmt = f"Офлайн · {place}" if place else "Офлайн"
    else:
        fmt = place
    if h.source == "telegram":
        source = next((p for p in re.split(r"\s*(?:\|+|/|>>)\s*", h.via) if p), "Telegram")
    else:
        source = SOURCE_NAMES.get(h.source, h.source)
    fields = [("ФОРМАТ", fmt), ("ПРИЗ", h.prize.replace("₹", "INR")), ("ИСТОЧНИК", source)]
    return [(k, v) for k, v in fields if v]


FIELD_GAP, FIELD_MIN = 40, 240


def _widths(d: ImageDraw.ImageDraw, values: list[str], f) -> list[float]:
    """Ширины колонок ФОРМАТ / ПРИЗ / ИСТОЧНИК: по тексту, но не уже FIELD_MIN;
    если всё не влезает, урезается самая широкая."""
    widths = [max(FIELD_MIN, d.textlength(v, font=f)) for v in values]
    excess = sum(widths) + FIELD_GAP * (len(widths) - 1) - MAIN_W
    if excess > 0:
        i = widths.index(max(widths))
        widths[i] = max(FIELD_MIN, widths[i] - excess)
    return widths


def _countdown(target: datetime, now: datetime) -> tuple[str, str]:
    """«9», «дней»; меньше суток — в часах."""
    left = (target - now).total_seconds()
    if left < 86400:
        n = max(1, math.ceil(left / 3600))
        return str(n), plural(n, HOURS)
    n = (msk(target).date() - msk(now).date()).days
    return str(n), plural(n, DAYS)


def _stamp(im: Image.Image, text: str, center: tuple[int, int], seed: str) -> None:
    """Резиновый штамп: двойная рамка, поворот, неровный оттиск."""
    f = font("Unbounded-ExtraBold", 34)
    tw = int(f.getlength(text))
    layer = Image.new("L", (tw + 56, 96), 0)
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle((4, 4, tw + 51, 91), radius=10, outline=255, width=5)
    d.rounded_rectangle((13, 13, tw + 42, 82), radius=5, outline=255, width=2)
    d.text(((tw + 56) / 2, 49), text, font=f, fill=255, anchor="mm")
    # непрочитанные места оттиска: случайные «проплешины» краски
    rng = random.Random(seed)
    for _ in range(260):
        x, y, r = rng.uniform(0, layer.width), rng.uniform(0, layer.height), rng.uniform(0.6, 2.6)
        d.ellipse((x - r, y - r, x + r, y + r), fill=0)
    layer = layer.point(lambda v: v * 0.86).rotate(9, resample=Image.Resampling.BICUBIC, expand=True)
    ink = Image.new("RGB", layer.size, SPOT)
    im.paste(ink, (center[0] - layer.width // 2, center[1] - layer.height // 2), layer)


def _stub(im: Image.Image, d: ImageDraw.ImageDraw, h: Hackathon, now: datetime) -> None:
    lab, val = font("JetBrainsMono-Medium", 17), font("Golos-SemiBold", 30)
    closed = bool(h.reg_deadline and h.reg_deadline <= now) or bool(h.end and h.end <= now)
    target, sub_label, sub = None, "", ""
    if closed:
        head = ("ПОСАДКА", "ЗАКОНЧИЛАСЬ")
        when = h.reg_deadline or h.end
        sub_label, sub = ("РЕГИСТРАЦИЯ ДО" if h.reg_deadline else "ФИНИШ"), _day(msk(when), now)
    elif h.reg_deadline:
        head, target = ("ПОСАДКА ЗАКАНЧИВАЕТСЯ", "ЧЕРЕЗ"), h.reg_deadline
        sub_label, sub = "РЕГИСТРАЦИЯ ДО", _day(msk(target), now)
    elif h.start and h.start > now:
        head, target = ("ВЫЛЕТ ЧЕРЕЗ", ""), h.start
        sub_label, sub = "СТАРТ", _day(msk(target), now)
    elif h.start and h.end:
        head, target = ("В ПОЛЁТЕ", "ДО ФИНИША"), h.end
        sub_label, sub = "ФИНИШ", _day(msk(target), now)
    else:
        head = ("ПОСАДКА", "")
        sub_label, sub = "ПОДРОБНОСТИ", "в анонсе" if h.source == "telegram" else "на сайте"
    text_c, accent = (MUTE, RULE) if closed else (INK, SPOT)

    d.text((STUB_X, 116), head[0], font=lab, fill=MUTE, anchor="ls")
    d.text((STUB_X, 138), head[1], font=lab, fill=MUTE, anchor="ls")
    if target:
        num, unit = _countdown(target, now)
        if (target - now).total_seconds() < 86400:
            sub += f", {msk(target):%H:%M}"
    elif not closed:
        num, unit = "?", ""
    else:
        num, unit = "", ""
    if num:
        uf = font("Golos-SemiBold", 36)
        uw = d.textlength(unit, font=uf)
        size = next((s for s in range(200, 149, -10)
                     if d.textlength(num, font=font("Unbounded-ExtraBold", s)) + 14 + uw <= STUB_W), None)
        if size:  # единица справа от числа
            nf = font("Unbounded-ExtraBold", size)
            d.text((STUB_X - 4, 352), num, font=nf, fill=accent, anchor="ls")
            d.text((STUB_X + d.textlength(num, font=nf) + 10, 352), unit, font=uf, fill=text_c, anchor="ls")
        else:  # число не помещается вместе с единицей — единица под ним
            size = next(s for s in range(200, 39, -10)
                        if d.textlength(num, font=font("Unbounded-ExtraBold", s)) <= STUB_W)
            d.text((STUB_X - 4, 318), num, font=font("Unbounded-ExtraBold", size), fill=accent, anchor="ls")
            d.text((STUB_X, 362), unit, font=uf, fill=text_c, anchor="ls")
    d.text((STUB_X, 416), sub_label, font=lab, fill=MUTE, anchor="ls")
    d.text((STUB_X, 452), _fit(d, sub, val, STUB_W), font=val, fill=text_c, anchor="ls")

    # штрихкод из хэша uid — декоративный, но у каждого события свой
    bits = hashlib.sha256(h.uid.encode()).digest()
    bits += hashlib.sha256(bits).digest()
    x = STUB_X
    for b in bits:
        w = 1 + b % 4
        if x + w > STUB_X + STUB_W:
            break
        d.rectangle((x, 500, x + w, 592), fill=MUTE if closed else INK)
        x += w + 2 + (b >> 4) % 3
    d.text((STUB_X, 614), ticket_code(h), font=font("JetBrainsMono-Medium", 15), fill=MUTE, anchor="ls")
    if closed:
        _stamp(im, "ЗАКРЫТО", (STUB_X + STUB_W // 2, 270), h.uid)


def render_ticket(h: Hackathon, now: datetime) -> bytes:
    """PNG-карточка события: название, даты, формат/приз/источник, темы и корешок с обратным отсчётом."""
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)
    mono = font("JetBrainsMono-ExtraBold", 22)
    d.rectangle((0, 0, W, 64), fill=SPOT)
    d.text((LEFT, 32), "ПОСАДОЧНЫЙ ТАЛОН · ХАКАТОН", font=mono, fill=PAPER, anchor="lm")
    d.text((STUB_X, 32), f"№ {ticket_code(h)}", font=mono, fill=PAPER, anchor="lm")
    # перфорация и вырезы по краям линии отрыва
    for y in range(76, H - 20, 18):
        d.ellipse((STUB - 5, y, STUB + 5, y + 10), fill=RULE)
    d.ellipse((STUB - 22, -22, STUB + 22, 22), fill=HOLE)
    d.ellipse((STUB - 22, H - 22, STUB + 22, H + 22), fill=HOLE)

    lab = font("JetBrainsMono-Medium", 17)
    _title(d, strip_emoji(h.title) or "Без названия")
    _route(d, h, now)
    d.line((LEFT, 470, STUB - 40, 470), fill=RULE, width=2)

    fields = _fields(h)
    val = font("Golos-SemiBold", 30)
    x = LEFT
    for (k, v), width in zip(fields, _widths(d, [v for _, v in fields], val)):
        d.text((x, 506), k, font=lab, fill=MUTE, anchor="ls")
        d.text((x, 544), _fit(d, v, val, width), font=val, fill=INK, anchor="ls")
        x += width + FIELD_GAP

    keys = topics_of(h)
    topics = labels(keys, "direction", 3) + labels(keys, "industry", 2) + labels(keys, "audience")
    tf, line = font("JetBrainsMono-ExtraBold", 20), ""
    for t in topics:
        candidate = f"{line}  ·  {t.upper()}" if line else t.upper()
        if d.textlength(candidate, font=tf) > MAIN_W:
            break
        line = candidate
    d.text((LEFT, 596), line, font=tf, fill=SPOT, anchor="ls")
    _stub(im, d, h, now)
    return png(im)
