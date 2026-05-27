"""
routers/allocations.py
----------------------
Presentation layer — HTTP endpoint for triggering the room allocation algorithm.

Routes
------
  POST   /allocations/              Run the matchmaker for a given student_id and
                                    return the resulting Allocation record.
  DELETE /allocations/{allocation_id}  Cancel an allocation and trigger automatic
                                    waitlist promotion.

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

from app.algorithms.matchmaker import allocate_room, cancel_allocation
from app.auth import get_current_admin
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
        "prevent race conditions under concurrent requests. "
        "**Requires admin Bearer token.**"
    ),
    dependencies=[Depends(get_current_admin)],
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


# ---------------------------------------------------------------------------
# DELETE /allocations/{allocation_id} — Cancel + promote from waitlist
# ---------------------------------------------------------------------------

@router.delete(
    "/{allocation_id}",
    status_code=status.HTTP_200_OK,
    summary="Cancel an allocation",
    description=(
        "Cancels the specified Allocation record and frees the associated room bed. "
        "Immediately attempts to promote the oldest eligible WAITLISTED student "
        "into the vacated room. Returns a summary of the cancellation and any "
        "promotion that occurred. "
        "**Requires admin Bearer token.**"
    ),
    dependencies=[Depends(get_current_admin)],
)
def cancel(
    allocation_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """
    Invoke ``cancel_allocation`` and surface domain errors as HTTP responses.

    Args:
        allocation_id: Path parameter — primary key of the Allocation to cancel.
        db:            Injected database session (one per request).

    Returns:
        A JSON object summarising the cancellation and any waitlist promotion.

    Raises:
        HTTPException 404: Allocation not found.
        HTTPException 400: Allocation is already CANCELLED.
        HTTPException 500: Unexpected server-side error.
    """
    try:
        result = cancel_allocation(db=db, allocation_id=allocation_id)

    except HTTPException:
        raise

    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "An unexpected error occurred while cancelling the allocation. "
                f"Details: {exc}"
            ),
        ) from exc

    return result
