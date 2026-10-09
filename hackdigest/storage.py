import sqlite3
import time
from dataclasses import dataclass

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    chat_id       INTEGER PRIMARY KEY,
    interval_sec  INTEGER NOT NULL,
    next_send_at  INTEGER NOT NULL,
    sources       TEXT    NOT NULL,
    active        INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS seen (
    chat_id  INTEGER NOT NULL,
    uid      TEXT    NOT NULL,
    PRIMARY KEY (chat_id, uid)
);
"""


@dataclass
class Chat:
    chat_id: int
    interval_sec: int
    next_send_at: int
    sources: list[str]
    active: bool


class Storage:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    @staticmethod
    def _row(row) -> Chat:
        return Chat(row[0], row[1], row[2], [s for s in row[3].split(",") if s], bool(row[4]))

    def get(self, chat_id: int) -> Chat | None:
        row = self.db.execute(
            "SELECT chat_id, interval_sec, next_send_at, sources, active FROM chats WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
        return self._row(row) if row else None

    def subscribe(self, chat_id: int, interval_sec: int, sources: list[str]) -> Chat:
        """Подписывает чат; существующие настройки сохраняются, подписка лишь включается."""
        with self.db:
            self.db.execute(
                "INSERT INTO chats (chat_id, interval_sec, next_send_at, sources) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET active = 1",
                (chat_id, interval_sec, int(time.time()) + interval_sec, ",".join(sources)),
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

    def due(self, now: int | None = None) -> list[Chat]:
        now = int(time.time()) if now is None else now
        rows = self.db.execute(
            "SELECT chat_id, interval_sec, next_send_at, sources, active FROM chats "
            "WHERE active = 1 AND next_send_at <= ?",
            (now,),
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
