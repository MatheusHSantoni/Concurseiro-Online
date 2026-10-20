import sqlite3
from pathlib import Path
from flask import g

DB_PATH = Path(__file__).resolve().parent / 'instance' / 'concurseiroonline.sqlite3'


def get_db():
    if 'db' not in g:
        DB_PATH.parent.mkdir(exist_ok=True)
        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        g.db = db
    return g.db


def close_db(_=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript('''
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL,
      is_admin INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS questions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      exam TEXT NOT NULL DEFAULT 'PRF',
      year INTEGER,
      number INTEGER,
      subject TEXT NOT NULL DEFAULT 'Não classificada',
      statement TEXT NOT NULL,
      answer TEXT CHECK(answer IN ('C', 'E', 'A') OR answer IS NULL),
      source TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'published')),
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS attempts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL REFERENCES users(id),
      question_id INTEGER NOT NULL REFERENCES questions(id),
      answer TEXT NOT NULL CHECK(answer IN ('C', 'E', 'B')),
      correct INTEGER NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_attempt_user_date ON attempts(user_id, created_at);
    CREATE INDEX IF NOT EXISTS idx_questions_status_subject ON questions(status, subject);
    ''')
    db.commit()
