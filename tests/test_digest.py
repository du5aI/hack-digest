from datetime import datetime, timedelta, timezone

from hackdigest.digest import TG_LIMIT, build_digest, fmt_range, format_interval, parse_interval, select
from hackdigest.filters import Filters

WORLD = Filters(region="world")
from hackdigest.models import Hackathon

NOW = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)


def make(i: int, days: int = 3, source: str = "devpost", **kw) -> Hackathon:
    start = NOW + timedelta(days=days)
    return Hackathon(uid=f"{source}:{i}", source=source, title=f"Hack <{i}>", url=f"https://x/{i}",
                     start=start, end=start + timedelta(days=2), prize="$1,000", tags=("AI",), **kw)


def test_parse_interval():
    assert parse_interval("12h") == 12 * 3600
    assert parse_interval("3d") == 3 * 86400
    assert parse_interval("2 дня") == 2 * 86400
    assert parse_interval(" 1 неделя ") == 7 * 86400
    assert parse_interval("30m") is None
    assert parse_interval("abc") is None


def test_format_interval():
    assert format_interval(7 * 86400) == "неделю"
    assert format_interval(3 * 86400) == "3 дня"
    assert format_interval(12 * 3600) == "12 часов"
    assert format_interval(21 * 3600) == "21 час"


def test_fmt_range():
    d = datetime(2026, 10, 12, tzinfo=timezone.utc)
    assert fmt_range(d, d + timedelta(days=3), NOW) == "12–15 окт"
    assert fmt_range(d, datetime(2026, 11, 2, tzinfo=timezone.utc), NOW) == "12 окт – 2 ноя"
    assert fmt_range(d, d, NOW) == "12 окт"
    assert fmt_range(datetime(2027, 1, 5, tzinfo=timezone.utc), None, NOW) == "5 янв 2027"


def test_digest_layout():
    items = [make(1, days=2), make(2, days=20), make(3, days=60), make(4, days=-3, reg_deadline=NOW + timedelta(days=2))]
    msgs = build_digest(select(items, WORLD, NOW), {"devpost:2"}, NOW, ["devpost"])
    text = "\n".join(msgs)
    assert "Ближайшие 7 дней · 1" in text
    assert "В ближайший месяц · 1" in text
    assert "<blockquote expandable>" in text  # «Позже» и «Уже идут» свёрнуты
    assert '<a href="https://x/2"><b>Hack &lt;2&gt;</b></a> <i>— новое</i>' in text
    assert "/filter" in text
    assert "регистрация до 11 окт" in text
    assert '<a href="https://devpost.com/hackathons">Devpost</a>' in text
    # без эмодзи
    assert all(ord(ch) < 0x2190 or ch in "–—…·«»" for ch in text)


def test_digest_splits_long():
    items = [make(i, days=1 + i % 5) for i in range(200)]
    msgs = build_digest(items, set(), NOW, ["devpost"], limit=200)
    assert len(msgs) > 1
    assert all(len(m) <= TG_LIMIT for m in msgs)
    short = build_digest(items, set(), NOW, ["devpost"], limit=10)
    assert len(short) == 1 and "и ещё 190" in short[0]


def test_select_filters_and_dedup():
    items = [make(1, online=True), make(2, online=False), make(3, source="mlh", online=True),
             make(5, days=-5)]  # уже прошло
    items[2] = Hackathon(**{**items[2].__dict__, "title": "Hack <1>"})  # дубль по названию
    assert [h.uid for h in select(items, WORLD, NOW)] == ["devpost:1", "devpost:2"]
    assert [h.uid for h in select(items, Filters(region="world", format="offline"), NOW)] == ["devpost:2"]
    assert select(items, Filters(region="world", topics=["web"]), NOW) == []
    assert len(select(items, Filters(region="world", topics=["ai"]), NOW)) == 2
    assert select([make(9, days=40)], Filters(region="world", period_days=30), NOW) == []


def test_region_filter():
    ru_offline = make(1, source="codenrock", online=False)
    intl_online = make(2, source="devpost", online=True)
    intl_offline = make(3, source="mlh", online=False)
    items = [ru_offline, intl_online, intl_offline]
    uids = lambda f: [h.uid for h in select(items, f, NOW)]  # noqa: E731
    assert uids(Filters()) == ["codenrock:1", "devpost:2"]  # по умолчанию: Россия + онлайн в мире
    assert uids(Filters(region="ru")) == ["codenrock:1"]
    assert uids(Filters(region="world")) == ["codenrock:1", "devpost:2", "mlh:3"]


def test_digest_empty():
    assert build_digest([], set(), NOW, ["devpost"]) == []


def test_cross_source_dedup():
    site = make(1, source="codenrock")
    site = Hackathon(**{**site.__dict__, "title": "SOLARCTF 2026"})
    other = Hackathon(**{**make(2, source="hackathons_rus").__dict__, "title": "SolarCTF"})
    post_dup = Hackathon(uid="telegram:c/1", source="telegram", title="Регистрация на SolarCTF открыта",
                         url="https://t.me/c/1", via="Канал")
    post_new = Hackathon(uid="telegram:c/2", source="telegram", title="Хакатон «Код города»",
                         url="https://t.me/c/2", via="Канал")
    longer = Hackathon(**{**make(3, source="mlh").__dict__, "title": "SolarCTF 2026 Autumn Edition"})
    quoted = Hackathon(**{**make(4, source="hackathons_rus").__dict__, "title": "Продуктовый хакатон «Точка сборки»"})
    post_quoted = Hackathon(uid="telegram:c/3", source="telegram", title="Создай решение для М.Видео",
                            summary="На ИИ-хакатоне «Точка сборки» тебя ждут кейсы", url="u", via="Канал")
    repost = Hackathon(**{**post_new.__dict__, "uid": "telegram:d/9"})
    got = select([site, other, longer, quoted, post_dup, post_new, post_quoted, repost], WORLD, NOW)
    assert [h.uid for h in got] == ["codenrock:1", "hackathons_rus:4", "telegram:c/2"]


def test_deadline_only_goes_by_deadline():
    h = Hackathon(uid="hackathons_rus:x", source="hackathons_rus", title="РуКод", url="u",
                  reg_deadline=NOW + timedelta(days=3))
    text = "\n".join(build_digest(select([h], Filters(), NOW), set(), NOW, ["hackathons_rus"]))
    assert "Ближайшие 7 дней · 1" in text and "регистрация до 12 окт" in text


def test_emoji_stripped_from_titles():
    h = Hackathon(**{**make(1).__dict__, "title": "Arkiv: Global Tour Stop 🌍 ⚡️"})
    text = build_digest([h], set(), NOW, ["devpost"])[0]
    assert "<b>Arkiv: Global Tour Stop</b>" in text
