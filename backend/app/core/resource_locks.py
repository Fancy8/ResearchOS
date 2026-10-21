from contextlib import contextmanager
from functools import wraps
from uuid import UUID

from sqlalchemy import select, text

from app.models import Workspace


def guard_resource(model):
    """Shared session lock covers remote I/O; cleanup waits on an exclusive lock."""

    def decorator(function):
        @wraps(function)
        def guarded(job_id):
            from app.workers.jobs import sync_engine

            identifier = UUID(str(job_id))
            with sync_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                workspace = connection.execute(
                    select(model.workspace_id).where(model.id == identifier)
                ).scalar_one_or_none()
                if not workspace:
                    return
                scope = f"resource:{workspace}"
                connection.execute(
                    text("SELECT pg_advisory_lock_shared(hashtextextended(:scope,0))"), {"scope": scope}
                )
                try:
                    active = connection.execute(
                        select(Workspace.status).where(Workspace.id == workspace)
                    ).scalar_one_or_none()
                    if active != "active":
                        return
                    return function(job_id)
                finally:
                    connection.execute(
                        text("SELECT pg_advisory_unlock_shared(hashtextextended(:scope,0))"), {"scope": scope}
                    )

        return guarded

    return decorator


@contextmanager
def exclusive_resource(engine, workspace_id, *, wait=True):
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        lock = "pg_advisory_lock" if wait else "pg_try_advisory_lock"
        result = connection.execute(text(f"SELECT {lock}(hashtextextended('backup-preserve',0))")).scalar()
        if not wait and not result:
            yield False
            return
        scope = f"resource:{workspace_id}"
        try:
            result = connection.execute(
                text(f"SELECT {lock}(hashtextextended(:scope,0))"), {"scope": scope}
            ).scalar()
            if not wait and not result:
                yield False
                return
            try:
                yield True
            finally:
                connection.execute(
                    text("SELECT pg_advisory_unlock(hashtextextended(:scope,0))"), {"scope": scope}
                )
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(hashtextextended('backup-preserve',0))"))
