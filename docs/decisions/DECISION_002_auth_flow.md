# DECISION 002: Auth Flow Design

## ARCHITECT proposes:

### JWT Delivery: httpOnly Cookies
JWT tokens are set as httpOnly cookies on login response, never returned in the response body
or stored in localStorage. This is a non-negotiable security requirement from CLAUDE.md.

Cookie configuration:
- `httponly=True` — JavaScript cannot access the token
- `samesite="lax"` — CSRF protection while allowing top-level navigations
- `secure=True` in production (HTTPS only), `False` in local dev
- `path="/"` — cookie sent on all routes
- `max_age=3600` — 1 hour expiry matching JWT expiry

### Registration Flow
1. User submits email, password, `tos_accepted: true`
2. Server validates: email format, password strength (min 8 chars), ToS accepted
3. Server hashes password with bcrypt (12 rounds)
4. Server creates user with `tos_accepted_at = now()`, `email_verified = false`
5. Server generates `email_verification_token` (random 32-byte hex)
6. Server "sends" verification email (MVP: log token to stdout)
7. Server returns 201 with user data (no auto-login)

### Login Flow
1. User submits email + password
2. Server verifies password against bcrypt hash
3. Server creates JWT with `sub: user_id`, `exp: now + 60min`
4. Server sets httpOnly cookie with JWT
5. Server returns 200 with basic user info

### Email Verification Flow (MVP: stub)
1. On registration, generate random token, store in `email_verification_token` column
2. Log the verification URL to stdout: `http://localhost:5173/verify?token={token}`
3. `POST /auth/verify-email` with `{token}` → set `email_verified = true`, clear token
4. Real email sending (SendGrid/SES) deferred to Week 4

### Password Reset Flow (MVP: stub)
1. `POST /auth/request-password-reset` with `{email}` → generate reset token, store in
   `password_reset_token` + `password_reset_expires = now + 1 hour`
2. Log reset URL to stdout: `http://localhost:5173/reset-password?token={token}`
3. `POST /auth/reset-password` with `{token, new_password}` → verify token not expired,
   hash new password, clear token
4. Always return 200 on request (don't leak whether email exists)

### Auth Dependency
`get_current_user` reads JWT from `access_token` cookie. Decodes with `python-jose`.
Returns user object or raises 401.

### Rate Limiting (MVP: simple in-memory)
- Login: max 5 attempts per email per 15 minutes (prevent brute force)
- Registration: max 3 per IP per hour
- MVP: track in-memory (dict), no Redis needed yet. This resets on server restart, acceptable for MVP.

## ADVERSARY attacks:

### Attack 1: Cookie not set on cross-origin requests
The frontend (Vite on :5173) and backend (FastAPI on :8000) are different origins.
`Set-Cookie` won't work unless CORS is configured with `allow_credentials=True` AND
the frontend sends `withCredentials: true`. If either is missing, the cookie silently
fails and every authenticated request returns 401.

**Failure scenario:** Developer tests auth in Postman (works), deploys frontend, every
user gets 401 on dashboard. The cookie was never set because the browser's CORS policy
blocked it.

### Attack 2: No CSRF protection with cookie-based auth
httpOnly cookies are sent automatically on every request. If the attacker hosts a page
that triggers `POST /videos/upload` or `DELETE /videos/{id}`, the browser sends the
cookie. SameSite=Lax only protects against cross-site POST from forms, not all scenarios.

**Failure scenario:** An attacker links a user to a malicious page. The page fires
`fetch('https://api.clipforge.com/videos/123', {method:'DELETE'})`. The cookie is
sent, and the user's video is deleted.

### Attack 3: Verification/reset tokens predictable or unbounded
If tokens are generated with weak randomness or never expire, they become an attack
surface. An attacker brute-forces the 32-byte hex token space. Or a password reset
token issued 6 months ago still works.

**Failure scenario:** A leaked database backup contains unexpired reset tokens.
Attacker uses them to reset passwords and take over accounts.

## JUDGE decides:

**Verdict: Approved with required modifications.**

1. **CORS config is critical.** ARCHITECT must configure CORS middleware with
   `allow_credentials=True`, explicit origin (`http://localhost:5173`), and the frontend
   must use `withCredentials: true`. This is not optional — test it E2E before marking
   auth as done.

2. **CSRF: SameSite=Lax is sufficient for MVP.** The Lax policy blocks cross-origin POST
   from foreign sites, which covers the main attack vector. State-changing GET requests
   don't exist in this API (all mutations are POST/PUT/DELETE). Full CSRF token implementation
   is deferred. **Accepted tradeoff:** No custom CSRF token for now. Revisit if the app
   exposes GET-based mutations.

3. **Token security:** Use `secrets.token_urlsafe(32)` (not `uuid4` or `random`). Password
   reset tokens MUST expire (1 hour). Email verification tokens expire in 24 hours. Both are
   single-use (cleared after successful use). **Required.**

## Implementation notes:
- JWT in httpOnly cookie, SameSite=Lax, Secure in prod
- CORS: `allow_credentials=True`, explicit origin list
- Frontend: `withCredentials: true` on all requests
- Tokens: `secrets.token_urlsafe(32)`, single-use, expiring
- Password reset: 1 hour expiry, always return 200
- Email verification: 24 hour expiry, logged to stdout in MVP
- Registration requires `tos_accepted: true` → sets `tos_accepted_at`
- Rate limiting: in-memory for MVP, 5 login attempts/15min, 3 registrations/hour/IP
