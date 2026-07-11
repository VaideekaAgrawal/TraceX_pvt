"""
FastAPI app factory. `create_app` (not a module-level `app` singleton) so
tests can build an app against arbitrary `Settings` — in particular the
"missing secrets in a non-dev env raises at startup" test, which needs a
fresh app instance per `Settings` rather than one shared module-level app.

Phase 2 added the auth router and an unauthenticated health probe. Phase 5
added `cases_router` — the L1 triage HTTP surface and this backend's first
business-logic routes beyond `/auth/*`. Phase 6 adds `l2_router` — the L2
deep-investigation surface, mounted under the same `/cases` prefix as a
separate router file rather than growing `cases.py` further (see
`docs/ROADMAP.md`).
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routes.auth import router as auth_router
from api.routes.cases import router as cases_router
from api.routes.l2 import router as l2_router
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
    # Stored so request-scoped dependencies (`foundation.auth.
    # get_app_settings`) can read back whatever `Settings` was actually
    # passed to this `create_app` call, instead of routes falling back to
    # `foundation.security`'s module-level `get_settings()` singleton
    # (code review, Phase 2: that fallback silently ignored a non-default
    # `settings=` argument for the real JWT sign/verify path).
    app.state.settings = settings
    app.include_router(auth_router)
    app.include_router(cases_router)
    app.include_router(l2_router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        # Unauthenticated by design: standard health-probe exemption
        # (k8s liveness/readiness checks can't carry a bearer token) — does
        # not violate "auth on every route" (docs/ROADMAP.md invariant),
        # which applies to business/data routes, not infra health checks.
        return {"status": "ok"}

    return app
