"""SQLite storage for customer messages and their reply threads."""
import os
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timezone

STATUSES = ("new", "replied", "closed")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  email TEXT NOT NULL DEFAULT '',
  phone TEXT NOT NULL DEFAULT '',
  topic TEXT NOT NULL DEFAULT '',
  body TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'new',
  token TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS replies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id INTEGER NOT NULL,
  author TEXT NOT NULL,            -- staff | customer
  body TEXT NOT NULL,
  delivery TEXT NOT NULL DEFAULT '', -- sent | outbox | failed | no_email (staff replies only)
  error TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_replies_message ON replies(message_id);
CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(status);
"""


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def split_contact(contact):
    """The contact field accepts an email or a phone number."""
    contact = (contact or "").strip()
    if EMAIL_RE.match(contact):
        return contact.lower(), ""
    digits = re.sub(r"[^\d+]", "", contact)
    return "", digits


class Store:
    def __init__(self, data_dir):
        os.makedirs(data_dir, exist_ok=True)
        self.path = os.path.join(data_dir, "messages.db")
        self.lock = threading.Lock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self.lock:
            self.db.executescript(SCHEMA)

    def close(self):
        with self.lock:
            self.db.close()

    def _one(self, sql, args=()):
        row = self.db.execute(sql, args).fetchone()
        return dict(row) if row else None

    # ---- messages
    def create_message(self, name, contact, topic, body):
        email, phone = split_contact(contact)
        ts = now()
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO messages (name, email, phone, topic, body, status, token, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (name, email, phone, topic, body, "new", secrets.token_urlsafe(24), ts, ts))
            self.db.commit()
            return cur.lastrowid

    def list_messages(self):
        rows = self.db.execute("""
          SELECT m.id, m.name, m.email, m.phone, m.topic, m.body, m.status, m.created_at, m.updated_at,
                 (SELECT COUNT(*) FROM replies r WHERE r.message_id = m.id) AS reply_count
          FROM messages m ORDER BY m.updated_at DESC, m.id DESC""").fetchall()
        return [dict(r) for r in rows]

    def get_message(self, message_id):
        return self._one("SELECT * FROM messages WHERE id = ?", (message_id,))

    def get_by_token(self, token):
        return self._one("SELECT * FROM messages WHERE token = ?", (token,))

    def set_status(self, message_id, status):
        if status not in STATUSES:
            raise ValueError(status)
        with self.lock:
            self.db.execute("UPDATE messages SET status = ?, updated_at = ? WHERE id = ?", (status, now(), message_id))
            self.db.commit()

    # ---- replies
    def replies(self, message_id):
        rows = self.db.execute("SELECT id, author, body, delivery, error, created_at FROM replies WHERE message_id = ? ORDER BY id", (message_id,)).fetchall()
        return [dict(r) for r in rows]

    def add_reply(self, message_id, author, body, delivery="", error=""):
        ts = now()
        # A staff reply answers the message; a customer reply puts it back in the unanswered queue.
        status = "replied" if author == "staff" else "new"
        with self.lock:
            cur = self.db.execute("INSERT INTO replies (message_id, author, body, delivery, error, created_at) VALUES (?,?,?,?,?,?)",
                                  (message_id, author, body, delivery, error, ts))
            self.db.execute("UPDATE messages SET status = ?, updated_at = ? WHERE id = ?", (status, ts, message_id))
            self.db.commit()
            return self._one("SELECT id, author, body, delivery, error, created_at FROM replies WHERE id = ?", (cur.lastrowid,))

    def update_delivery(self, reply_id, delivery, error=""):
        with self.lock:
            self.db.execute("UPDATE replies SET delivery = ?, error = ? WHERE id = ?", (delivery, error, reply_id))
            self.db.commit()
