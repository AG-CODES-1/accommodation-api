"""
tests/test_allocations.py
--------------------------
Integration tests for the allocation engine and waitlist promotion logic.

Test database
-------------
An in-memory SQLite database (sqlite:///:memory:) is used so tests are
fully isolated from the development accommodation.db file.

SQLAlchemy's StaticPool is used to ensure every session in the test process
shares the same single in-memory connection — without it each new session
would open a fresh (empty) database, breaking the test flow.

Running the tests
-----------------
    pytest tests/test_allocations.py -v
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Allocation

# ===========================================================================
# In-memory test database setup
# ===========================================================================

SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///:memory:"

test_engine = create_engine(
    SQLALCHEMY_TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # All sessions share one connection → DB persists.
)

TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=test_engine,
)

# Create every table defined in our ORM on the in-memory engine.
Base.metadata.create_all(bind=test_engine)


# ---------------------------------------------------------------------------
# Dependency override — swap the real DB session for the test one
# ---------------------------------------------------------------------------

def override_get_db():
    """Yield a session backed by the in-memory test database."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

# ===========================================================================
# Test client
# ===========================================================================

client = TestClient(app)


# ===========================================================================
# Helper: obtain an admin Bearer token
# ===========================================================================

def _get_admin_token() -> str:
    """
    Authenticate against POST /admin/login and return a signed JWT string.

    Uses the hardcoded MVP credentials defined in routers/admin.py.
    """
    response = client.post(
        "/admin/login",
        data={"username": "admin", "password": "password123"},
    )
    assert response.status_code == 200, (
        f"Admin login failed unexpectedly: {response.json()}"
    )
    return response.json()["access_token"]


# ===========================================================================
# Tests
# ===========================================================================

def test_waitlist_and_promotion_engine():
    """
    End-to-end scenario that exercises the full allocation lifecycle:

    1. Create a single-bed room.
    2. Create two compatible students (same gender, both within budget).
    3. Authenticate as admin.
    4. Allocate Student A  → expects PENDING  with a room assigned.
    5. Allocate Student B  → expects WAITLISTED (room is now full).
    6. Cancel Student A's allocation.
    7. Assert Student B was automatically promoted to PENDING with the
       room assigned — proving the promotion engine works end-to-end.
    """

    # ------------------------------------------------------------------
    # Step 1 — Create a room with capacity = 1
    # ------------------------------------------------------------------
    room_response = client.post(
        "/rooms/",
        json={
            "block_name":         "Block T",
            "room_number":        "T01",
            "capacity":           1,
            "price":              500.00,
            "gender_restriction": "mixed",
        },
    )
    assert room_response.status_code == 201, room_response.json()
    room_id: int = room_response.json()["id"]

    # ------------------------------------------------------------------
    # Step 2 — Create Student A
    # ------------------------------------------------------------------
    response_a = client.post(
        "/students/",
        json={
            "name":           "Student A",
            "gender":         "female",
            "academic_level": "100_level",
            "max_budget":     1000.00,
            "study_habit":    "quiet",
        },
    )
    assert response_a.status_code == 201, response_a.json()
    student_a_id: int = response_a.json()["id"]

    # ------------------------------------------------------------------
    # Step 3 — Create Student B
    # ------------------------------------------------------------------
    response_b = client.post(
        "/students/",
        json={
            "name":           "Student B",
            "gender":         "female",
            "academic_level": "200_level",
            "max_budget":     1000.00,
            "study_habit":    "moderate",
        },
    )
    assert response_b.status_code == 201, response_b.json()
    student_b_id: int = response_b.json()["id"]

    # ------------------------------------------------------------------
    # Step 4 — Authenticate as admin
    # ------------------------------------------------------------------
    token = _get_admin_token()
    auth_headers = {"Authorization": f"Bearer {token}"}

    # ------------------------------------------------------------------
    # Step 5 — Allocate Student A → room is free, should get PENDING
    # ------------------------------------------------------------------
    alloc_a_response = client.post(
        "/allocations/",
        json={"student_id": student_a_id},
        headers=auth_headers,
    )
    assert alloc_a_response.status_code == 201, alloc_a_response.json()

    alloc_a = alloc_a_response.json()
    assert alloc_a["status"]  == "pending", (
        f"Expected PENDING but got: {alloc_a['status']}"
    )
    assert alloc_a["room_id"] == room_id, (
        f"Expected room_id={room_id} but got: {alloc_a['room_id']}"
    )
    alloc_a_id: int = alloc_a["id"]

    # ------------------------------------------------------------------
    # Step 6 — Allocate Student B → room is full, should be WAITLISTED
    # ------------------------------------------------------------------
    alloc_b_response = client.post(
        "/allocations/",
        json={"student_id": student_b_id},
        headers=auth_headers,
    )
    assert alloc_b_response.status_code == 201, alloc_b_response.json()

    alloc_b = alloc_b_response.json()
    assert alloc_b["status"]  == "waitlisted", (
        f"Expected WAITLISTED but got: {alloc_b['status']}"
    )
    assert alloc_b["room_id"] is None, (
        f"Expected room_id=None but got: {alloc_b['room_id']}"
    )
    alloc_b_id: int = alloc_b["id"]

    # ------------------------------------------------------------------
    # Step 7 — Cancel Student A's allocation
    # ------------------------------------------------------------------
    cancel_response = client.delete(
        f"/allocations/{alloc_a_id}",
        headers=auth_headers,
    )
    assert cancel_response.status_code == 200, cancel_response.json()

    cancel_result = cancel_response.json()
    assert cancel_result["cancelled_allocation_id"] == alloc_a_id
    assert cancel_result["freed_room_id"]           == room_id

    # The promotion engine should have immediately promoted Student B.
    assert cancel_result["promoted_allocation_id"]  == alloc_b_id, (
        "Promotion engine did not return the correct promoted allocation id."
    )
    assert cancel_result["promoted_student_id"]     == student_b_id, (
        "Promotion engine promoted the wrong student."
    )

    # ------------------------------------------------------------------
    # Step 8 — Confirm Student B's record in the DB is now PENDING
    # ------------------------------------------------------------------
    # Query the test DB directly to verify the persisted state, not just
    # the API response (which comes from the same transaction).
    db = TestingSessionLocal()
    try:
        promoted: Allocation | None = (
            db.query(Allocation)
            .filter(Allocation.id == alloc_b_id)
            .first()
        )

        assert promoted is not None, "Student B's allocation record not found in DB."
        assert promoted.status.value == "pending", (
            f"DB shows status={promoted.status.value!r}, expected 'pending'."
        )
        assert promoted.room_id == room_id, (
            f"DB shows room_id={promoted.room_id}, expected {room_id}."
        )
    finally:
        db.close()
