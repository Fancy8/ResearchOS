"""Alembic migrations use a separate owner connection, never the application role."""
from logging.config import fileConfig
from alembic import context
from sqlalchemy import create_engine, pool
from app.core.config import get_settings
from app.db.base import Base
from app import models  # noqa: F401

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
url = get_settings().admin_database_url
if not url:
    raise RuntimeError("A migration-owner database URL is required by the migration runner")

if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(url, poolclass=pool.NullPool).connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
