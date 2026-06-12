"""RegWatch FastAPI application factory.

The backend is the only component that talks to Supabase / Qdrant / Groq / embeddings.
The Streamlit frontend calls this API over HTTP. Hosted free on Render (+ UptimeRobot
keep-alive); 1 worker because APScheduler is in-process (see docs/BUILD_PLAN.md).
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import VERSION, config
from api.routers import health


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Scheduler + service warmup are wired in a later phase. Kept empty so the
    # skeleton boots cleanly on Render for the Day-1 deploy de-risk.
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="RegWatch API", version=VERSION, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router, tags=["health"])
    return app


app = create_app()
