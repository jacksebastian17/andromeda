"""Versioned localhost API. A standalone process serves persisted research snapshots."""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import Connection
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__, queries
from . import schemas as s
from .database import StorageUnavailable, database_path, make_engine
from .storage import check_revision

DB_WARNING = (
    "Research database unavailable or schema out of date. Check the database path and run migrate."
)


def create_app(path: Path | None = None) -> FastAPI:
    engine = make_engine(path or database_path(), mode="ro")

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.started = datetime.now(UTC)
        application.state.clock = monotonic()
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(
        title="Andromeda Research API",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        description="Read-only views over the local synthetic fixture and paper ledger.",
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET"],
        allow_headers=["Accept"],
    )

    def snapshot() -> Iterator[Connection]:
        with engine.connect() as conn:
            check_revision(conn)
            yield conn

    db = Depends(snapshot)
    prefix = "/api/v1"

    @app.exception_handler(SQLAlchemyError)
    async def db_error(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": DB_WARNING})

    @app.exception_handler(StorageUnavailable)
    async def revision_error(_: Request, exc: StorageUnavailable) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": DB_WARNING})

    @app.get(prefix + "/health", responses={503: {"model": s.Health}})
    def health(request: Request, response: Response) -> s.Health:
        runtime = {
            "version": __version__,
            "started_at": request.app.state.started,
            "uptime_seconds": round(monotonic() - request.app.state.clock, 3),
        }
        try:
            with engine.connect() as conn:
                check_revision(conn)
                return queries.health(conn, runtime)
        except (SQLAlchemyError, StorageUnavailable):
            response.status_code = 503
            return s.Health.model_validate(
                {
                    **runtime,
                    "database": "unavailable",
                    "source_status": "unavailable",
                    "last_ingestion_at": None,
                    "last_evaluation_at": None,
                    "missing_inputs": None,
                    "warnings": [DB_WARNING],
                }
            )

    @app.get(prefix + "/overview")
    def overview(conn: Annotated[Connection, db]) -> s.Overview:
        return queries.overview(conn)

    @app.get(prefix + "/events")
    def events(conn: Annotated[Connection, db]) -> list[s.EventView]:
        return queries.events(conn)

    @app.get(prefix + "/events/{event_id}")
    def event(event_id: str, conn: Annotated[Connection, db]) -> s.EventDetail:
        result = queries.event_detail(conn, event_id)
        if result is None:
            raise HTTPException(404, "Unknown research event.")
        return result

    @app.get(prefix + "/research/models")
    def models(conn: Annotated[Connection, db]) -> list[s.ModelView]:
        return queries.models(conn)

    @app.get(prefix + "/research/evaluations")
    def evaluations(conn: Annotated[Connection, db]) -> s.Evaluations:
        return queries.evaluations(conn)

    @app.get(prefix + "/portfolio")
    def portfolio(conn: Annotated[Connection, db]) -> s.Portfolio:
        result = queries.portfolio(conn)
        if result is None:
            raise HTTPException(404, "Paper ledger has not been initialized. Run ingest.")
        return result

    return app


app = create_app()
