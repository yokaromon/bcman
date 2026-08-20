"""
logger.py — SQLite ベースのログモジュール（コア）

依存: Python 標準ライブラリのみ（sqlite3, sys, threading, datetime）
他プロジェクトへの移植: このファイル単体をコピーするだけで使用可能
"""

import sqlite3
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_lock = threading.Lock()
_db_path: Optional[Path] = None

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL,
    source      TEXT    NOT NULL,
    client_id   TEXT,
    seq_no      INTEGER,
    from_node   TEXT,
    to_node     TEXT,
    source_file TEXT,
    line_no     INTEGER,
    message     TEXT    NOT NULL
)
"""

_INSERT = """
INSERT INTO logs (timestamp, source, client_id, seq_no, from_node, to_node, source_file, line_no, message)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def init(db_path: str | Path) -> None:
    """ログモジュールを初期化する。アプリ起動時に一度だけ呼ぶ。"""
    global _db_path
    _db_path = Path(db_path)
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    _setup()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _setup() -> None:
    with _lock:
        conn = _connect()
        conn.execute(_CREATE_TABLE)
        # 既存DBに line_no カラムがなければ追加（後方互換）
        cols = {row[1] for row in conn.execute("PRAGMA table_info(logs)")}
        if "line_no" not in cols:
            conn.execute("ALTER TABLE logs ADD COLUMN line_no INTEGER")
        conn.commit()
        conn.close()


def write(
    message: str,
    from_node: Optional[str] = None,
    to_node: Optional[str] = None,
    *,
    source: str = "backend",
    client_id: Optional[str] = None,
    seq_no: Optional[int] = None,
    timestamp: Optional[str] = None,
) -> None:
    """ログを1件書き込む。呼び出し元のファイル名・行番号は自動取得する。

    write("メッセージ")
    write("メッセージ", "FromNode", "ToNode")
    """
    if _db_path is None:
        raise RuntimeError("logger not initialized — call logger.init(db_path) first.")

    # sys._getframe(1) は inspect.stack() より約100倍高速
    frame = sys._getframe(1)
    source_file = Path(frame.f_code.co_filename).name
    line_no = frame.f_lineno

    ts = timestamp or datetime.now(timezone.utc).isoformat()

    with _lock:
        conn = _connect()
        conn.execute(_INSERT, (ts, source, client_id, seq_no, from_node, to_node, source_file, line_no, message))
        conn.commit()
        conn.close()


def write_batch(records: list[dict]) -> int:
    """フロントエンドから転送されたレコード群をまとめて書き込む。書き込み件数を返す。"""
    if _db_path is None:
        raise RuntimeError("logger not initialized — call logger.init(db_path) first.")

    rows = [
        (
            r.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            r.get("source", "frontend"),
            r.get("client_id"),
            r.get("seq_no"),
            r.get("from_node"),
            r.get("to_node"),
            r.get("source_file", ""),
            r.get("line_no"),
            r.get("message", ""),
        )
        for r in records
    ]

    with _lock:
        conn = _connect()
        conn.executemany(_INSERT, rows)
        conn.commit()
        conn.close()

    return len(rows)
