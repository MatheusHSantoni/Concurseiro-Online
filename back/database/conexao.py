import sqlite3
from pathlib import Path
from flask import g

DB_PATH = Path(__file__).resolve().parents[2] / 'instance' / 'concurseiroonline.sqlite3'


def get_db():
    if 'db' not in g:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        g.db = db
    return g.db


def close_db(_=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


