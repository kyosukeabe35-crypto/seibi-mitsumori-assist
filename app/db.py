import os
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

# Vercel等のサーバーレス環境ではプロジェクトディレクトリが読み取り専用で、
# 書き込みできるのは /tmp のみ。この場合はデータが実行インスタンスの寿命
# 分しか保持されない(デモ・提出用の一時公開を想定。実運用はローカル版を使う)。
if os.environ.get("VERCEL"):
    DATA_DIR = Path("/tmp/data")
else:
    DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "app.db"

DEFAULT_SETTINGS = {
    "company_name": "",
    "company_address": "",
    "company_tel": "",
    "company_email": "",
    "tax_rate": "0.10",
    "default_validity_days": "30",
    "estimate_prefix": "EST",
}


def get_conn():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        conn.executescript(f.read())
    cur = conn.cursor()
    for k, v in DEFAULT_SETTINGS.items():
        cur.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v)
        )
    conn.commit()
    conn.close()


def ensure_initialized():
    """DBファイルが無ければ作成する。新規作成したかどうかを返す。"""
    is_new = not DB_PATH.exists()
    if is_new:
        init_db()
    return is_new


def get_settings():
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    d = dict(DEFAULT_SETTINGS)
    d.update({r["key"]: r["value"] for r in rows})
    return d


def set_settings(values: dict):
    conn = get_conn()
    cur = conn.cursor()
    for k, v in values.items():
        cur.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (k, v),
        )
    conn.commit()
    conn.close()
