"""
schemas.py
----------
Application layer — Pydantic request/response contracts.

This module defines the data shapes that cross the API boundary.
It deliberately imports the Python enums from models.py so that the
valid values are always in sync with the database constraints — there
is one single source of truth.

Schema hierarchy per entity
───────────────────────────
  <Entity>Base      — shared fields used by both Create and Response
  <Entity>Create    — inbound payload (POST /entities)
  <Entity>Response  — outbound payload (GET /entities, POST response body)

No SQLAlchemy imports or ORM logic should appear in this file.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# Re-use the same Python enums defined alongside the ORM models so that
# valid values stay in sync with the database column constraints.
from app.models import (
    AcademicLevelEnum,
    AllocationStatusEnum,
    GenderEnum,
    GenderRestrictionEnum,
    StudyHabitEnum,
)


# ===========================================================================
# Student schemas
# ===========================================================================

class StudentBase(BaseModel):
    """Fields shared between the Create and Response schemas for Student."""

    name: str = Field(
        ...,
        min_length=2,
        max_length=255,
        description="Full legal name of the student.",
        examples=["Amara Osei"],
    )
    gender: GenderEnum = Field(
        ...,
        description="Student's gender — used to enforce room gender restrictions.",
        examples=[GenderEnum.FEMALE],
    )
    academic_level: AcademicLevelEnum = Field(
        ...,
        description="Current academic standing using the 100–500 level system.",
        examples=[AcademicLevelEnum.L_200],
    )
    max_budget: float = Field(
        ...,
        gt=0,
        description="Maximum monthly accommodation budget in local currency. Must be positive.",
        examples=[850.00],
    )
    preferred_block: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Preferred residence block name (e.g. 'Block A'). Leave null if no preference.",
        examples=["Block A"],
    )
    study_habit: StudyHabitEnum = Field(
        default=StudyHabitEnum.MODERATE,
        description="Self-reported study habit used for roommate compatibility scoring.",
        examples=[StudyHabitEnum.QUIET],
    )

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, v: str) -> str:
        """Reject strings that are only whitespace."""
        if not v.strip():
            raise ValueError("name must not be blank or whitespace-only.")
        return v.strip()


class StudentCreate(StudentBase):
    """
    Inbound payload for POST /students.

    Inherits all fields from StudentBase. No extra fields are accepted
    from the client — the database assigns the primary key.
    """
    model_config = {"extra": "forbid"}  # Reject unknown fields immediately.


class StudentResponse(StudentBase):
    """
    Outbound representation of a persisted Student record.

    Adds the server-assigned `id` that is unavailable at creation time.
    """
    id: int = Field(..., description="Auto-assigned surrogate primary key.", examples=[1])

    model_config = {"from_attributes": True}


# ===========================================================================
# Room schemas
# ===========================================================================

class RoomBase(BaseModel):
    """Fields shared between the Create and Response schemas for Room."""

    block_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Name of the residence block, e.g. 'Block A', 'North Wing'.",
        examples=["Block A"],
    )
    room_number: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Room identifier within its block, e.g. '101', 'A12'.",
        examples=["101"],
    )
    capacity: int = Field(
        ...,
        ge=1,
        description="Maximum number of students that can occupy this room.",
        examples=[4],
    )
    current_occupants: int = Field(
        default=0,
        ge=0,
        description="Current number of confirmed occupants. Defaults to 0 for a new room.",
        examples=[2],
    )
    price: float = Field(
        ...,
        gt=0,
        description="Monthly accommodation fee in local currency. Must be positive.",
        examples=[750.00],
    )
    gender_restriction: GenderRestrictionEnum = Field(
        default=GenderRestrictionEnum.MIXED,
        description="Occupancy gender restriction applied to this room.",
        examples=[GenderRestrictionEnum.FEMALE_ONLY],
    )

    @model_validator(mode="after")
    def occupants_must_not_exceed_capacity(self) -> "RoomBase":
        """Ensure current_occupants is never greater than capacity."""
        if self.current_occupants > self.capacity:
            raise ValueError(
                f"current_occupants ({self.current_occupants}) cannot exceed "
                f"capacity ({self.capacity})."
            )
        return self


class RoomCreate(RoomBase):
    """
    Inbound payload for POST /rooms.

    Inherits all fields from RoomBase. Typically `current_occupants`
    will be omitted by the client and will default to 0.
    """
    model_config = {"extra": "forbid"}


class RoomResponse(RoomBase):
    """
    Outbound representation of a persisted Room record.

    Adds the server-assigned `id`. Also exposes a computed availability
    property as a convenience for clients.
    """
    id: int = Field(..., description="Auto-assigned surrogate primary key.", examples=[1])

    model_config = {"from_attributes": True}

    @property
    def is_available(self) -> bool:
        """True when at least one bed remains unfilled."""
        return self.current_occupants < self.capacity

    @property
    def available_beds(self) -> int:
        """Number of remaining open beds."""
        return self.capacity - self.current_occupants


# ===========================================================================
# Allocation schemas
# ===========================================================================

class AllocationBase(BaseModel):
    """Fields shared between the Create and Response schemas for Allocation."""

    student_id: int = Field(
        ...,
        gt=0,
        description="Primary key of the Student being allocated.",
        examples=[1],
    )
    room_id: Optional[int] = Field(
        default=None,
        gt=0,
        description=(
            "Primary key of the Room being assigned. "
            "Null for WAITLISTED allocations where no room has been assigned yet."
        ),
        examples=[3],
    )


class AllocationCreate(AllocationBase):
    """
    Inbound payload for POST /allocations.

    Only the foreign keys are required from the client.  The server
    assigns the timestamp and sets status to PENDING automatically.
    Explicit overrides are intentionally not exposed here — status
    transitions happen via dedicated PATCH endpoints.
    """
    model_config = {"extra": "forbid"}


class AllocationResponse(AllocationBase):
    """
    Outbound representation of a persisted Allocation record.

    Exposes the server-assigned id, UTC timestamp, and current status
    in addition to the FK fields inherited from AllocationBase.
    """
    id: int = Field(
        ...,
        description="Auto-assigned surrogate primary key.",
        examples=[1],
    )
    timestamp: datetime = Field(
        ...,
        description="UTC datetime when this allocation record was created.",
        examples=["2024-09-01T08:30:00Z"],
    )
    status: AllocationStatusEnum = Field(
        ...,
        description="Current lifecycle state of this allocation.",
        examples=[AllocationStatusEnum.PENDING],
    )

    model_config = {"from_attributes": True}


# ===========================================================================
# Utility / generic response schemas
# ===========================================================================

class MessageResponse(BaseModel):
    """Generic envelope for simple success/informational messages."""

    message: str = Field(..., description="Human-readable status message.", examples=["Operation successful."])

    model_config = {"from_attributes": True}
