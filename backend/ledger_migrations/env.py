"""The independent deletion journal has its own database, owner and migrations."""

from sqlalchemy import create_engine, pool

from alembic import context
from app.core.config import get_settings

url = get_settings().ledger_admin_url
if not url:
    raise RuntimeError("LEDGER_MIGRATION_OWNER_REQUIRED")
if context.is_offline_mode():
    context.configure(url=url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(url, poolclass=pool.NullPool, hide_parameters=True).connect() as connection:
        if connection.exec_driver_sql("SELECT current_user").scalar_one() != "researchos_ledger_admin":
            raise RuntimeError("LEDGER_MIGRATION_OWNER_REQUIRED")
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()
