"""Alembic environment for the G1N persistent schema.

This is the W4 production migration path.  Local dev uses
``db.init_db()`` (``Base.metadata.create_all``) for zero-friction
bootstrapping; production uses ``alembic upgrade head`` against
PostgreSQL.

Usage
-----

    cd server
    alembic upgrade head
    alembic revision --autogenerate -m "..."

The DSN is taken from ``G1N_DB_URL`` (falls back to the same
SQLite default as :mod:`server.db`).
"""

from __future__ import annotations

import os
import pathlib
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make ``server`` importable when alembic is invoked from any cwd.
SERVER_ROOT = pathlib.Path(__file__).resolve().parents[1]
PROJECT_ROOT = SERVER_ROOT.parent
sys.path.insert(0, str(SERVER_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from db import Base  # noqa: E402  (import after sys.path tweak)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_url() -> str:
    return (
        os.environ.get("G1N_DB_URL")
        or os.environ.get("DATABASE_URL")
        or f"sqlite:///{(PROJECT_ROOT / 'data' / 'g1n.db').as_posix()}"
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    config.set_main_option("sqlalchemy.url", _get_url())
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
