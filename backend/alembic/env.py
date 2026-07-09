from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Import the app's own settings + full ORM metadata. `prepend_sys_path = .` in
# alembic.ini (default alembic init value) puts `backend/` — the directory
# alembic is always run from, per the README's documented workflow — on
# sys.path, so these resolve the same way `foundation.config`/`db.models` do
# everywhere else in the app (tests, future `api/` routers).
from db.models import Base  # noqa: E402
from foundation.config import get_settings  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Single source of truth for the DB URL: foundation.config.get_settings(),
# same as db/session.py's runtime engine — never a second, alembic-only URL
# hardcoded in alembic.ini. This also means `alembic upgrade head` respects
# whatever DATABASE_URL/.env override is active (e.g. a throwaway SQLite file
# for a verification run), same as the app.
config.set_main_option("sqlalchemy.url", get_settings().database_url)

# Full ORM metadata — every model module is imported via `db.models`
# (see db/models/__init__.py), so this is the complete schema for
# `alembic revision --autogenerate` to diff against.
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite can't ALTER most column properties in place; batch mode
        # emulates ALTER via a recreate-and-copy strategy so future
        # migrations (not just this initial CREATE TABLE one) still work
        # against the SQLite pilot DB, not only Postgres.
        render_as_batch=url.startswith("sqlite"),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=connection.dialect.name == "sqlite",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
