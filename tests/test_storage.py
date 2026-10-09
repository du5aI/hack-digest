import sqlite3

from hackdigest.filters import Filters
from hackdigest.storage import Storage


def test_subscription_flow():
    db = Storage(":memory:")
    chat = db.subscribe(1, 3600, ["devpost"], ["itmo"])
    assert chat.active and chat.sources == ["devpost"] and chat.channels == ["itmo"]
    assert db.due() == []
    assert [c.chat_id for c in db.due(now=chat.next_send_at)] == [1]

    db.set_interval(1, 7200)
    db.set_sources(1, ["devpost", "codenrock"])
    db.set_filters(1, Filters(format="online", topics=["ai"], period_days=30))
    db.set_channels(1, ["a_chan", "b_chan"])
    db.unsubscribe(1)
    assert db.due(now=10**12) == []
    chat = db.subscribe(1, 3600, ["devpost"], [])  # повторная подписка сохраняет настройки
    assert chat.interval_sec == 7200 and chat.sources == ["devpost", "codenrock"]
    assert chat.filters == Filters(format="online", topics=["ai"], period_days=30)
    assert chat.channels == ["a_chan", "b_chan"]


def test_migrates_old_db(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("CREATE TABLE chats (chat_id INTEGER PRIMARY KEY, interval_sec INTEGER NOT NULL, "
                      "next_send_at INTEGER NOT NULL, sources TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);"
                      "INSERT INTO chats VALUES (5, 60, 0, 'devpost', 1);")
    old.commit()
    old.close()
    chat = Storage(str(path)).get(5)
    assert chat.sources == ["devpost"] and chat.filters.is_empty() and chat.channels == []


def test_seen():
    db = Storage(":memory:")
    db.mark_seen(1, ["a", "b"])
    assert db.unseen(1, ["a", "b", "c"]) == {"c"}
    assert db.unseen(2, ["a"]) == {"a"}
