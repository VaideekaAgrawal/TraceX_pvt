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
`docs/ROADMAP.md`). Phase 14 adds `alerts_router`/`audit_router`/
`dashboard_router` — the system-wide (not case-scoped) alert list + manual
assignment, unified audit-log query, and Dashboard summary surfaces.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.routes.alerts import router as alerts_router
from api.routes.audit import router as audit_router
from api.routes.auth import router as auth_router
from api.routes.cases import router as cases_router
from api.routes.copilot import router as copilot_router
from api.routes.dashboard import router as dashboard_router
from api.routes.governance import router as governance_router
from api.routes.l2 import router as l2_router
from api.routes.recommendations import router as recommendations_router
from api.routes.reports import router as reports_router
from api.routes.review_queue import router as review_queue_router
from api.routes.watchlist import router as watchlist_router
from db.session import get_db
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
    app.include_router(recommendations_router)
    app.include_router(copilot_router)
    app.include_router(watchlist_router)
    app.include_router(reports_router)
    app.include_router(alerts_router)
    app.include_router(audit_router)
    app.include_router(dashboard_router)
    app.include_router(governance_router)
    app.include_router(review_queue_router)

    # Health probes are unauthenticated by design: standard exemption (k8s
    # liveness/readiness checks can't carry a bearer token) — does not violate
    # "auth on every route" (docs/ROADMAP.md invariant), which applies to
    # business/data routes, not infra health checks.
    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/live")
    def health_live() -> dict[str, str]:
        # Liveness: is the process up and serving? No dependencies — a failing
        # DB must NOT restart the pod (that's readiness's job), or a brief DB
        # blip would cascade into a crash loop (ROADMAP Phase 12).
        return {"status": "alive"}

    @app.get("/health/ready")
    def health_ready(db: Session = Depends(get_db)) -> dict[str, str]:
        # Readiness: can this pod actually serve traffic (DB reachable)? A 503
        # here pulls the pod out of the Service's endpoints without killing it.
        try:
            db.execute(text("SELECT 1"))
        except Exception as exc:  # pragma: no cover - exercised via the 503 path
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "database not reachable"
            ) from exc
        return {"status": "ready"}

    return app
