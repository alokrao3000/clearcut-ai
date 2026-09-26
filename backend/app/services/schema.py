"""Schema state at startup.

Until M6 the app called `Base.metadata.create_all` on boot, which quietly adds new *tables*
and never new *columns* — so a model change appeared to work and then failed at the first
query. Alembic now owns the schema, and this module decides what the app does about it.

The default is to check, not to migrate. Several API processes starting at once would race
each other through the same DDL, so migrating belongs in a deploy step that runs once.
`CLEARCUT_AUTO_MIGRATE=true` is for a single-process dev box and the compose file.
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


class SchemaOutOfDate(RuntimeError):
    """The database is behind the code. Refusing to serve is safer than half-working."""


def alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def head_revision(database_url: str) -> str | None:
    return ScriptDirectory.from_config(alembic_config(database_url)).get_current_head()


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def upgrade(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "head")


def ensure_ready(engine: Engine, database_url: str, *, auto_migrate: bool) -> str:
    """Bring the schema to head, or refuse to start. Returns the revision now in place."""
    head = head_revision(database_url)
    current = current_revision(engine)

    if current == head:
        return head or "none"

    if auto_migrate:
        log.info("Migrating database from %s to %s", current or "empty", head)
        upgrade(database_url)
        return head or "none"

    raise SchemaOutOfDate(
        f"The database is at revision {current or 'none'} but this code expects {head}. "
        "Run `alembic upgrade head` as part of your deploy, or set CLEARCUT_AUTO_MIGRATE=true "
        "on a single-process development machine."
    )
