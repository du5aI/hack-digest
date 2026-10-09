from hackdigest.digest import TG_LIMIT, build_digest, format_interval, parse_interval
from hackdigest.models import Hackathon


def make(i: int, source: str = "devpost") -> Hackathon:
    return Hackathon(uid=f"{source}:{i}", source=source, title=f"Hack <{i}>", url=f"https://x/{i}",
                     dates="Oct 10, 2026", prize="$1,000", tags=("AI",))


def test_parse_interval():
    assert parse_interval("12h") == 12 * 3600
    assert parse_interval("3d") == 3 * 86400
    assert parse_interval("1w") == 7 * 86400
    assert parse_interval("2 дня") == 2 * 86400
    assert parse_interval(" 1 неделя ") == 7 * 86400
    assert parse_interval("30m") is None  # меньше часа
    assert parse_interval("abc") is None
    assert parse_interval("") is None


def test_format_interval():
    assert format_interval(7 * 86400) == "неделю"
    assert format_interval(3 * 86400) == "3 дня"
    assert format_interval(12 * 3600) == "12 часов"
    assert format_interval(21 * 3600) == "21 час"
    assert format_interval(90 * 60) == "90 минут"


def test_digest_marks_new_and_escapes():
    msgs = build_digest({"devpost": [make(1), make(2)]}, new_uids={"devpost:2"})
    assert len(msgs) == 1
    assert "• <a href=\"https://x/1\">Hack &lt;1&gt;</a>" in msgs[0]
    assert "🆕 <a href=\"https://x/2\">" in msgs[0]


def test_digest_limits_and_splits():
    items = [make(i) for i in range(400)]
    msgs = build_digest({"devpost": items}, new_uids=set(), per_source=400)
    assert len(msgs) > 1
    assert all(len(m) <= TG_LIMIT for m in msgs)
    # элемент не отрывается от строки с деталями
    assert all(not m.startswith("    ") for m in msgs)
    short = build_digest({"devpost": items}, new_uids=set(), per_source=5)
    assert "…и ещё 395" in short[0]


def test_digest_empty():
    assert build_digest({"devpost": []}, new_uids=set()) == []
