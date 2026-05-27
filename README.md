<div align="center">

# 🏛️ HostelSync Allocation API

### A Production-Ready, Algorithmic University Housing Allocation System

[![CI](https://github.com/AG-CODES-1/accommodation-api/actions/workflows/ci.yml/badge.svg)](https://github.com/AG-CODES-1/accommodation-api/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=flat&logo=fastapi&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=flat)

</div>

---

**HostelSync** is a backend API that solves the real-world complexity of university student accommodation allocation. It moves beyond simple CRUD — implementing a full **event-driven state machine** that intelligently matches students to rooms based on budget, gender compatibility, and availability, and automatically promotes waitlisted students the moment a bed becomes free.

Built with **Domain-Driven Design (DDD)** principles, the codebase is structured around clean separation of concerns: the allocation algorithm, HTTP routing, data persistence, and authentication each live in their own layer.

---

## ✨ Key Features

### 🔄 Waitlist State Machine
Every allocation moves through a defined lifecycle — `PENDING` → `CONFIRMED` → `CANCELLED`, or `WAITLISTED` → `PENDING` on promotion. No student is ever simply rejected; if no room is available, they are queued automatically and their position is preserved.

### ⚡ Auto-Promotion Engine
When an allocation is cancelled, the system **immediately** queries the waitlist for the oldest eligible student — checking budget and gender compatibility against the newly freed room — and promotes them atomically within the **same database transaction**. No room goes to waste.

### 🔒 JWT Authentication
Sensitive allocation and cancellation endpoints are secured with **OAuth2 Bearer token** authentication using HS256-signed JWTs. The Swagger UI (`/docs`) ships with a built-in **Authorize** button for frictionless testing.

### 🛡️ Concurrency-Safe by Design
The matchmaker uses **`SELECT … FOR UPDATE`** row-level locking to prevent race conditions under concurrent requests — two students can never be allocated to the same last available bed simultaneously.

### 🧪 Automated Integration Tests
A full end-to-end test suite verifies the entire allocation lifecycle — from room creation through waitlisting to promotion — against an isolated **in-memory SQLite database**, ensuring the real data is never touched during testing.

### 🚀 CI/CD Pipeline
Every push to `main` triggers a **GitHub Actions** workflow that installs all dependencies and runs the full Pytest suite automatically, ensuring regressions are caught before they reach production.

---

## 🗂️ Project Structure

```
accommodation-api/
├── app/
│   ├── algorithms/
│   │   └── matchmaker.py      # Core allocation & cancellation business logic
│   ├── routers/
│   │   ├── admin.py           # JWT login endpoint
│   │   ├── allocations.py     # Allocation trigger & cancellation routes
│   │   ├── rooms.py           # Room CRUD routes
│   │   └── students.py        # Student CRUD routes
│   ├── auth.py                # OAuth2 scheme, token creation, admin dependency
│   ├── database.py            # SQLAlchemy engine, session factory, Base
│   ├── main.py                # FastAPI app entry point
│   ├── models.py              # ORM table definitions & enums
│   └── schemas.py             # Pydantic request/response schemas
├── tests/
│   └── test_allocations.py    # End-to-end integration test suite
├── .github/workflows/
│   └── ci.yml                 # GitHub Actions CI pipeline
└── README.md
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **API Framework** | [FastAPI](https://fastapi.tiangolo.com/) |
| **ORM** | [SQLAlchemy](https://www.sqlalchemy.org/) |
| **Database** | SQLite (MVP) — swap `DATABASE_URL` for PostgreSQL in production |
| **Authentication** | [python-jose](https://github.com/mpdavis/python-jose) · OAuth2 + HS256 JWT |
| **Data Validation** | [Pydantic v2](https://docs.pydantic.dev/) |
| **Testing** | [Pytest](https://pytest.org/) · [HTTPX](https://www.python-httpx.org/) |
| **CI/CD** | [GitHub Actions](https://github.com/features/actions) |

---

## ⚙️ API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/` | — | Health check |
| `POST` | `/students/` | — | Register a student applicant |
| `GET` | `/students/` | — | List all students |
| `POST` | `/rooms/` | — | Register a room |
| `GET` | `/rooms/` | — | List all rooms |
| `POST` | `/admin/login` | — | Obtain a JWT Bearer token |
| `POST` | `/allocations/` | 🔒 Admin | Run the matchmaker for a student |
| `DELETE` | `/allocations/{id}` | 🔒 Admin | Cancel allocation + auto-promote waitlist |

---

## 🚀 Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/AG-CODES-1/accommodation-api.git
cd accommodation-api
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv

# Windows
.\.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install fastapi uvicorn sqlalchemy "python-jose[cryptography]" python-multipart pytest httpx
```

### 4. Run the development server

```bash
uvicorn app.main:app --reload
```

The API will be live at **`http://127.0.0.1:8000`**.
Interactive documentation (Swagger UI) is available at **`http://127.0.0.1:8000/docs`**.

---

## 🧪 Running the Tests

```bash
pytest tests/ -v
```

The test suite uses an **in-memory SQLite database** — no setup required and no data is written to disk.

**What the integration test verifies:**
1. ✅ Student A is allocated a room → status `PENDING`
2. ✅ Student B is waitlisted when the room is full → status `WAITLISTED`
3. ✅ Cancelling Student A's allocation automatically promotes Student B → status `PENDING`

---

## 🔐 Authentication Flow

1. `POST /admin/login` with `username=admin` and `password=password123`
2. Copy the `access_token` from the response
3. Click **Authorize 🔒** in the Swagger UI and paste the token
4. All protected endpoints (`/allocations/`) will now accept your requests

> **Note:** The hardcoded admin credentials are for MVP development only. In production, replace with a hashed-password lookup against a User database table.

---

## 🧠 Allocation Algorithm

```
POST /allocations/  { "student_id": 1 }
          │
          ▼
   Fetch Student ──── not found ──► 404
          │
          ▼
   Query rooms WHERE:
     • current_occupants < capacity
     • price <= student.max_budget
     • gender_restriction compatible
   ORDER BY price ASC  (best-fit)
   .with_for_update()  (row lock)
          │
     ┌────┴────┐
   FOUND    NOT FOUND
     │          │
     ▼          ▼
  PENDING   WAITLISTED
  room_id   room_id = null
  assigned
```

---

## 📄 License

This project is licensed under the **MIT License**.
