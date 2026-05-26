"""
algorithms/matchmaker.py
------------------------
Domain service layer — core room allocation algorithm.

This module contains the pure business logic for matching a Student
applicant to a suitable Room.  It has no knowledge of HTTP routing;
it operates only on domain objects and raises domain-appropriate
exceptions that the router layer translates into HTTP responses.

Functions
---------
allocate_room       — Match a student to the best available room.
                      Falls back to WAITLISTED status if no room fits.
cancel_allocation   — Cancel an existing allocation, free the room,
                      and automatically promote the oldest eligible
                      waitlisted student into the vacated bed.
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

    Returns ``status=WAITLISTED`` (instead of raising) when no room
    satisfies all three constraints simultaneously.
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
        # ------------------------------------------------------------------
        # Waitlist fallback — no suitable room is currently available.
        # ------------------------------------------------------------------
        # Rather than rejecting the student, we record their intent with
        # room_id=None and status=WAITLISTED.  A future background job or
        # manual admin action can re-run the matcher and promote them when
        # a room opens up.
        waitlisted_allocation = Allocation(
            student_id=student.id,
            room_id=None,
            timestamp=datetime.now(timezone.utc),
            status=AllocationStatusEnum.WAITLISTED,
        )
        db.add(waitlisted_allocation)
        db.commit()
        db.refresh(waitlisted_allocation)
        return waitlisted_allocation

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


# ---------------------------------------------------------------------------
# Room-to-student gender eligibility helper
# ---------------------------------------------------------------------------

# Maps a room's gender restriction to the set of student genders that are
# allowed to occupy it.  Used during waitlist promotion to find compatible
# waiting students for the newly freed room.
_ROOM_RESTRICTION_TO_ELIGIBLE_GENDERS: dict[GenderRestrictionEnum, list[GenderEnum]] = {
    GenderRestrictionEnum.MIXED:       [GenderEnum.MALE, GenderEnum.FEMALE, GenderEnum.OTHER],
    GenderRestrictionEnum.MALE_ONLY:   [GenderEnum.MALE],
    GenderRestrictionEnum.FEMALE_ONLY: [GenderEnum.FEMALE],
}


# ---------------------------------------------------------------------------
# Cancellation + waitlist promotion function
# ---------------------------------------------------------------------------

def cancel_allocation(db: Session, allocation_id: int) -> dict:
    """
    Cancel an existing Allocation and automatically promote the oldest
    eligible waitlisted student into the vacated room (if one exists).

    State machine transitions
    -------------------------
    Cancelled allocation:    PENDING / CONFIRMED  →  CANCELLED
    Promoted allocation:     WAITLISTED           →  PENDING

    Locking strategy
    ----------------
    Both the target Allocation row and (when applicable) the Room row
    are locked with ``SELECT … FOR UPDATE`` before mutation.  The
    waitlisted Allocation selected for promotion is locked the same way.
    All three locks are held within a single transaction, so no other
    concurrent request can observe an inconsistent intermediate state.

    Args:
        db:            An active SQLAlchemy ``Session``.
        allocation_id: Primary key of the Allocation to cancel.

    Returns:
        A dictionary containing:
        - ``cancelled_allocation_id``  — id of the cancelled record.
        - ``freed_room_id``            — id of the room that was freed
                                         (None for waitlisted cancellations).
        - ``promoted_allocation_id``   — id of the promoted waitlisted
                                         record, or None if no match found.
        - ``promoted_student_id``      — student_id of the promoted
                                         record, or None.
        - ``message``                  — human-readable summary.

    Raises:
        HTTPException 404: Allocation with ``allocation_id`` does not exist.
        HTTPException 400: Allocation is already CANCELLED.
    """

    # ------------------------------------------------------------------
    # Step 1 — Fetch and lock the target allocation
    # ------------------------------------------------------------------
    allocation: Allocation | None = (
        db.query(Allocation)
        .filter(Allocation.id == allocation_id)
        .with_for_update()
        .first()
    )

    if allocation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Allocation with id={allocation_id} was not found.",
        )

    if allocation.status == AllocationStatusEnum.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Allocation id={allocation_id} is already CANCELLED.",
        )

    # ------------------------------------------------------------------
    # Step 2 — Cancel the allocation
    # ------------------------------------------------------------------
    allocation.status = AllocationStatusEnum.CANCELLED
    freed_room: Room | None = None

    # ------------------------------------------------------------------
    # Step 3 — Free the room (if any was assigned)
    # ------------------------------------------------------------------
    if allocation.room_id is not None:
        freed_room = (
            db.query(Room)
            .filter(Room.id == allocation.room_id)
            .with_for_update()
            .first()
        )
        if freed_room is not None:
            freed_room.current_occupants = max(0, freed_room.current_occupants - 1)

    # ------------------------------------------------------------------
    # Step 4 — Waitlist promotion
    # ------------------------------------------------------------------
    # Only attempt promotion when a real room was freed.
    promoted_allocation: Allocation | None = None

    if freed_room is not None:
        eligible_genders = _ROOM_RESTRICTION_TO_ELIGIBLE_GENDERS[freed_room.gender_restriction]

        # Find the oldest WAITLISTED allocation whose student can afford
        # the freed room and whose gender is compatible with its restriction.
        promoted_allocation = (
            db.query(Allocation)
            .join(Student, Allocation.student_id == Student.id)
            .filter(
                and_(
                    Allocation.status == AllocationStatusEnum.WAITLISTED,
                    Student.max_budget >= freed_room.price,
                    Student.gender.in_(eligible_genders),
                )
            )
            .order_by(Allocation.timestamp.asc())   # Oldest first — FIFO fairness.
            .with_for_update()
            .first()
        )

        if promoted_allocation is not None:
            promoted_allocation.room_id = freed_room.id
            promoted_allocation.status  = AllocationStatusEnum.PENDING
            freed_room.current_occupants += 1        # Re-occupy the bed.

    # ------------------------------------------------------------------
    # Step 5 — Commit atomically
    # ------------------------------------------------------------------
    db.commit()

    # ------------------------------------------------------------------
    # Step 6 — Build and return the result summary
    # ------------------------------------------------------------------
    if promoted_allocation is not None:
        message = (
            f"Allocation {allocation_id} cancelled. "
            f"Student {promoted_allocation.student_id} promoted from waitlist "
            f"into room {freed_room.id}."
        )
    elif freed_room is not None:
        message = (
            f"Allocation {allocation_id} cancelled and room {freed_room.id} freed. "
            "No eligible waitlisted student found for promotion."
        )
    else:
        message = (
            f"Waitlisted allocation {allocation_id} cancelled. "
            "No room was freed (allocation had no assigned room)."
        )

    return {
        "cancelled_allocation_id": allocation_id,
        "freed_room_id":           freed_room.id if freed_room else None,
        "promoted_allocation_id":  promoted_allocation.id if promoted_allocation else None,
        "promoted_student_id":     promoted_allocation.student_id if promoted_allocation else None,
        "message":                 message,
    }
