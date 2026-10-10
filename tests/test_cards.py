from datetime import datetime, timedelta, timezone

from hackdigest.cards import caption, change_notice, due_reminder, ics
from hackdigest.models import Hackathon
from hackdigest.storage import Storage, event_id

NOW = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)


def make(**kw) -> Hackathon:
    base = dict(uid="devpost:1", source="devpost", title="Hack & <Co>", url="https://x/1",
                start=NOW + timedelta(days=10), end=NOW + timedelta(days=12), reg_deadline=NOW + timedelta(days=5),
                online=True, prize="$1,000", organizer="Acme", participants=1234,
                description="Build AI agents for healthcare. Second sentence.")
    return Hackathon(**{**base, **kw})


def test_caption():
    text = caption(make(), NOW, tracked=True)
    assert "Hack &amp; &lt;Co&gt;" in text
    assert "Регистрация до 14 окт</b> — закроется через 5 дней" in text
    assert "организатор: Acme" in text and "1 234 участника" in text
    assert "вы следите" in text and len(text) <= 1024


def test_reminders_pick_latest_only():
    h = make(reg_deadline=NOW + timedelta(hours=20))
    sent, text = due_reminder(h, set(), NOW)
    assert sent == {"reg1", "reg3"} and "через 20 часов" in text
    assert due_reminder(h, sent, NOW) is None
    sent, _ = due_reminder(make(reg_deadline=NOW + timedelta(days=2)), set(), NOW)
    assert sent == {"reg3"}
    sent, text = due_reminder(make(reg_deadline=None, start=NOW + timedelta(hours=10)), set(), NOW)
    assert sent == {"start"} and "начинается" in text
    assert due_reminder(make(), set(), NOW) is None  # до дедлайна ещё 5 дней


def test_change_notice():
    old = make()
    assert change_notice(old, old, NOW) is None
    moved = make(reg_deadline=NOW + timedelta(days=8), online=False, location="Казань")
    text = change_notice(old, moved, NOW)
    assert "14 окт → 17 окт" in text and "теперь очно, Казань" in text


def test_ics():
    body = ics([make(), make(uid="tg:2", start=None, end=None)], NOW).decode()
    assert body.count("BEGIN:VEVENT") == 2 and "VALARM" in body
    assert "SUMMARY:Hack & <Co>" in body and "Дедлайн регистрации" in body
    assert "DTSTART;TZID=Europe/Moscow:20261019T150000" in body


def test_storage_events_and_tracking():
    db = Storage(":memory:")
    h = make()
    eid = event_id(h)
    assert db.save_events([h]) == []
    assert db.event(eid) == h
    moved = make(reg_deadline=NOW + timedelta(days=7))
    [(old, new)] = db.save_events([moved])
    assert old == h and new == moved
    db.track(1, eid)
    assert db.is_tracked(1, eid) and db.watchers(eid) == [1]
    db.mark_reminded(1, eid, {"reg3"})
    [(chat, ev, sent)] = db.tracked()
    assert chat == 1 and ev == moved and sent == {"reg3"}
    db.track(1, eid, on=False)
    assert db.tracked(1) == []
    db.set_board(5, ["a", "b"])
    assert db.board(5) == ["a", "b"]
