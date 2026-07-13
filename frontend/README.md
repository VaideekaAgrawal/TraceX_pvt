# TraceX Frontend

The rebuilt frontend, per `docs/FRONTEND_ROADMAP.md` and `docs/FRONTEND_PLAN.md`. See those docs before writing code here; this README is "how to run it," not "what to build."

Three pages only: **Dashboard → Investigation Workspace → My Center**. No page-per-data-type navigation (`/graph`, `/anomaly`, etc.) — see `docs/FRONTEND_PLAN.md` §0.

## Architecture note: BFF pattern

The FastAPI backend (`backend/`) has no CORS middleware configured and returns the login JWT as a JSON body, not a cookie. This app never calls the backend directly from the browser — every backend call goes through this app's own Route Handlers (`src/app/api/**/route.ts`), which run server-side, hold the backend base URL (`BACKEND_API_URL`), and set the JWT as an httpOnly cookie on this app's own origin. See `src/lib/api/backend.ts` and `src/lib/auth/session.ts`.

## Layout

```
frontend/
  src/
    app/
      (app)/          # Route group for the three authenticated pages —
                       # layout.tsx here is the auth guard + TopNav shell.
      api/auth/        # BFF Route Handlers: login, logout, session-expired.
      login/           # Public login page.
    components/
      auth/            # Login form (client).
      shell/           # TopNav, notification bell, user menu.
      ui/              # shadcn/ui primitives.
    lib/
      api/             # Backend fetch helpers + typed client + response types.
      auth/            # Session cookie contract, AuthProvider/useAuth/useRole.
    hooks/             # Convenience re-exports of the auth hooks.
    proxy.ts           # Route guard (Next.js 16's replacement for
                       # middleware.ts — see that file's docstring).
```

## Setup

```bash
cd frontend
cp .env.example .env.local   # set BACKEND_API_URL if not localhost:8000
npm install
npm run dev
```

Requires Node >= 20.9 (Next.js 16). Requires a running backend (`cd backend && uvicorn api.app:create_app --factory --reload`) with at least one seeded user — see `backend/scripts/create_user.py`.

## Running checks (same gates CI runs)

```bash
npm run lint
npm run build   # also runs the TypeScript check
```
