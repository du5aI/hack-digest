from hackdigest.storage import Storage


def test_subscription_flow():
    db = Storage(":memory:")
    chat = db.subscribe(1, 3600, ["devpost"])
    assert chat.active and chat.sources == ["devpost"]
    assert db.due() == []
    assert [c.chat_id for c in db.due(now=chat.next_send_at)] == [1]

    db.set_interval(1, 7200)
    db.set_sources(1, ["devpost", "codenrock"])
    db.unsubscribe(1)
    assert db.due(now=10**12) == []
    # повторная подписка сохраняет настройки
    chat = db.subscribe(1, 3600, ["devpost"])
    assert chat.interval_sec == 7200 and chat.sources == ["devpost", "codenrock"]


def test_seen():
    db = Storage(":memory:")
    db.mark_seen(1, ["a", "b"])
    assert db.unseen(1, ["a", "b", "c"]) == {"c"}
    assert db.unseen(2, ["a"]) == {"a"}
