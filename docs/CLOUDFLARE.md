# Cloudflare deployment

Use the bundled [cloudflare-agent-deploy skill](../.agents/skills/cloudflare-agent-deploy/SKILL.md).
This repository already contains the app-specific Worker, private R2 bridge, Dockerfile,
and two-database snapshot implementation. Do not regenerate them with the skill's generic
scaffolder, which has a different single-database storage contract.

## Configure a clone

Prepare a **new** Workers/Containers application and a dedicated R2 bucket in your account.
Choose a unique worker name and final HTTPS origin. Do not point this starter at another
agent's bucket or Durable Object. One named object (`agent`) owns the single SQLite writer.

From the repository root:

```sh
uv sync --frozen
uv run python -m scripts.configure_cloudflare \
  --name my-agent \
  --account-id YOUR_32_CHARACTER_CLOUDFLARE_ACCOUNT_ID \
  --public-origin https://my-agent.YOUR_SUBDOMAIN.workers.dev \
  --auth0-domain YOUR_TENANT.us.auth0.com \
  --auth0-client-id YOUR_SPA_CLIENT_ID \
  --auth0-audience https://my-agent.example/api
cd deploy/cloudflare
npm ci
npx wrangler login
npx wrangler whoami
```

The generator writes ignored `wrangler.jsonc`, refuses to overwrite an existing config,
and performs no remote operations. Edit the generated file's public agent metadata/model
settings and optional `CORS_ORIGINS` string (JSON-encoded array). Worker vars are explicitly
forwarded to the container. The readiness gate stays false until setup is verified.

Inspect your account's Workers/Containers entitlement and R2 availability. Create only the
missing bucket named by the generated config:

```sh
npx wrangler r2 bucket create my-agent-state
npx wrangler secret put MODEL_API_KEY
```

Enter the model-provider key through the secret prompt, not a committed config or CLI flag.
No R2 credential is sent to the container. Never put a confidential Auth0 client secret
into this SPA application. Configure exact Auth0 callback/logout URLs and web origins per
[AUTH0.md](AUTH0.md). Use the **actual final URL**, not these placeholders.

## Validate, then deploy

Run the root test suite and container smoke tests first. For a local Wrangler rehearsal,
create ignored `.dev.vars` in this directory with `MODEL_API_KEY`, run `npx wrangler dev
--local`, and use a local config with loopback origins and `PUBLIC_GATEWAY_READY="true"`.
Use a separate local state directory for each rehearsal. Never enable remote bindings just
to get local tests passing. Local R2 starts empty; the app initializes it before readiness.

Once authentication/data boundaries and setup are verified, set the generated config's
`PUBLIC_GATEWAY_READY` to `"true"` and run:

```sh
npm run check
npm run deploy
```

The pinned Wrangler builds linux/amd64 from the root Dockerfile. Internal port is 9173.
The container needs `MODEL_API_KEY` plus the public Auth0/model settings. The readiness
check requires configured auth/model and an initial durable snapshot. Missing setup fails
closed rather than exposing an anonymous agent.

After deployment, verify health, UI, Auth0 login, a real A2A reply, continuation, another
account's denial, and graceful restart. Also verify `/admin` and `/deepagents-state.zip`
are not publicly available. Record actual version/image/resource identifiers privately or
in your clone's deployment notes. This upstream template intentionally has none.

## Persistence and lifecycle

The dedicated `STATE` R2 binding stores `state/v1/state.zip` and `state/v1/initialized.json`.
An outbound interceptor makes `http://storage.internal/deepagents-state.zip` available only
to the container. Public requests never reach the storage entrypoint.

Before the first initialization, GET returns 404 and a new local database is created.
After initialization, a missing state object returns 503, not 404. Corruption, unavailable
storage, and missing established state fail startup instead of silently discarding history.

`app.sqlite` holds owner-scoped task/replay/memory data; `checkpoints.sqlite` holds LangGraph
state and virtual files. The app blocks new mutations and waits for active turns before
backing up both databases into one generation with SQLite's online backup API. ZIP members,
checksums and SQLite integrity are verified before restore. Uploads are serialized.

Snapshots happen before readiness, every 30 seconds, and during graceful shutdown. Abrupt
failure can lose changes since the last successful checkpoint: normally 30 seconds plus
active turn and upload time, longer during storage outages. This is not transactional remote
storage per response. `/health` reports last successful checkpoint and last error type.
A storage outage during operation does not roll back already accepted local turns.

Use **one Uvicorn worker and one container writer** with this design. Do not shard the named
object or reuse a bucket across deployments. Move to an appropriate shared transactional
backend before scaling writers. Store any external tool artifacts separately; this archive
only captures the two databases, not arbitrary filesystem files.

## Updates, restart, recovery

After prompt, code, model, secret, or environment changes, increment `REVISION` in
`deploy/cloudflare/worker.js` and deploy again. The Durable Object signals the old process,
waits for its final snapshot, then starts the new image and restores state. Keep enough
shutdown time for a 120-second turn plus snapshot upload (local Compose allows 150 seconds).

Before rolling back, preserve the current checkpoint and check database compatibility with
the target code version. Use Wrangler's version tooling after inspecting the actual account;
this template contains no magic rollback ID. Never delete the initialization marker to bypass
a recovery failure. Restoring older data must be a deliberate recovery operation, not an
automatic fallback. Keep downloaded state archives private: they contain user conversations.
