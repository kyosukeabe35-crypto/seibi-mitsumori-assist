"""Vercel(Python Serverless Functions)向けのエントリポイント。

app/ 以下はフラットなモジュール構成(db.py, matching.py 等を素朴に import する)
になっているため、app/ を sys.path に追加してから読み込む。
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("VERCEL", "1")

APP_DIR = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_DIR))

from app import app  # noqa: E402
