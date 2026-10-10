import asyncio
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.types import User

from hackdigest import bot as hb
from hackdigest.export import event_json, snapshot
from hackdigest.models import Hackathon
from hackdigest.storage import Storage

NOW = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
URL = "https://example.github.io/hack-digest/"


def make(i: int, **kw) -> Hackathon:
    base = dict(uid=f"codenrock:{i}", source="codenrock", title=f"Хакатон {i} 🚀", url=f"https://x/{i}",
                start=NOW + timedelta(days=5 + i), end=NOW + timedelta(days=7 + i),
                reg_deadline=NOW + timedelta(days=2 + i), description="Нейросети для медицины и клиник, ИИ")
    return Hackathon(**{**base, **kw})


def test_event_json_is_clean():
    e = event_json(make(1))
    assert e["title"] == "Хакатон 1"  # без эмодзи
    assert e["deadline"].endswith("+00:00") and e["ru"] is True
    assert "ai" in e["topics"] and e["code"].startswith("CNR-")
    data = snapshot([make(1)], NOW, ["devpost"])
    assert data["failed"] == ["Devpost"] and data["topics"]["ai"]["group"] == "direction"


def test_app_caption_and_keyboard():
    items = [make(0), make(5)]
    assert hb.app_caption(items, NOW) == "<b>Табло на 10 октября</b> · 2 рейса, горят 1"
    private = hb.app_keyboard(URL, group=False).inline_keyboard[0][0]
    assert private.web_app.url == URL and private.url is None
    assert hb.app_keyboard(URL, group=True).inline_keyboard[0][0].url == URL  # в группах — обычная ссылка


class FakeBot(Bot):
    def __init__(self):
        super().__init__("42:TEST")
        self.out = []

    async def __call__(self, method, request_timeout=None):
        if type(method).__name__ == "GetMe":
            return User(id=42, is_bot=True, first_name="b", username="b")
        self.out.append(method)
        return True


def test_digest_in_webapp_mode_is_one_message(monkeypatch):
    items = [make(i) for i in range(3)]

    async def fake_collect(chat, db):
        return NOW, items, set(), [], []

    monkeypatch.setattr(hb, "collect", fake_collect)
    monkeypatch.setattr(hb, "render_board_gif", lambda *a, **k: b"GIF")
    db = Storage(":memory:")
    chat = db.subscribe(1, 3600, ["codenrock"], [])
    bot = FakeBot()
    asyncio.run(hb.send_digest(bot, db, chat, 6, webapp_url=URL))
    kinds = [type(m).__name__ for m in bot.out]
    assert kinds == ["SendAnimation"]  # табло — и никаких текстовых сообщений
    assert bot.out[0].reply_markup.inline_keyboard[0][0].web_app.url == URL
    assert db.unseen(1, [h.uid for h in items]) == set()  # показанные отмечены
