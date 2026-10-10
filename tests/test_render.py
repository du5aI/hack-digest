import io
from datetime import datetime, timedelta, timezone

from PIL import Image

from hackdigest.models import Hackathon
from hackdigest.render import render_board, render_board_gif, render_ticket
from hackdigest.render.board import W, city_code, short_title
from hackdigest.render.ticket import _countdown, ticket_code

NOW = datetime(2026, 10, 10, 9, tzinfo=timezone.utc)


def make(i: int, days: float = 3, source: str = "codenrock", **kw) -> Hackathon:
    start = NOW + timedelta(days=days)
    kw = {"start": start, "end": start + timedelta(days=2), "reg_deadline": start - timedelta(days=1),
          "title": f"Хакатон «Тест {i}» 2026", **kw}
    return Hackathon(uid=f"{source}:{i}", source=source, url=f"https://x/{i}", **kw)


def _open(data: bytes, fmt: str) -> Image.Image:
    im = Image.open(io.BytesIO(data))
    assert im.format == fmt
    return im


def test_city_code():
    assert city_code(Hackathon(uid="a:1", source="a", title="", url="", online=True, location="Москва")) == "ОНЛ"
    assert city_code(Hackathon(uid="a:1", source="a", title="", url="", location="Санкт-Петербург")) == "СПБ"
    assert city_code(Hackathon(uid="a:1", source="a", title="", url="", location="Иннополис")) == "ИНП"
    assert city_code(Hackathon(uid="a:1", source="a", title="", url="", location="Toronto, Ontario")) == "TOR"
    assert city_code(Hackathon(uid="a:1", source="a", title="", url="", location="Звенигородка")) == "ЗВЕ"
    assert city_code(Hackathon(uid="a:1", source="a", title="", url="")) == "—"


def test_short_title():
    assert short_title("Альфа-Будущее Хакатон") == "АЛЬФА-БУДУЩЕЕ"
    assert short_title("1С-хакатон «ПроТехно»") == "1С ПРОТЕХНО"
    assert short_title("ARCTF 2026 🚀") == "ARCTF"
    assert short_title("EvoHacks2026") == "EVOHACKS"
    assert short_title("Генерация идей (Хакатон)") == "ГЕНЕРАЦИЯ ИДЕЙ"
    # длинное — по границе слова, а если есть имя в кавычках — берётся оно
    assert short_title("SechenovTech – 10сезон / Выездной хакатон в Звенигород #АП") == "SECHENOVTECH"
    assert short_title("Хакатон «ПриморТех» по разработке ПО для морской робототехники") == "ПРИМОРТЕХ"
    assert all(len(short_title(t)) <= 19 for t in ("Очень длинное название без кавычек вообще", "Суперкалифраджилистик"))


def test_board_png_and_gif():
    items = [make(i, days=i) for i in range(1, 15)]
    data = render_board(items, {"codenrock:1"}, NOW)
    im = _open(data, "PNG")
    assert im.width == W and 1000 < im.height < 1800

    gif = render_board_gif(items, {"codenrock:1"}, NOW)
    im = _open(gif, "GIF")
    assert im.size == (W, _open(data, "PNG").height) and W >= 2000  # крупный исходник — чёткий в Telegram
    assert len(gif) < 3_000_000
    durations = []
    for i in range(im.n_frames):
        im.seek(i)
        durations.append(im.info["duration"])
    assert durations[-1] >= 4000 and 1500 <= sum(durations[:-1]) <= 2500
    assert im.info.get("loop") == 0


def test_board_skips_undated_and_empty():
    post = Hackathon(uid="telegram:1", source="telegram", title="Анонс", url="u", via="Канал")
    assert render_board([], set(), NOW) is None
    assert render_board([post], set(), NOW) is None
    assert render_board_gif([post], set(), NOW) is None
    # только дедлайн — тоже дата
    assert render_board([post, make(1, start=None, end=None)], set(), NOW)


def test_tickets():
    cases = [
        make(1),
        make(2, title="42. Вызовы будущего 2.0 – Хакатон «Особенности построения воронки продаж для сегментов: "
                     "B2B, B2C, B2G» и ещё очень много слов, которые не влезут даже в три строки", prize="3 000 000 ₽"),
        make(3, reg_deadline=NOW - timedelta(days=1)),  # регистрация закрыта
        make(4, reg_deadline=NOW + timedelta(hours=5)),  # меньше суток
        make(5, end=None, reg_deadline=None, online=True),  # только старт
        make(6, start=None, end=None),  # только дедлайн
        make(7, source="telegram", start=None, end=None, reg_deadline=None, via="хакатоны.рус / ctf"),  # без дат
        make(8, source="telegram", start=None, end=None, reg_deadline=None, dates_text="15–17 ноября", prize="₹ 15,000"),
        make(9, days=-1, reg_deadline=None),  # уже идёт
    ]
    for h in cases:
        im = _open(render_ticket(h, NOW), "PNG")
        assert im.size == (1280, 640)


def test_ticket_helpers():
    h = make(1)
    assert ticket_code(h) == ticket_code(make(1)) and ticket_code(h).startswith("CNR-")
    assert _countdown(NOW + timedelta(days=2, hours=1), NOW) == ("2", "дня")
    assert _countdown(NOW + timedelta(days=5), NOW) == ("5", "дней")
    assert _countdown(NOW + timedelta(hours=1, minutes=30), NOW) == ("2", "часа")
