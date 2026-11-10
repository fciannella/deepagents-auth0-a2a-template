# Auth0 setup

Create your own Auth0 **Single Page Application** and an **API** using RS256 signing.
The API Identifier becomes `AUTH0_AUDIENCE`; define an `agent:chat` permission (or choose
a different nonempty required scope and update `AUTH0_REQUIRED_SCOPES`). Make that scope
available to the users who should access the agent. If RBAC is enabled, configure roles
and grants accordingly; this starter checks the access token's `scope` string.

Set these public values in `.env`:

- `AUTH0_DOMAIN`: tenant/custom hostname, without `https://` or trailing slash.
- `AUTH0_CLIENT_ID`: SPA client ID.
- `AUTH0_AUDIENCE`: exact API Identifier.
- `AUTH0_REQUIRED_SCOPES`: space-separated required API scopes, default `agent:chat`.

For local testing, configure the SPA's Allowed Callback URLs and Allowed Logout URLs
as `http://localhost:9183`, and Allowed Web Origins as `http://localhost:9183`.
The example `.env` uses exactly that callback. Use HTTPS away from loopback.

For Cloudflare, add the final HTTPS URL to the same lists. Generated cloud config uses
`https://your-agent.example/` as callback/logout (trailing slash) and
`https://your-agent.example` as public/web origin. Keep existing allowed entries if you
are intentionally sharing an application. `AUTH0_REDIRECT_URI` can select either root
spelling explicitly; the SDK and Auth0 allowlist must agree.

The UI uses Authorization Code + PKCE via a locally vendored Auth0 SDK. Tokens are held
in memory, not localStorage. No Auth0 client secret belongs in frontend code or this SPA.

The API verifies RS256 signature through JWKS, issuer, API audience, expiry, issued-at,
subject and configured scopes. `sub` values ending with `@clients` are rejected: this
starter represents human users, not client-credential service identities. Ownership is
SHA-256 of verified `issuer + NUL + subject`. No request body chooses an owner.

External browser clients also need their origin in the gateway's `CORS_ORIGINS` JSON list.
Their own Auth0 application must allow their callback and web origin. Server/native
clients omit the browser Origin header and still must provide a valid user access token.

Before release, verify login, a real reply, continuation, logout, expiry/wrong-audience
rejection, and denial when another real account asks for the first account's task/context.
Automated synthetic JWT tests complement but do not replace tenant-specific checks.
