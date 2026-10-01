"""Alembic env. Pulls DB URL + metadata from the app (Postgres only — see
docker-compose.yml for local dev)."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.config.config_reader import settings
from src.models import Base  # import model modules in src/models/__init__ for autogen

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_offline():
    context.configure(url=settings.DATABASE_URL, target_metadata=target_metadata,
                      literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online():
    cn = engine_from_config(config.get_section(config.config_ini_section, {}),
                            prefix="sqlalchemy.", poolclass=pool.NullPool)
    with cn.connect() as c:
        context.configure(connection=c, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run_offline() if context.is_offline_mode() else run_online()
