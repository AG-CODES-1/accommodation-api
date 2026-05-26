"""
database.py
-----------
Infrastructure layer — SQLAlchemy engine and session factory.

SQLite is used for local MVP development.  Swap DATABASE_URL for a
PostgreSQL / MySQL connection string when moving to staging/production.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# ---------------------------------------------------------------------------
# Connection URL
# ---------------------------------------------------------------------------
# The database file will be created in the project root as `accommodation.db`.
# Override this via an environment variable in production environments.
DATABASE_URL: str = "sqlite:///./accommodation.db"

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
# `check_same_thread=False` is required for SQLite when used with FastAPI's
# multi-threaded request handling.  This flag has no effect on other dialects.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,          # Set to True to log all generated SQL statements.
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
# Each request should open its own session and close it when done.
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,   # Transactions must be committed explicitly.
    autoflush=False,    # Prevents premature flushes before a commit.
)

# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------
# All ORM model classes inherit from this base so SQLAlchemy can discover them.
class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


# ---------------------------------------------------------------------------
# Dependency helper (for FastAPI route injection — imported by routes layer)
# ---------------------------------------------------------------------------
def get_db():
    """
    Yield a database session for the duration of a single request.

    Usage (FastAPI dependency injection):
        db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
