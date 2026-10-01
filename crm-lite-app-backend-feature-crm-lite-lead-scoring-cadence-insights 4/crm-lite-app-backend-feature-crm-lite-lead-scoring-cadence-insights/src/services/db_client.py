"""Database client — lazy sync SQLAlchemy engine + session provider.

Postgres only (see docker-compose.yml for local dev; Azure Database for
PostgreSQL in real environments — same URL scheme, no code change). Engine
built on first use so the app imports without a live DB.
"""
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.config.config_reader import settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(settings.DATABASE_URL, pool_pre_ping=True, future=True)


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker:
    """Public session factory — repositories that need their own short-lived
    session (e.g. `with get_session_factory()() as db: ...`) use this directly
    instead of the request-scoped `get_db` dependency below."""
    return sessionmaker(bind=get_engine(), autoflush=False,
                        expire_on_commit=False, class_=Session, future=True)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yield session, commit on success, always close."""
    db = get_session_factory()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
