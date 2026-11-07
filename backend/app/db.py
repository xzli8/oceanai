import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "app.db"


def db_path() -> str:
    return os.environ.get("CERT_DB_PATH", str(DEFAULT_DB))


def connect() -> sqlite3.Connection:
    # isolation_level=None: we control transactions explicitly (BEGIN IMMEDIATE for writes).
    # check_same_thread=False: streaming responses may iterate on different threadpool workers.
    conn = sqlite3.connect(db_path(), isolation_level=None, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def write_tx(conn: sqlite3.Connection):
    """Serialize writers: BEGIN IMMEDIATE takes the write lock up front."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(iso: str) -> datetime:
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def local_date(iso_utc: str, tz: str) -> str:
    return parse_utc(iso_utc).astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d")


def local_datetime(iso_utc: str, tz: str) -> str:
    return parse_utc(iso_utc).astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")
