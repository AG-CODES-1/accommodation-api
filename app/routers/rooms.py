"""
routers/rooms.py
----------------
Presentation layer — HTTP endpoints for the Room domain entity.

Routes
------
  POST /rooms/       Create a new room record.
  GET  /rooms/       List all room records.
"""

from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Room
from app.schemas import RoomCreate, RoomResponse

router = APIRouter(
    prefix="/rooms",
    tags=["Rooms"],
)


# ---------------------------------------------------------------------------
# POST /rooms/ — Create a new room
# ---------------------------------------------------------------------------

@router.post(
    "/",
    response_model=RoomResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new room",
    description=(
        "Register a new accommodation room with its location, capacity, "
        "pricing, and gender restriction. The server assigns the primary key."
    ),
)
def create_room(
    payload: RoomCreate,
    db: Session = Depends(get_db),
) -> Room:
    """
    Persist a new Room record from the validated request payload.

    Args:
        payload: Validated ``RoomCreate`` schema from the request body.
        db:      Injected database session (one per request).

    Returns:
        The newly created ``Room`` ORM instance.

    Note:
        ``current_occupants`` defaults to 0 in the schema; the allocation
        service is responsible for incrementing this field when a student
        is confirmed into the room.
    """
    new_room = Room(
        block_name=payload.block_name,
        room_number=payload.room_number,
        capacity=payload.capacity,
        current_occupants=payload.current_occupants,
        price=payload.price,
        gender_restriction=payload.gender_restriction,
    )

    db.add(new_room)
    db.commit()
    db.refresh(new_room)  # Reload from DB to populate server-set fields (e.g. id).
    return new_room


# ---------------------------------------------------------------------------
# GET /rooms/ — List all rooms
# ---------------------------------------------------------------------------

@router.get(
    "/",
    response_model=List[RoomResponse],
    status_code=status.HTTP_200_OK,
    summary="List all rooms",
    description=(
        "Retrieve every accommodation room currently registered in the system. "
        "Results are returned in insertion order."
    ),
)
def list_rooms(
    db: Session = Depends(get_db),
) -> List[Room]:
    """
    Fetch all Room rows from the database.

    Args:
        db: Injected database session (one per request).

    Returns:
        A list of ``Room`` ORM instances (may be empty).
    """
    return db.query(Room).all()
