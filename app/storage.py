"""One SQLite writer; every account operation takes a verified owner, never a client user ID."""

import json
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException


def timestamp():
    return datetime.now(UTC).isoformat()


class Storage:
    def __init__(self, path):
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            PRAGMA busy_timeout=5000;
            CREATE TABLE IF NOT EXISTS threads(id TEXT PRIMARY KEY, owner TEXT NOT NULL, created TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS threads_owner ON threads(owner);
            CREATE TABLE IF NOT EXISTS turns(
                owner TEXT NOT NULL, request_id TEXT NOT NULL, thread_id TEXT NOT NULL,
                input TEXT NOT NULL, output TEXT, status TEXT NOT NULL, created TEXT NOT NULL,
                fingerprint TEXT NOT NULL, PRIMARY KEY(owner,request_id),
                FOREIGN KEY(thread_id) REFERENCES threads(id));
            CREATE TABLE IF NOT EXISTS turn_metadata(
                owner TEXT NOT NULL, request_id TEXT NOT NULL, message_id TEXT NOT NULL,
                requested_context TEXT, updated TEXT NOT NULL, PRIMARY KEY(owner,request_id));
            CREATE TABLE IF NOT EXISTS memories(
                owner TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, updated TEXT NOT NULL,
                PRIMARY KEY(owner,key));
        """)
        # An interrupted turn remains inspectable, and is never automatically run again.
        self.db.execute("UPDATE turns SET status='failed' WHERE status='pending'")

    def owned(self, owner, thread_id):
        row = self.db.execute("SELECT * FROM threads WHERE owner=? AND id=?", (owner, thread_id)).fetchone()
        if not row:
            raise HTTPException(404, "Conversation not found")
        return dict(row)

    def resolve(self, owner, requested=None):
        if requested:
            return self.owned(owner, requested)["id"]
        thread = str(uuid4())
        self.db.execute("INSERT INTO threads VALUES(?,?,?)", (thread, owner, timestamp()))
        return thread

    def request(self, owner, request_id):
        row = self.db.execute(
            "SELECT * FROM turns WHERE owner=? AND request_id=?", (owner, request_id)
        ).fetchone()
        return dict(row) if row else None

    def start(self, owner, request_id, thread, text, message_id, requested_context, fingerprint):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute(
                "INSERT INTO turns VALUES(?,?,?,?,NULL,'pending',?,?)",
                (owner, request_id, thread, text, timestamp(), fingerprint),
            )
            self.db.execute(
                "INSERT INTO turn_metadata VALUES(?,?,?,?,?)",
                (owner, request_id, message_id, requested_context, timestamp()),
            )
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def finish(self, owner, request_id, output=None):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute(
                "UPDATE turns SET output=?,status=? WHERE owner=? AND request_id=?",
                (output, "complete" if output is not None else "failed", owner, request_id),
            )
            self.db.execute(
                "UPDATE turn_metadata SET updated=? WHERE owner=? AND request_id=?",
                (timestamp(), owner, request_id),
            )
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def remember(self, owner, key, value):
        if not key.strip() or len(key) > 80 or not value.strip() or len(value) > 1000:
            raise ValueError("Memory keys must be 1–80 characters; values 1–1000 characters")
        self.db.execute(
            "INSERT INTO memories VALUES(?,?,?,?) ON CONFLICT(owner,key) DO UPDATE SET value=excluded.value,updated=excluded.updated",
            (owner, key, value, timestamp()),
        )
        return "Saved."

    def forget(self, owner, key):
        self.db.execute("DELETE FROM memories WHERE owner=? AND key=?", (owner, key))
        return "Forgotten."

    def memory_page(self, owner, query="", offset=0):
        offset = max(0, offset)
        rows = [
            dict(row)
            for row in self.db.execute(
                "SELECT key,value,updated FROM memories WHERE owner=? AND (instr(lower(key),lower(?))>0 OR instr(lower(value),lower(?))>0) ORDER BY key LIMIT 51 OFFSET ?",
                (owner, query[:200], query[:200], offset),
            )
        ]
        return {"items": rows[:50], "next_offset": offset + 50 if len(rows) > 50 else None}

    def context(self, owner, max_chars=12000):
        items, size = [], 2
        for row in self.db.execute(
            "SELECT key,value FROM memories WHERE owner=? ORDER BY updated DESC,key", (owner,)
        ):
            item = dict(row)
            length = len(json.dumps(item, ensure_ascii=False)) + 2
            if size + length > max_chars:
                break
            items.append(item)
            size += length
        return json.dumps(items, ensure_ascii=False)
