import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from core.config import get_settings
from core.db.models import Base

target_metadata = Base.metadata


def _url() -> str:
    # Tests pass an explicit URL via `config.attributes["database_url"]`.
    url = context.config.attributes.get("database_url")
    return str(url) if url else get_settings().database_url


def include_object(obj, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    # Indexes are defined in migration SQL (HNSW, GIN, partial), not on the models.
    # Don't let autogenerate propose dropping them.
    if type_ == "index" and reflected and compare_to is None:
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(
        connection=connection, target_metadata=target_metadata, include_object=include_object
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
