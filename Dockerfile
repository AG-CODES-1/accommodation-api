# ── Base image ────────────────────────────────────────────────────────────────
# python:3.10-slim keeps the image small while providing a stable, well-supported
# Python runtime. The slim variant omits build tools and documentation that are
# not needed at runtime.
FROM python:3.10-slim

# ── Environment hygiene ───────────────────────────────────────────────────────
# PYTHONDONTWRITEBYTECODE — prevents Python from writing .pyc files to disk.
# PYTHONUNBUFFERED       — ensures stdout/stderr are flushed immediately,
#                          which is critical for seeing logs in real time.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ── Working directory ─────────────────────────────────────────────────────────
WORKDIR /app

# ── Dependency installation ───────────────────────────────────────────────────
# Copy requirements first so Docker can cache this layer independently of the
# application code. Rebuilds triggered by code changes will skip this step.
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ──────────────────────────────────────────────────────────
# Copy the rest of the project after installing dependencies so that routine
# code edits don't invalidate the (heavier) dependency cache layer.
COPY . .

# ── Network ───────────────────────────────────────────────────────────────────
EXPOSE 8000

# ── Default command ───────────────────────────────────────────────────────────
# Bind to 0.0.0.0 so the server is reachable outside the container.
# For production, consider adding --workers 4 (Gunicorn) or using a process
# manager; for the MVP a single Uvicorn worker is sufficient.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
