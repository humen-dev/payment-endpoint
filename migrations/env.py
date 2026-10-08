from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

import shop.models  # noqa: F401 (registers the models on `db.metadata`)
from shop.config import Config
from shop.extensions import db

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def database_url() -> str:
    """An explicitly configured URL (e.g. by the tests) wins over the app config."""
    return config.get_main_option("sqlalchemy.url") or Config.SQLALCHEMY_DATABASE_URI


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(), target_metadata=db.metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=db.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
