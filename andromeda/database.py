"""Local SQLite connections, transaction boundaries and exact cash configuration."""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import URL, Connection, Engine, create_engine, event
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
HEAD = "0001_foundation"


class StorageUnavailable(RuntimeError):
    """The research schema cannot be used by this application version."""


def database_path() -> Path:
    return Path(os.getenv("ANDROMEDA_DB", str(ROOT / "var" / "andromeda.sqlite3"))).resolve()


def cash_cents(value: str) -> int:
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Starting cash must be a USD decimal amount.") from exc
    if not amount.is_finite() or not 0 <= amount <= Decimal("92233720368547758.07"):
        raise ValueError("Starting cash exceeds the nonnegative integer-cent range.")
    cents = amount * 100
    if cents != cents.to_integral_value() or amount != Decimal(int(cents)).scaleb(-2):
        raise ValueError("Starting cash must be exactly representable in cents.")
    return int(cents)


def stamp(value: datetime) -> str:
    if value.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone.")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def make_engine(path: Path, *, mode: Literal["ro", "rw", "rwc"] = "rw") -> Engine:
    engine = create_engine(
        URL.create(
            "sqlite+pysqlite", database=path.resolve().as_uri(), query={"mode": mode, "uri": "true"}
        ),
        poolclass=NullPool,
        connect_args={"timeout": 10, "check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def configure(db: sqlite3.Connection, _: Any) -> None:
        db.isolation_level = None
        db.execute("PRAGMA foreign_keys=ON")
        journal = "PRAGMA journal_mode=WAL" if mode == "rwc" else "PRAGMA journal_mode"
        if db.execute(journal).fetchone()[0].lower() != "wal":
            raise StorageUnavailable("SQLite WAL mode is required.")

    @event.listens_for(engine, "begin")
    def begin(conn: Connection) -> None:
        # Start reads explicitly for a consistent multi-query snapshot under SQLite.
        immediate = conn.get_execution_options().get("writer", False)
        conn.exec_driver_sql("BEGIN IMMEDIATE" if immediate else "BEGIN")

    return engine


@contextmanager
def write_transaction(engine: Engine) -> Iterator[Connection]:
    with engine.connect() as conn:
        conn.execution_options(writer=True)
        with conn.begin():
            yield conn


def migrate(path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    path.parent.mkdir(parents=True, exist_ok=True)
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["path"] = path
    command.upgrade(config, "head")
