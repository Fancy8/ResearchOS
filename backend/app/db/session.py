from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

engine = create_async_engine(
    get_settings().database_url,
    pool_pre_ping=True,
    hide_parameters=True,
    connect_args={"options": "-c timezone=UTC"},
    **(
        {"poolclass": NullPool}
        if get_settings().environment == "test"
        else {"pool_size": 5, "max_overflow": 5}
    ),
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session():
    async with SessionLocal() as session:
        async with session.begin():
            yield session
