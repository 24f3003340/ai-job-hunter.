from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import Base, engine
from .routers import applications, auth, jobs, profile

@asynccontextmanager
async def lifespan(_: FastAPI):
    # Dev convenience only; production uses Alembic migrations.
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="AI Job Hunter", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

for r in (auth.router, profile.router, jobs.router, applications.router):
    app.include_router(r, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok"}
