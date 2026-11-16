"""Engine and session factory. Tests pass an explicit URL so they never use the Compose database."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def make_engine(url: str | None = None) -> Engine:
    """Open a Postgres engine. The default URL is the application database."""
    return create_engine(url or get_settings().database_url, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build a session factory that does not expire objects after commit."""
    return sessionmaker(bind=engine, expire_on_commit=False)
