"""
routers/allocations.py
----------------------
Presentation layer — HTTP endpoint for triggering the room allocation algorithm.

Routes
------
  POST /allocations/    Run the matchmaker for a given student_id and
                        return the resulting Allocation record.

Design note
-----------
The ``AllocationCreate`` schema in schemas.py carries both ``student_id``
and ``room_id`` because it models the full database entity.  Here the
client only supplies ``student_id`` — the algorithm selects the room.
A lightweight ``AllocationRequest`` body model is defined locally to
keep this contract explicit without polluting the shared schema module.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.algorithms.matchmaker import allocate_room
from app.database import get_db
from app.schemas import AllocationResponse

router = APIRouter(
    prefix="/allocations",
    tags=["Allocations"],
)


# ---------------------------------------------------------------------------
# Local request body schema
# ---------------------------------------------------------------------------

class AllocationRequest(BaseModel):
    """Inbound payload for POST /allocations/."""

    student_id: int = Field(
        ...,
        gt=0,
        description="Primary key of the Student to allocate a room for.",
        examples=[1],
    )

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# POST /allocations/ — Run the matchmaker
# ---------------------------------------------------------------------------

@router.post(
    "/",
    response_model=AllocationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Allocate a room for a student",
    description=(
        "Runs the algorithmic matchmaker for the given ``student_id``. "
        "Applies budget, availability, and gender-compatibility constraints "
        "to find the best room, then creates an ``Allocation`` record with "
        "status ``PENDING``. "
        "The selected room row is locked with ``SELECT … FOR UPDATE`` to "
        "prevent race conditions under concurrent requests."
    ),
)
def trigger_allocation(
    payload: AllocationRequest,
    db: Session = Depends(get_db),
) -> AllocationResponse:
    """
    Invoke ``allocate_room`` and surface any domain errors as HTTP responses.

    The matchmaker already raises ``HTTPException`` for known failure modes
    (404 student not found, 400 no suitable room).  Those propagate through
    FastAPI automatically.  Any unexpected exception is caught here and
    re-raised as a 500 so the client always receives a structured JSON error.

    Args:
        payload: Validated request body containing ``student_id``.
        db:      Injected database session (one per request).

    Returns:
        The newly created ``AllocationResponse`` on success.

    Raises:
        HTTPException 404: Student not found.
        HTTPException 400: No suitable room is available.
        HTTPException 500: Unexpected server-side error.
    """
    try:
        allocation = allocate_room(db=db, student_id=payload.student_id)

    except HTTPException:
        # Re-raise domain errors (404, 400) produced by the matchmaker
        # without wrapping them — they already carry the correct status
        # code and user-facing detail message.
        raise

    except Exception as exc:
        # Roll back any partial writes before propagating.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "An unexpected error occurred while processing the allocation. "
                f"Details: {exc}"
            ),
        ) from exc

    return allocation
