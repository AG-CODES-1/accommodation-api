"""
main.py
-------
Application entry point for the HostelSync Allocation API.

Responsibilities:
  - Instantiate the FastAPI application with metadata.
  - Trigger SQLAlchemy table creation on startup (dev/MVP convenience).
  - Expose a root health-check endpoint.

Registered domain routers:
  - /students     →  app.routers.students
  - /rooms        →  app.routers.rooms
  - /allocations  →  app.routers.allocations
  - /admin        →  app.routers.admin  (login + JWT issuance)
"""

from fastapi import FastAPI

from app.routers import admin, allocations, rooms, students

from app.database import engine
from app.models import Base  # Importing Base after all model classes ensures
                              # every table is registered on the metadata object
                              # before create_all is called.

# ---------------------------------------------------------------------------
# Create all database tables
# ---------------------------------------------------------------------------
# For the local MVP this runs synchronously at import time.
# In a production setup, consider replacing this with Alembic migrations
# so that schema changes are versioned and reversible.
Base.metadata.create_all(bind=engine)

# ---------------------------------------------------------------------------
# FastAPI application instance
# ---------------------------------------------------------------------------
app = FastAPI(
    title="HostelSync Allocation API",
    description=(
        "Algorithmic Accommodation Matchmaker — matches student applicants "
        "to available rooms using a Domain-Driven Design architecture."
    ),
    version="0.1.0",
    contact={
        "name": "HostelSync Development Team",
    },
    license_info={
        "name": "MIT",
    },
)


# ---------------------------------------------------------------------------
# Health-check endpoint
# ---------------------------------------------------------------------------

@app.get(
    "/",
    summary="Health Check",
    description="Confirms that the API server is online and reachable.",
    tags=["Health"],
)
def health_check() -> dict:
    """
    Root endpoint — returns a simple liveness message.

    Returns:
        dict: A JSON object with a ``status`` and ``message`` field.
    """
    return {
        "status": "online",
        "message": "HostelSync Allocation API is up and running.",
    }


# ---------------------------------------------------------------------------
# Domain routers
# ---------------------------------------------------------------------------
# Prefix and tags are already declared on each APIRouter instance, so they
# are intentionally omitted here to avoid duplication (which would produce
# double-prefixed paths such as /students/students/).

app.include_router(students.router)
app.include_router(rooms.router)
app.include_router(allocations.router)
app.include_router(admin.router)
