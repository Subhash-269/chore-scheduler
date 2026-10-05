"""
db.py - SQLite persistence for accounts and households (phase 2).

One file (server/data/chores.db by default, CHORES_DATA_DIR to move it).
Standard library only. JSON blobs hold the household config and published
schedule, exactly the shapes phase 1 stored in files; the carry-over state
stays a file per household because scheduler.load_state/save_state read
and write a path.
"""
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name        TEXT NOT NULL,
    pw_hash     TEXT NOT NULL,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tokens (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS households (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    config      TEXT,              -- Household JSON (server/main.py Household model)
    schedule    TEXT,              -- published schedule JSON
    settings    TEXT NOT NULL DEFAULT '{}',  -- member permissions etc.
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS members (
    household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role         TEXT NOT NULL CHECK (role IN ('admin', 'member')),
    roommate     TEXT,            -- which name in config.roommates this account is
    joined_at    REAL NOT NULL,
    PRIMARY KEY (household_id, user_id)
);

CREATE TABLE IF NOT EXISTS invites (
    code         TEXT PRIMARY KEY,
    household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    role         TEXT NOT NULL CHECK (role IN ('admin', 'member')),
    created_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    expires_at   REAL NOT NULL,
    used_by      INTEGER REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS statuses (
    household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    slot_id      TEXT NOT NULL,
    status       TEXT NOT NULL,    -- TaskStatus JSON
    updated_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_at   REAL NOT NULL,
    PRIMARY KEY (household_id, slot_id)
);
"""


class DB:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.path = os.path.join(data_dir, "chores.db")
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    @contextmanager
    def tx(self):
        """Serialized transaction - SQLite allows one writer anyway."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def one(self, sql, *args):
        with self._lock:
            return self._conn.execute(sql, args).fetchone()

    def all(self, sql, *args):
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    def household_dir(self, household_id):
        d = os.path.join(self.data_dir, "households", str(household_id))
        os.makedirs(d, exist_ok=True)
        return d

    def state_path(self, household_id):
        """Carry-over file for this household, same format main.py writes."""
        return os.path.join(self.household_dir(household_id), "schedule_state.json")

    def close(self):
        with self._lock:
            self._conn.close()


def now():
    return time.time()


def loads(text, default=None):
    return json.loads(text) if text else default


def dumps(value):
    return json.dumps(value, ensure_ascii=False)
