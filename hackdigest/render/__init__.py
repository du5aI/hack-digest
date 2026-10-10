"""Картинки для Telegram на Pillow: табло ближайших хакатонов и «посадочный талон» события."""
import io
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageFont

FONTS = Path(__file__).resolve().parent.parent / "fonts"
MSK = ZoneInfo("Europe/Moscow")


@lru_cache(maxsize=64)
def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / f"{name}.ttf"), size)


def msk(d: datetime) -> datetime:
    """Дата в московском времени (все даты на картинках — по Москве)."""
    return d.astimezone(MSK)


def png(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


from hackdigest.render.board import render_board, render_board_gif  # noqa: E402
from hackdigest.render.ticket import render_ticket  # noqa: E402

__all__ = ["render_board", "render_board_gif", "render_ticket"]
