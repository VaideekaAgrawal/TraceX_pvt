---
name: verify
description: Project verify recipe for TraceX — how to stand up backend + frontend locally and drive real flows through them. Bootstrapped Phase 13 (2026-07-14); extend as later phases add surfaces (dashboard, workspace, AI features).
---

# TraceX local verify recipe

Two independent processes: FastAPI backend (`backend/`) and Next.js frontend (`frontend/`). No CORS is configured on the backend by design — the frontend never calls it directly from the browser, only server-side via its own BFF Route Handlers. Drive flows through the frontend's real HTTP surface (`curl` with a cookie jar works fine and exercises the same BFF routes a browser would hit) rather than importing modules directly.

## Backend

`backend/.venv` is currently **broken** (missing `pandas` — a pre-existing environment issue, not caused by any diff). Use `backend/.venv313` instead, which has the full dependency set:

```bash
cd backend
source .venv313/bin/activate
uvicorn api.app:create_app --factory --port 8000 &
curl -s http://localhost:8000/healthz   # {"status":"ok"}
```

Needs a `.env` (copy `.env.example`, gitignored) and at least one seeded user for anything auth-gated:

```bash
python scripts/create_user.py --username verifyuser --email verifyuser@example.invalid \
  --password 'VerifyPass123!' --full-name "Verify User" --role INVESTIGATOR
```

Uses the real SQLite DB at repo-root `data/tracex.db` unless `.env` points elsewhere — fine for throwaway verify users, just don't leave them seeded in a way that looks like real data (use an obviously-fake username, they're gitignored anyway).

## Frontend

Requires **Node >= 20.9** (Next.js 16) — the repo's default Node is 18.20.8, which Next 16 rejects outright. Use `nvm`:

```bash
source ~/.nvm/nvm.sh && nvm use 20.20.2
cd frontend
cp .env.example .env.local   # BACKEND_API_URL=http://localhost:8000, gitignored
npm run dev &
```

## Driving auth flows (curl + cookie jar, no browser needed for server-side checks)

```bash
COOKIES=/tmp/cookies.txt
# Login
curl -s -c "$COOKIES" -X POST http://localhost:3000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"verifyuser","password":"VerifyPass123!"}'
# -> {"role":"INVESTIGATOR","user_id":"..."}, httpOnly cookie set, raw JWT never in the body

# Authenticated request
curl -s -b "$COOKIES" -o /dev/null -w "%{http_code}\n" http://localhost:3000/dashboard

# Redirect-target / open-redirect checks — inspect the Location header, don't follow it
curl -sD - -b "$COOKIES" -o /dev/null "http://localhost:3000/login?next=//evil.com" | grep -i ^location:
```

**Gotcha for anything touching the `next`/redirect-target logic**: string-prefix checks (`next.startsWith("//")`) are not enough — browsers (via the WHATWG URL parser, which `window.location.assign`/`redirect()` actually use) normalize a leading backslash and embedded tab/newline/CR characters into an off-origin `//host` *before* resolving. Verify with Node directly, not just by eyeballing the check:

```bash
node -e 'console.log(new URL("/\\evil.com", "http://localhost:3000").href)'   # http://evil.com/
node -e 'console.log(new URL("/\t/evil.com", "http://localhost:3000").href)'  # http://evil.com/
```

The real fix is resolving `next` through the actual `URL` constructor against a sentinel origin and comparing origins (see `frontend/src/lib/auth/redirect.ts`), not re-deriving WHATWG normalization rules by hand.

## Simulating a backend outage (for anything touching error-handling/resilience)

```bash
pkill -f "uvicorn api.app:create_app"
# then hit the frontend with a still-valid cookie — should degrade gracefully,
# not force-logout or destroy the session cookie
```

## Cleanup

```bash
pkill -f "uvicorn api.app:create_app"
pkill -f "next dev"
```

Throwaway `.env`/`.env.local` and any seeded verify users are gitignored — no need to clean those up, but don't `git add` them by accident.
