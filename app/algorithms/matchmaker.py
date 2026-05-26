"""
algorithms/matchmaker.py
------------------------
Domain service layer — core room allocation algorithm.

This module contains the pure business logic for matching a Student
applicant to a suitable Room.  It has no knowledge of HTTP routing;
it operates only on domain objects and raises domain-appropriate
exceptions that the router layer translates into HTTP responses.

Algorithm summary
-----------------
1. Fetch the student — raise 404 if not found.
2. Build gender-compatibility filter rules.
3. Query rooms that satisfy capacity, budget, and gender constraints.
4. Lock the selected row with FOR UPDATE to prevent double-allocation
   under concurrent requests.
5. Create an Allocation record and increment the room's occupant count.
6. Commit atomically and return the new Allocation.
"""

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.models import (
    Allocation,
    AllocationStatusEnum,
    GenderEnum,
    GenderRestrictionEnum,
    Room,
    Student,
)


# ---------------------------------------------------------------------------
# Gender-compatibility helper
# ---------------------------------------------------------------------------

def _build_gender_filter(student_gender: GenderEnum):
    """
    Return a SQLAlchemy filter expression that restricts rooms to those
    compatible with the given student gender.

    Compatibility matrix
    --------------------
    Student gender  │  Eligible room restrictions
    ────────────────┼──────────────────────────────
    MALE            │  MALE_ONLY, MIXED
    FEMALE          │  FEMALE_ONLY, MIXED
    OTHER           │  MIXED only  (safest default)

    Args:
        student_gender: The ``GenderEnum`` value from the Student record.

    Returns:
        A SQLAlchemy ``BinaryExpression`` suitable for use in ``.filter()``.
    """
    mixed_clause = Room.gender_restriction == GenderRestrictionEnum.MIXED

    if student_gender == GenderEnum.MALE:
        return or_(
            mixed_clause,
            Room.gender_restriction == GenderRestrictionEnum.MALE_ONLY,
        )
    elif student_gender == GenderEnum.FEMALE:
        return or_(
            mixed_clause,
            Room.gender_restriction == GenderRestrictionEnum.FEMALE_ONLY,
        )
    else:
        # GenderEnum.OTHER — restrict to gender-neutral rooms only.
        return mixed_clause


# ---------------------------------------------------------------------------
# Core allocation function
# ---------------------------------------------------------------------------

def allocate_room(db: Session, student_id: int) -> Allocation:
    """
    Match a Student to the best available Room and persist the result.

    The function executes inside the caller's database transaction.  The
    caller (router) is responsible for rolling back on unhandled errors.

    Locking strategy
    ----------------
    ``.with_for_update()`` issues a ``SELECT … FOR UPDATE`` statement,
    acquiring a row-level exclusive lock on the chosen room for the
    duration of the transaction.  This prevents two concurrent requests
    from allocating the same room's last bed simultaneously.

    .. note::
        SQLite does not support row-level ``FOR UPDATE`` locking — it
        falls back to a full-table lock via its WAL/journal mechanism.
        The call is safe and correct on SQLite; the locking guarantee
        is strongest on PostgreSQL or MySQL in production.

    Args:
        db:         An active SQLAlchemy ``Session``.
        student_id: Primary key of the Student to allocate.

    Returns:
        The newly created and committed ``Allocation`` ORM instance.

    Raises:
        HTTPException 404: Student with ``student_id`` does not exist.
        HTTPException 400: No room satisfies all three constraints
                           (availability, budget, gender compatibility).
    """

    # ------------------------------------------------------------------
    # Step 1 — Fetch student or raise 404
    # ------------------------------------------------------------------
    student: Student | None = db.query(Student).filter(Student.id == student_id).first()

    if student is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with id={student_id} was not found.",
        )

    # ------------------------------------------------------------------
    # Step 2 — Build constraint filters
    # ------------------------------------------------------------------
    availability_filter = Room.current_occupants < Room.capacity
    budget_filter       = Room.price <= student.max_budget
    gender_filter       = _build_gender_filter(student.gender)

    # ------------------------------------------------------------------
    # Step 3 & 4 — Query and lock the first matching room
    # ------------------------------------------------------------------
    # Rooms are ordered by price ascending so the student is allocated
    # the most affordable eligible room first (best-fit heuristic).
    # .with_for_update() acquires an exclusive row lock before we read
    # the row, preventing concurrent transactions from picking the same
    # room until this transaction commits or rolls back.
    room: Room | None = (
        db.query(Room)
        .filter(
            and_(
                availability_filter,
                budget_filter,
                gender_filter,
            )
        )
        .order_by(Room.price.asc())
        .with_for_update()
        .first()
    )

    if room is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No suitable rooms are available for this student. "
                "All rooms matching the budget and gender criteria are either "
                "fully occupied or do not exist."
            ),
        )

    # ------------------------------------------------------------------
    # Step 5a — Create the Allocation record
    # ------------------------------------------------------------------
    new_allocation = Allocation(
        student_id=student.id,
        room_id=room.id,
        timestamp=datetime.now(timezone.utc),
        status=AllocationStatusEnum.PENDING,
    )
    db.add(new_allocation)

    # ------------------------------------------------------------------
    # Step 5b — Increment room occupancy
    # ------------------------------------------------------------------
    # This is done on the already-locked ORM instance so SQLAlchemy
    # generates an UPDATE on the same row we selected above.
    room.current_occupants += 1

    # ------------------------------------------------------------------
    # Step 6 — Commit atomically and return
    # ------------------------------------------------------------------
    db.commit()

    # Refresh to load any server-generated values (e.g. allocation id)
    # before returning to the caller.
    db.refresh(new_allocation)

    return new_allocation
