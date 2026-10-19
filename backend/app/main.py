from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import Base, engine
from .routers import applications, auth, documents, jobs, profile, resumes
from .ratelimit import limit_ip


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Dev convenience only; production schemas are managed exclusively by Alembic.
    if settings.env != "production":
        Base.metadata.create_all(engine)
    yield


app = FastAPI(title="AI Job Hunter", version="0.2.0", lifespan=lifespan,
              dependencies=[limit_ip("all", "rate_limit_default")])
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

@app.exception_handler(DataError)
async def _unstorable_input(_: Request, __: DataError):
    # e.g. PostgreSQL rejects U+0000 in text/JSON (SQLite does not). Never echo the offending value.
    return JSONResponse(status_code=422, content={"detail": "Request contains a value the database cannot store"})


for r in (auth.router, profile.router, jobs.router, documents.router, resumes.router, applications.router):
    app.include_router(r, prefix="/api/v1")


@app.get("/health")
def health():
    """Liveness only: the process is up. Use /health/ready for dependencies."""
    return {"status": "ok"}


@app.get("/health/ready")
def ready():
    """Readiness: database, rate-limit backend and malware scanner. Reports state, never URLs or secrets."""
    from sqlalchemy import text

    from .ratelimit import backend_status
    from .services.uploads import scanner_status

    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    parts = {"database": {"ok": db_ok}, "rate_limit": backend_status(), "malware_scanner": scanner_status()}
    ok = all(p["ok"] for p in parts.values())
    return JSONResponse(status_code=200 if ok else 503, content={"status": "ready" if ok else "degraded", **parts})
