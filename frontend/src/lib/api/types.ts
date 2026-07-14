/**
 * Shapes mirrored from the real backend routes this phase wires up:
 * `POST /auth/login`, `GET /auth/me` (`backend/api/routes/auth.py`).
 *
 * Keep these in lockstep with the backend's Pydantic response models —
 * don't invent fields the backend doesn't actually return.
 */

// `db/enums.py::UserRole` — exactly two roles, string values match the
// backend's `UserRole.value` exactly (`"INVESTIGATOR"` / `"ADMIN_COMPLIANCE"`).
// Do not add a third role here without a corresponding backend change.
export const USER_ROLES = ["INVESTIGATOR", "ADMIN_COMPLIANCE"] as const;
export type UserRole = (typeof USER_ROLES)[number];

export interface LoginRequest {
  username: string;
  password: string;
}

// The raw backend response to `POST /auth/login`. This shape only ever
// exists server-side (inside the Next.js Route Handler that calls the
// backend) — the `access_token` must never be forwarded to client-side JS.
export interface BackendLoginResponse {
  access_token: string;
  token_type: string;
  role: UserRole;
  user_id: string;
}

// What the Next.js `/api/auth/login` Route Handler returns to the browser
// after setting the httpOnly cookie — non-sensitive fields only.
export interface ClientLoginResult {
  role: UserRole;
  user_id: string;
}

// `GET /auth/me` response — the authenticated user's profile, used to seed
// the server-rendered `AuthProvider`.
export interface CurrentUser {
  user_id: string;
  username: string;
  email: string;
  role: UserRole;
  full_name: string;
}
