"""
FastAPI app factory. `create_app` (not a module-level `app` singleton) so
tests can build an app against arbitrary `Settings` — in particular the
"missing secrets in a non-dev env raises at startup" test, which needs a
fresh app instance per `Settings` rather than one shared module-level app.

This is the minimal app skeleton this phase adds: the auth router and an
unauthenticated health probe. All case/alert/business routes are Phase 4's
job (see `docs/ROADMAP.md`).
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routes.auth import router as auth_router
from foundation.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # The actual invocation point that closes the "hardcoded JWT secret"
        # landmine (CLAUDE.md) — Settings.validate_secrets() existed before
        # this phase but was never called anywhere. Raising here fails
        # startup loudly instead of booting insecurely.
        settings.validate_secrets()
        yield

    app = FastAPI(title="TraceX API", lifespan=lifespan)
    app.include_router(auth_router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        # Unauthenticated by design: standard health-probe exemption
        # (k8s liveness/readiness checks can't carry a bearer token) — does
        # not violate "auth on every route" (docs/ROADMAP.md invariant),
        # which applies to business/data routes, not infra health checks.
        return {"status": "ok"}

    return app
