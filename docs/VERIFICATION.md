# Template verification

Initial verification: 2026-11-10.

- 27 Python tests passed; Ruff checks and formatting passed.
- Worker bridge regression test passed, including refusal to initialize empty state after
  the remote initialization marker exists.
- Docker Compose image built and started. An unconfigured clone serves its UI/config and
  reports `needs_configuration` with HTTP 503 on health, rather than enabling anonymous use.
- The real-model smoke script passed inside the built container: A2A reply, signed JWT
  validation, idempotent replay, another synthetic owner's denial, process-lifespan restart,
  and continuation with the same test phrase. A provider key was passed transiently for the
  test; no key, Auth0 tenant, or deployment credentials are included in this repository.
- A local Wrangler rehearsal built the AMD64 image, initialized the private R2 bridge,
  uploaded a coordinated SQLite snapshot, stopped the container gracefully, and restored a
  synthetic memory fixture into a new container. Only local emulated Cloudflare storage was
  used; no cloud resources were created or modified for this starter.
- Tests cover committed SQLite WAL state, both-database restore validation, corruption and
  unavailable storage, first initialization, owner-scoped tools, 131 saved memory records,
  active-turn conflicts, malformed inputs, CORS and private-route rejection.
- The portable config generator was exercised and refuses to overwrite an existing config.

The built-in UI sends messages and restores conversations through A2A. Its assets and JS
syntax were checked, but a fresh browser/Auth0 sign-in was not run for the generic template:
each clone must supply its own tenant/application, callback URLs, scopes and users. Browser
preview tooling was unavailable during this verification. CI runs deterministic tests and
builds the container without external credentials.

No deployment URL is provided: deployment belongs to the clone. Follow the Cloudflare skill
and `CLOUDFLARE.md` to verify real tenant authentication, a live model reply/continuation,
second-account denial and restart durability on the selected account before release.
