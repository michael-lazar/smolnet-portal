# Spec: Accounts, Sessions & TLS Client Certificates

Status: DRAFT
Date: 2026-07-15

## Overview

Add user accounts to the portal so that visitors can upload or generate TLS
client certificates and have them automatically presented to gemini servers
through the proxy. This unlocks the "identity" half of geminispace
(astrobotany, station, bbs.geminispace.org, etc.) which is currently a dead
end — the portal renders *"This proxy does not support client certificates"*
for every `6x` response.

There are no passwords and no email addresses. **The certificate is the
account.** Possession of the certificate + private key is the only credential,
both at signup and at every subsequent login.

Alongside this, a SQLite database is introduced as the single persistence
layer for the app. It stores users, certificates, sessions, and absorbs the
favicon cache that currently lives in a `shelve` file in the temp directory.

## Goals

- Signup by uploading an existing certificate/key, or by generating a new one
  server-side.
- Login by re-presenting a registered certificate + private key.
- Session-cookie auth backed by SQLite.
- The active certificate is automatically attached to proxied TLS requests
  (gemini, scroll).
- Certificates are downloadable at any time as a PEM bundle.
- `6x` responses from gemini servers render a login/signup call-to-action
  instead of a dead end.
- Favicon cache moves from `shelve` to the same SQLite database.

## Non-goals (for now)

- Per-host or per-path certificate scoping (real gemini clients scope certs to
  a URL prefix; v1 applies the active cert to all proxied TLS requests).
- Passphrase-protected (encrypted) private key uploads.
- Client certs for `gophers://` (TLS gopher) — no server ecosystem uses them.
- Account recovery. If you lose every certificate on your account, the
  account is unrecoverable by design.

## Concepts

### Account model

- A **user** is an anonymous row — no name, no email. Its only meaningful
  content is its set of certificates.
- A user has **one or more certificates**. Any of them (with its private key)
  can be used to log in.
- At most **one certificate is "active"** per user. The active cert is what
  gets attached to proxy requests. A user may also deactivate all certs to
  browse anonymously while staying logged in.
- A certificate fingerprint (SHA-256 over the DER encoding) is **globally
  unique** — one cert can only ever belong to one account, since it doubles
  as the login credential.

### Why login requires the private key

The certificate alone is not a secret — it is presented in the clear(ish) to
every gemini server the user visits. The private key is the actual
credential. Login therefore requires uploading a PEM containing **both** the
certificate and its unencrypted private key; the server verifies the key
matches the certificate's public key before matching the fingerprint against
registered certificates.

Note on trust model: the server must hold the private key anyway in order to
open TLS connections on the user's behalf — this is inherent to a web proxy
and should be stated plainly on the signup page.

## User flows

### Signup — upload

1. `GET /auth/signup` — page offers two paths: *upload* or *generate*.
2. User uploads a PEM file (single file containing cert + key, or two file
   inputs: cert required, key required if not bundled).
3. Server validates (see *Certificate validation*), rejects if the
   fingerprint is already registered ("already registered — log in instead",
   linking to login).
4. Creates `user`, creates `certificate` (auto-activated, `source=uploaded`),
   creates session, sets cookie, redirects to the account page (or `next`).

### Signup — generate

1. Same page, generate form: Common Name (required, shown to gemini servers)
   and validity period (1 / 10 / 50 years, default 10).
2. Server generates an ECDSA P-256 key and a self-signed X.509 cert
   (`subject = issuer = CN=<name>`, random serial, `notBefore = now − 1 day`
   for clock skew, SHA-256 signature).
3. Creates user + certificate (auto-activated, `source=generated`), session,
   cookie.
4. Redirects to the account page with a prominent one-time banner: **download
   your certificate now — it is your only way to log back in.**

### Login

1. `GET /auth/login` — file upload form (accepts `?next=` for post-login
   redirect; `next` must be a relative path on this origin).
2. User uploads cert + key PEM.
3. Server validates the pair, computes the fingerprint, looks up the
   certificate row → user. No match → error linking to signup.
4. Creates session, sets cookie, redirects to `next` or account page.

### Logout

`POST /auth/logout` — deletes the session row, clears the cookie.

### Account page (`GET /account`)

- Lists all certificates: CN, fingerprint (truncated, expandable), validity
  window, source, created date, active status. Warn on expired /
  expiring-soon certs.
- Per cert: **activate** / **deactivate**, **download** (PEM bundle with cert
  + private key), **delete**.
- Deleting the **last** certificate is blocked (it would orphan the account);
  point users at *delete account* instead.
- Upload-another and generate-another forms (same validation as signup;
  additional certs are **not** auto-activated).
- **Delete account**: explicit confirmation; deletes user, certificates,
  sessions.

### Browsing with a certificate

- On every proxy request, if the session user has an active cert and the URL
  scheme is `gemini` or `scroll`, the cert/key is loaded into the SSL context.
- The base template header shows the identity state when logged in, e.g.
  `[id: mozz ✓]` linking to `/account` when a cert is active, `[id: off]`
  when logged in with no active cert. Users must be able to see at a glance
  whether their identity is being presented.
- Background favicon fetches and any other server-initiated requests **never**
  attach client certificates.

### Access errors (`6x` responses)

Replace `proxy/gemini-cert-required.html` with a template driven by auth
state (the scroll protocol reuses the same statuses and template):

| State | 60 (cert required) | 61/62 (not authorised / not valid) |
|---|---|---|
| Anonymous | "This page requires an identity." Buttons: **Log in** / **Create account**, both carrying `?next=<current proxy URL>` | Same as 60 |
| Logged in, no active cert | "You're logged in but no certificate is active." Link to `/account` to activate or create one | Same |
| Logged in, active cert | (Shouldn't normally happen — cert was sent) Show meta + link to account | "The server rejected the certificate `<CN>` (`61 …meta…`)." Link to `/account` to switch or generate another |

The response `meta` line is displayed in all cases — servers put useful
instructions there.

## HTTP routes

All new routes are static-path routes; werkzeug gives them precedence over
the dynamic `/<scheme>/<netloc>/...` proxy routes, so no conflicts (no
supported scheme is named `auth`, `account`, or `certificates`).

| Method | Path | Description |
|---|---|---|
| GET | `/auth/login` | Login form (`?next=` supported) |
| POST | `/auth/login` | Validate PEM, create session |
| GET | `/auth/signup` | Signup page (upload + generate forms) |
| POST | `/auth/signup/upload` | Create account from uploaded cert |
| POST | `/auth/signup/generate` | Create account with generated cert |
| POST | `/auth/logout` | Destroy session |
| GET | `/account` | Account/certificate management page |
| POST | `/account/delete` | Delete account (confirmation required) |
| POST | `/certificates/upload` | Add cert to existing account |
| POST | `/certificates/generate` | Generate cert on existing account |
| POST | `/certificates/<id>/activate` | Make this the active cert |
| POST | `/certificates/<id>/deactivate` | No active cert (anonymous browsing) |
| POST | `/certificates/<id>/delete` | Remove cert (blocked if last one) |
| GET | `/certificates/<id>/download` | PEM bundle, `Content-Disposition: attachment; filename=<cn>.pem` |

All `/certificates/*` and `/account*` routes are session-required and scoped
to the session's user (404 on other users' cert ids).

## Database

### Engine & access

- SQLite via **`aiosqlite`** (new dependency) — the app is ASGI and the
  current `shelve` calls already do sync I/O in the request path; this fixes
  that rather than extending it.
- `PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout=5000`, foreign keys ON.
  WAL makes multi-worker gunicorn on one host safe.
- Path from config: `QUART_DATABASE_PATH` env var; default
  `instance/portal.sqlite3` for dev. **Not** the temp dir — this data is now
  durable (accounts live here).
- No ORM. A thin repository module (`geminiportal/db.py`) with plain SQL,
  matching the project's low-dependency style.
- Migrations: numbered SQL scripts applied at startup, tracked with
  `PRAGMA user_version`.

### Schema

```sql
CREATE TABLE users (
    id          INTEGER PRIMARY KEY,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE certificates (
    id               INTEGER PRIMARY KEY,
    user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    fingerprint      TEXT NOT NULL UNIQUE,   -- sha256 hex of DER cert
    common_name      TEXT NOT NULL,
    cert_pem         TEXT NOT NULL,
    private_key_pem  TEXT NOT NULL,          -- see "Key storage" below
    not_before       TEXT NOT NULL,
    not_after        TEXT NOT NULL,
    source           TEXT NOT NULL CHECK (source IN ('uploaded', 'generated')),
    is_active        INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX certificates_user_idx ON certificates(user_id);
CREATE UNIQUE INDEX certificates_active_idx ON certificates(user_id)
    WHERE is_active = 1;                     -- at most one active per user

CREATE TABLE sessions (
    id            INTEGER PRIMARY KEY,
    token_hash    TEXT NOT NULL UNIQUE,      -- sha256 hex of the cookie token
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at    TEXT NOT NULL,
    last_used_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX sessions_expires_idx ON sessions(expires_at);

CREATE TABLE favicons (
    url         TEXT PRIMARY KEY,            -- favicon.txt URL for the host
    favicon     TEXT,                        -- NULL = negative cache
    expires_at  REAL NOT NULL                -- unix time, 4h TTL as today
);
```

### Favicon migration

`FaviconCache` keeps its interface (`check()` becomes async) but reads/writes
the `favicons` table instead of `shelve`. Entries expire after 4 hours, so no
data migration is needed — the shelve file is simply abandoned. Negative
caching (storing `NULL` on fetch failure) is preserved. This is the only
filesystem-stashed data in the app today; anything similar added later goes
in this database.

## Sessions & cookies

- Token: 32 random bytes (`secrets.token_urlsafe`), sent in a `session`
  cookie; only the SHA-256 hash is stored.
- Cookie flags: `HttpOnly`, `SameSite=Lax`, `Secure` (when not in debug),
  `Max-Age` matched to the session expiry.
- Lifetime: 30 days, sliding — `expires_at` is pushed forward on use (throttle
  the UPDATE to at most once per hour via `last_used_at`). Long sessions
  matter here because logging in requires digging up a key file.
- Expired-session cleanup: `DELETE FROM sessions WHERE expires_at < now`
  opportunistically at startup and once per day via a background task.
- The captcha cookie's Jan-1st expiry trick (anti-tracking) intentionally does
  **not** apply: a session cookie is identifying by definition, and only
  exists for users who opted into accounts. Anonymous browsing is unchanged.
- A valid session also **bypasses the captcha check** — a logged-in user has
  already proven more than the captcha does.

Request plumbing: an `@app.before_request` hook resolves the cookie to
`g.user` / `g.active_cert` (single JOIN query), and the context processor
exposes them to templates for the header indicator.

## Certificate handling

New dependency: **`cryptography`**. (`openssl` subprocess is already used
for pretty-printing server certs and stays as-is; parsing, validation,
fingerprinting, and generation use `cryptography` proper.)

### Validation (upload & login)

- Max upload size: 64 KB. Accept one combined PEM or separate cert/key files.
- Cert must parse as X.509; key must parse as an unencrypted private key
  (RSA / EC / Ed25519). Encrypted keys are rejected with a clear message
  ("decrypt it first: `openssl pkey -in cert.pem -out decrypted.pem`").
- Key must match the cert: compare `SubjectPublicKeyInfo` bytes of
  `key.public_key()` vs `cert.public_key()`.
- Expired certs: allowed at login (some gemini servers accept them; the
  account shows a warning) but a warning banner is shown. Uploads of expired
  certs at signup get the same warning, not a rejection.
- Fingerprint = `cert.fingerprint(SHA256())`, stored as lowercase hex.

### Generation

- ECDSA P-256 key (small, universally supported by gemini servers;
  Ed25519 deliberately avoided for compatibility).
- Self-signed, `subject == issuer == CN=<user input>`, CN limited to 64
  printable chars, random 64-bit serial, `notBefore = now − 1d`,
  `notAfter = now + validity`, SHA-256.
- No SANs, no extensions beyond BasicConstraints(CA=FALSE) — matches what the
  gemini ecosystem expects from client certs.

### Key storage

Private keys are stored **encrypted at rest** with Fernet, using a key
derived from the app `SECRET_KEY` (which becomes a required config value in
production). This costs a few lines with `cryptography` already in the tree
and means a leaked DB file alone doesn't expose every user's identity key.
Consequence: rotating `SECRET_KEY` invalidates stored keys, so it must be
called out in deployment docs. (If this trade-off is unwanted, plaintext
storage is the fallback — the threat model already includes the server.)

### Attaching certs to proxy requests

- `build_proxy_request(url, options, client_cert=None)` gains an optional
  parameter; `app.proxy()` passes `g.active_cert` when the scheme is
  `gemini` or `scroll`.
- `GeminiRequest.create_ssl_context()` / `ScrollRequest.create_ssl_context()`
  call `context.load_cert_chain(certfile, keyfile)`. The stdlib only loads
  from file paths, so the PEM is written to a `NamedTemporaryFile` (mode
  0600) and unlinked immediately after `load_cert_chain` returns — the
  context holds the material in memory after loading.
- Optimization: cache the constructed `SSLContext` per cert fingerprint in a
  small LRU so the temp-file dance happens once per cert, not per request.
  (Note: `CloseNotifyState` hooks a per-request callback onto the context, so
  either the cache stores contexts pre-hook or the callback is made
  re-entrant — implementation detail to resolve.)

## Security notes

- **CSRF**: every state-changing POST carries a hidden `csrf_token` =
  HMAC-SHA256(`SECRET_KEY`, session token hash), verified server-side. The
  unauthenticated login/signup POSTs have no session to ride, but still get
  `SameSite=Lax` + an `Origin`/`Referer` same-origin check.
- **Open redirect**: `next` must be a relative path (`startswith("/")`, not
  `//`).
- **Enumeration/abuse**: login by fingerprint is not brute-forceable in any
  meaningful way (you need the matching private key), but login/signup POSTs
  get a modest per-IP rate limit anyway (simple in-memory counter is fine).
- **Cert isolation**: certs are only attached to user-initiated proxy
  requests for TLS schemes; never to favicon prefetches. This prevents the
  portal from silently announcing a user's identity to hosts they didn't
  navigate to.
- **Download responses**: `Cache-Control: no-store` on the PEM download and
  the account page.

## Implementation plan (suggested order)

1. `geminiportal/db.py` — aiosqlite connection lifecycle (init on app
   startup, close on shutdown), migration runner, schema v1.
2. Port `FaviconCache` to the DB (smallest slice that proves the DB layer;
   `test_favicons.py` updates with it).
3. `geminiportal/certs.py` — parse/validate/generate/fingerprint/encrypt
   (pure functions, heavily unit-tested).
4. `geminiportal/auth.py` — session create/resolve/destroy, `before_request`
   hook, CSRF helper.
5. Blueprint with the routes above + `templates/auth/*` pages; header
   indicator in `base.html`.
6. Proxy integration: `build_proxy_request` parameter, SSL context loading,
   captcha bypass for sessions.
7. Rework `gemini-cert-required.html` into the state-aware access-error
   template.

## Open questions

1. **Cert scoping** — v1 sends the active cert to *every* gemini/scroll host.
   That's how a "logged in everywhere" UX works, but it lets any gemini
   server correlate a user across hosts. Acceptable for v1? (Per-host
   activation is the obvious v2.)
2. **Should generated certs auto-download?** The spec says "banner + download
   link" after generation; forcing the download as the POST response is more
   foolproof but makes the redirect flow clunkier.
3. **Key encryption at rest** — confirm the SECRET_KEY-rotation trade-off is
   acceptable (see *Key storage*).
