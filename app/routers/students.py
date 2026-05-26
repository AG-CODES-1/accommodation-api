"""
routers/students.py
-------------------
Presentation layer — HTTP endpoints for the Student domain entity.

Routes
------
  POST /students/       Create a new student record.
  GET  /students/       List all student records.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Student
from app.schemas import StudentCreate, StudentResponse

router = APIRouter(
    prefix="/students",
    tags=["Students"],
)


# ---------------------------------------------------------------------------
# POST /students/ — Create a new student
# ---------------------------------------------------------------------------

@router.post(
    "/",
    response_model=StudentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new student",
    description=(
        "Register a new student applicant with their personal details and "
        "accommodation preferences. The server assigns the primary key."
    ),
)
def create_student(
    payload: StudentCreate,
    db: Session = Depends(get_db),
) -> Student:
    """
    Persist a new Student record from the validated request payload.

    Args:
        payload: Validated ``StudentCreate`` schema from the request body.
        db:      Injected database session (one per request).

    Returns:
        The newly created ``Student`` ORM instance.

    Raises:
        HTTPException 400: If a database constraint is violated
                           (e.g. duplicate entry — reserved for future use).
    """
    new_student = Student(
        name=payload.name,
        gender=payload.gender,
        academic_level=payload.academic_level,
        max_budget=payload.max_budget,
        preferred_block=payload.preferred_block,
        study_habit=payload.study_habit,
    )

    db.add(new_student)
    db.commit()
    db.refresh(new_student)  # Reload from DB to populate server-set fields (e.g. id).
    return new_student


# ---------------------------------------------------------------------------
# GET /students/ — List all students
# ---------------------------------------------------------------------------

@router.get(
    "/",
    response_model=List[StudentResponse],
    status_code=status.HTTP_200_OK,
    summary="List all students",
    description=(
        "Retrieve every student applicant currently registered in the system. "
        "Results are returned in insertion order."
    ),
)
def list_students(
    db: Session = Depends(get_db),
) -> List[Student]:
    """
    Fetch all Student rows from the database.

    Args:
        db: Injected database session (one per request).

    Returns:
        A list of ``Student`` ORM instances (may be empty).
    """
    return db.query(Student).all()
