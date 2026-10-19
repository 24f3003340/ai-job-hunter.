from alembic import context
from sqlalchemy import create_engine, pool

from app import models  # noqa: F401  (register tables on Base.metadata)
from app.config import settings
from app.db import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    # Tests and tooling may pass a URL via -x url=... or config.set_main_option("sqlalchemy.url", ...)
    return context.get_x_argument(as_dictionary=True).get("url") or config.get_main_option("sqlalchemy.url") or settings.database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is None:
        engine = create_engine(_url(), poolclass=pool.NullPool)
        with engine.connect() as connection:
            _run(connection)
        return
    _run(connectable)


def _run(connection) -> None:
    # render_as_batch lets SQLite (tests/dev) apply the same ALTERs as PostgreSQL.
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True,
                      compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
