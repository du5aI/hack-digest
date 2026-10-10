import hashlib
import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime

from hackdigest.filters import Filters
from hackdigest.models import Hackathon

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    chat_id       INTEGER PRIMARY KEY,
    interval_sec  INTEGER NOT NULL,
    next_send_at  INTEGER NOT NULL,
    sources       TEXT    NOT NULL,
    active        INTEGER NOT NULL DEFAULT 1,
    filters       TEXT    NOT NULL DEFAULT '{}',
    channels      TEXT    NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS seen (
    chat_id  INTEGER NOT NULL,
    uid      TEXT    NOT NULL,
    PRIMARY KEY (chat_id, uid)
);
-- последние известные данные о событиях: по ним открываются карточки и приходят напоминания
CREATE TABLE IF NOT EXISTS events (
    eid      TEXT PRIMARY KEY,
    data     TEXT NOT NULL,
    updated  INTEGER NOT NULL
);
-- события, за которыми следит чат; sent — какие напоминания уже отправлены
CREATE TABLE IF NOT EXISTS tracked (
    chat_id  INTEGER NOT NULL,
    eid      TEXT    NOT NULL,
    sent     TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (chat_id, eid)
);
-- порядок строк на последнем табло чата: для кнопок с номерами и голосования
CREATE TABLE IF NOT EXISTS boards (
    chat_id  INTEGER PRIMARY KEY,
    eids     TEXT NOT NULL
);
"""
# колонки, появившиеся после первой версии, — добавляем в старые базы
MIGRATIONS = {
    "filters": "ALTER TABLE chats ADD COLUMN filters TEXT NOT NULL DEFAULT '{}'",
    "channels": "ALTER TABLE chats ADD COLUMN channels TEXT NOT NULL DEFAULT ''",
}
COLUMNS = "chat_id, interval_sec, next_send_at, sources, active, filters, channels"


def _split(value: str) -> list[str]:
    return [s for s in value.split(",") if s]


def event_id(h: Hackathon) -> str:
    """Короткий стабильный id события — помещается в callback_data и deep link."""
    return hashlib.blake2s(h.uid.encode(), digest_size=5).hexdigest()


_DATES = ("start", "end", "reg_deadline")
WATCHED = ("start", "end", "reg_deadline", "online", "location")  # о каких изменениях стоит сообщить


def _dump(h: Hackathon) -> str:
    data = asdict(h)
    for f in _DATES:
        data[f] = data[f] and data[f].isoformat()
    return json.dumps(data, ensure_ascii=False)


def _load(raw: str) -> Hackathon:
    data = json.loads(raw)
    known = {f.name for f in fields(Hackathon)}
    data = {k: v for k, v in data.items() if k in known}
    for f in _DATES:
        data[f] = data.get(f) and datetime.fromisoformat(data[f])
    data["tags"] = tuple(data.get("tags", ()))
    return Hackathon(**data)


@dataclass
class Chat:
    chat_id: int
    interval_sec: int
    next_send_at: int
    sources: list[str]
    active: bool
    filters: Filters = field(default_factory=Filters)
    channels: list[str] = field(default_factory=list)


class Storage:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)
        existing = {r[1] for r in self.db.execute("PRAGMA table_info(chats)")}
        with self.db:
            for column, sql in MIGRATIONS.items():
                if column not in existing:
                    self.db.execute(sql)

    @staticmethod
    def _row(row) -> Chat:
        return Chat(row[0], row[1], row[2], _split(row[3]), bool(row[4]),
                    Filters.from_dict(json.loads(row[5] or "{}")), _split(row[6]))

    def get(self, chat_id: int) -> Chat | None:
        row = self.db.execute(f"SELECT {COLUMNS} FROM chats WHERE chat_id = ?", (chat_id,)).fetchone()
        return self._row(row) if row else None

    def subscribe(self, chat_id: int, interval_sec: int, sources: list[str], channels: list[str]) -> Chat:
        """Подписывает чат; существующие настройки сохраняются, подписка лишь включается."""
        with self.db:
            self.db.execute(
                "INSERT INTO chats (chat_id, interval_sec, next_send_at, sources, channels) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET active = 1",
                (chat_id, interval_sec, int(time.time()) + interval_sec, ",".join(sources), ",".join(channels)),
            )
        return self.get(chat_id)

    def unsubscribe(self, chat_id: int) -> None:
        with self.db:
            self.db.execute("UPDATE chats SET active = 0 WHERE chat_id = ?", (chat_id,))

    def set_interval(self, chat_id: int, interval_sec: int) -> None:
        with self.db:
            self.db.execute(
                "UPDATE chats SET interval_sec = ?, next_send_at = ? WHERE chat_id = ?",
                (interval_sec, int(time.time()) + interval_sec, chat_id),
            )

    def set_sources(self, chat_id: int, sources: list[str]) -> None:
        with self.db:
            self.db.execute("UPDATE chats SET sources = ? WHERE chat_id = ?", (",".join(sources), chat_id))

    def set_filters(self, chat_id: int, filters: Filters) -> None:
        with self.db:
            self.db.execute("UPDATE chats SET filters = ? WHERE chat_id = ?", (json.dumps(filters.to_dict()), chat_id))

    def set_channels(self, chat_id: int, channels: list[str]) -> None:
        with self.db:
            self.db.execute("UPDATE chats SET channels = ? WHERE chat_id = ?", (",".join(channels), chat_id))

    def due(self, now: int | None = None) -> list[Chat]:
        now = int(time.time()) if now is None else now
        rows = self.db.execute(
            f"SELECT {COLUMNS} FROM chats WHERE active = 1 AND next_send_at <= ?", (now,)
        ).fetchall()
        return [self._row(r) for r in rows]

    def schedule_next(self, chat: Chat, now: int | None = None) -> None:
        now = int(time.time()) if now is None else now
        with self.db:
            self.db.execute(
                "UPDATE chats SET next_send_at = ? WHERE chat_id = ?", (now + chat.interval_sec, chat.chat_id)
            )

    def unseen(self, chat_id: int, uids: list[str]) -> set[str]:
        seen = {r[0] for r in self.db.execute("SELECT uid FROM seen WHERE chat_id = ?", (chat_id,))}
        return {u for u in uids if u not in seen}

    def mark_seen(self, chat_id: int, uids: list[str]) -> None:
        with self.db:
            self.db.executemany(
                "INSERT OR IGNORE INTO seen (chat_id, uid) VALUES (?, ?)", [(chat_id, u) for u in uids]
            )

    # ---------- события, слежение, табло ----------

    def save_events(self, items: list[Hackathon]) -> list[tuple[Hackathon, Hackathon]]:
        """Запоминает события. Возвращает (было, стало) для тех, у кого сдвинулись даты или формат."""
        changed = []
        now = int(time.time())
        with self.db:
            for h in items:
                eid = event_id(h)
                row = self.db.execute("SELECT data FROM events WHERE eid = ?", (eid,)).fetchone()
                if row:
                    old = _load(row[0])
                    if any(getattr(old, f) != getattr(h, f) for f in WATCHED):
                        changed.append((old, h))
                self.db.execute("INSERT OR REPLACE INTO events (eid, data, updated) VALUES (?, ?, ?)",
                                (eid, _dump(h), now))
        return changed

    def event(self, eid: str) -> Hackathon | None:
        row = self.db.execute("SELECT data FROM events WHERE eid = ?", (eid,)).fetchone()
        return _load(row[0]) if row else None

    def track(self, chat_id: int, eid: str, on: bool = True) -> None:
        with self.db:
            if on:
                self.db.execute("INSERT OR IGNORE INTO tracked (chat_id, eid) VALUES (?, ?)", (chat_id, eid))
            else:
                self.db.execute("DELETE FROM tracked WHERE chat_id = ? AND eid = ?", (chat_id, eid))

    def is_tracked(self, chat_id: int, eid: str) -> bool:
        return self.db.execute("SELECT 1 FROM tracked WHERE chat_id = ? AND eid = ?", (chat_id, eid)).fetchone() is not None

    def tracked(self, chat_id: int | None = None) -> list[tuple[int, Hackathon, set[str]]]:
        """(чат, событие, отправленные напоминания) — для одного чата или для всех."""
        sql = "SELECT t.chat_id, e.data, t.sent FROM tracked t JOIN events e ON e.eid = t.eid"
        rows = self.db.execute(sql + " WHERE t.chat_id = ?", (chat_id,)) if chat_id is not None else self.db.execute(sql)
        return [(r[0], _load(r[1]), set(_split(r[2]))) for r in rows]

    def watchers(self, eid: str) -> list[int]:
        return [r[0] for r in self.db.execute("SELECT chat_id FROM tracked WHERE eid = ?", (eid,))]

    def mark_reminded(self, chat_id: int, eid: str, keys: set[str]) -> None:
        with self.db:
            self.db.execute("UPDATE tracked SET sent = ? WHERE chat_id = ? AND eid = ?",
                            (",".join(sorted(keys)), chat_id, eid))

    def set_board(self, chat_id: int, eids: list[str]) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO boards (chat_id, eids) VALUES (?, ?)", (chat_id, ",".join(eids)))

    def board(self, chat_id: int) -> list[str]:
        row = self.db.execute("SELECT eids FROM boards WHERE chat_id = ?", (chat_id,)).fetchone()
        return _split(row[0]) if row else []
