"""
models.py
---------
Domain persistence layer — SQLAlchemy ORM table definitions.

Three core tables are defined here:
  • Student   — applicant profile and accommodation preferences
  • Room       — available accommodation units
  • Allocation — the matchmaking result linking a Student to a Room

No FastAPI schemas, routing, or business logic lives in this file.
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import relationship

from app.database import Base


# ===========================================================================
# Enumerated types
# ===========================================================================

class GenderEnum(str, enum.Enum):
    """Biological / preferred gender used for room-restriction matching."""
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class AcademicLevelEnum(str, enum.Enum):
    """Academic standing of the student applicant (100–500 level system)."""
    L_100 = "100_level"
    L_200 = "200_level"
    L_300 = "300_level"
    L_400 = "400_level"
    L_500 = "500_level"  # Postgraduate / masters level.


class StudyHabitEnum(str, enum.Enum):
    """
    Self-reported study-habit preference.

    Used by the allocation algorithm to match compatible roommates and
    suitable room environments.
    """
    QUIET = "quiet"           # Prefers a silent study environment.
    MODERATE = "moderate"     # Comfortable with some ambient noise.
    NIGHT_OWL = "night_owl"   # Studies late; tolerates/prefers activity at night.
    SOCIAL = "social"         # Studies in groups; high-activity preference.


class AllocationStatusEnum(str, enum.Enum):
    """Lifecycle state of an allocation record."""
    PENDING = "pending"         # Created but awaiting confirmation.
    CONFIRMED = "confirmed"     # Accepted by the student or administrator.
    CANCELLED = "cancelled"     # Revoked before move-in.
    WAITLISTED = "waitlisted"   # Room full; student queued for next availability.


class GenderRestrictionEnum(str, enum.Enum):
    """Occupancy restriction applied at the room level."""
    MALE_ONLY = "male_only"
    FEMALE_ONLY = "female_only"
    MIXED = "mixed"             # No gender restriction.


# ===========================================================================
# ORM Models
# ===========================================================================

class Student(Base):
    """
    Represents a student applicant seeking accommodation.

    Each Student record captures both identity information and personal
    preferences that the allocation algorithm will use to find the best
    matching Room.
    """
    __tablename__ = "students"

    # ------------------------------------------------------------------
    # Primary key
    # ------------------------------------------------------------------
    id = Column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True,
        comment="Surrogate primary key.",
    )

    # ------------------------------------------------------------------
    # Identity fields
    # ------------------------------------------------------------------
    name = Column(
        String(255),
        nullable=False,
        comment="Full legal name of the student.",
    )
    gender = Column(
        Enum(GenderEnum),
        nullable=False,
        comment="Student's gender — used to enforce room gender restrictions.",
    )
    academic_level = Column(
        Enum(AcademicLevelEnum),
        nullable=False,
        comment="Current academic standing (e.g., freshman, postgraduate).",
    )

    # ------------------------------------------------------------------
    # Preference fields (inputs to the allocation algorithm)
    # ------------------------------------------------------------------
    max_budget = Column(
        Float,
        nullable=False,
        comment="Maximum monthly accommodation budget in local currency.",
    )
    preferred_block = Column(
        String(100),
        nullable=True,
        comment="Preferred residence block name, e.g. 'Block A'. Optional.",
    )
    study_habit = Column(
        Enum(StudyHabitEnum),
        nullable=False,
        default=StudyHabitEnum.MODERATE,
        comment="Self-reported study habit used for roommate compatibility scoring.",
    )

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------
    allocations = relationship(
        "Allocation",
        back_populates="student",
        cascade="all, delete-orphan",
        doc="All allocation attempts associated with this student.",
    )

    def __repr__(self) -> str:
        return (
            f"<Student id={self.id!r} name={self.name!r} "
            f"level={self.academic_level!r}>"
        )


# ---------------------------------------------------------------------------

class Room(Base):
    """
    Represents a physical accommodation unit available for allocation.

    Rooms belong to a named block and carry capacity, pricing, and
    restriction metadata consumed by the allocation engine.
    """
    __tablename__ = "rooms"

    # ------------------------------------------------------------------
    # Primary key
    # ------------------------------------------------------------------
    id = Column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True,
        comment="Surrogate primary key.",
    )

    # ------------------------------------------------------------------
    # Location fields
    # ------------------------------------------------------------------
    block_name = Column(
        String(100),
        nullable=False,
        index=True,
        comment="Name of the residence block, e.g. 'Block A', 'North Wing'.",
    )
    room_number = Column(
        String(20),
        nullable=False,
        comment="Room identifier within its block, e.g. '101', 'A12'.",
    )

    # ------------------------------------------------------------------
    # Capacity and occupancy fields
    # ------------------------------------------------------------------
    capacity = Column(
        Integer,
        nullable=False,
        comment="Maximum number of students that can occupy this room.",
    )
    current_occupants = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Current number of confirmed occupants. Must not exceed capacity.",
    )

    # ------------------------------------------------------------------
    # Financial and restriction fields
    # ------------------------------------------------------------------
    price = Column(
        Float,
        nullable=False,
        comment="Monthly accommodation fee in local currency.",
    )
    gender_restriction = Column(
        Enum(GenderRestrictionEnum),
        nullable=False,
        default=GenderRestrictionEnum.MIXED,
        comment="Occupancy gender restriction applied to this room.",
    )

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------
    allocations = relationship(
        "Allocation",
        back_populates="room",
        cascade="all, delete-orphan",
        doc="All allocation records associated with this room.",
    )

    def __repr__(self) -> str:
        return (
            f"<Room id={self.id!r} block={self.block_name!r} "
            f"number={self.room_number!r} occupancy={self.current_occupants}/{self.capacity}>"
        )


# ---------------------------------------------------------------------------

class Allocation(Base):
    """
    Represents the outcome of the matching algorithm for a single Student.

    An Allocation record is the join entity between Student and Room.
    It records *when* the match was made and its current *status* in the
    confirmation workflow.

    Business rules (enforced at the service layer, not here):
      - A student should have at most one CONFIRMED allocation at a time.
      - Creating an Allocation does NOT automatically increment
        Room.current_occupants; that is the responsibility of the domain
        service / use-case handler.
    """
    __tablename__ = "allocations"

    # ------------------------------------------------------------------
    # Primary key
    # ------------------------------------------------------------------
    id = Column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True,
        comment="Surrogate primary key.",
    )

    # ------------------------------------------------------------------
    # Foreign keys
    # ------------------------------------------------------------------
    student_id = Column(
        Integer,
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Reference to the allocated Student.",
    )
    room_id = Column(
        Integer,
        ForeignKey("rooms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Reference to the allocated Room.",
    )

    # ------------------------------------------------------------------
    # Audit fields
    # ------------------------------------------------------------------
    timestamp = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="UTC timestamp of when this allocation was first created.",
    )

    # ------------------------------------------------------------------
    # Status field
    # ------------------------------------------------------------------
    status = Column(
        Enum(AllocationStatusEnum),
        nullable=False,
        default=AllocationStatusEnum.PENDING,
        comment="Current lifecycle state of this allocation.",
    )

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------
    student = relationship(
        "Student",
        back_populates="allocations",
        doc="The student this allocation belongs to.",
    )
    room = relationship(
        "Room",
        back_populates="allocations",
        doc="The room assigned by this allocation.",
    )

    def __repr__(self) -> str:
        return (
            f"<Allocation id={self.id!r} student_id={self.student_id!r} "
            f"room_id={self.room_id!r} status={self.status!r}>"
        )
