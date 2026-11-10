# Working on this template

This repository is a generic text agent, not a domain-specific deployed instance.
Customize `agent/prompt.md`, `agent/tools.py`, and environment settings. Keep the test
UI on the same A2A interface used by external clients. No admin control plane.

- Use the bundled [cloudflare-agent-deploy skill](.agents/skills/cloudflare-agent-deploy/SKILL.md)
  for Cloudflare deployment work. Read `docs/CLOUDFLARE.md` before changing its scaffold.
  The deployment files already exist: do not run the skill's generic scaffolder over them.
- Never reuse a previous agent's Auth0 client/audience, Cloudflare resource names, credentials,
  user history, R2 bucket, or deployment identifiers unless explicitly authorized.
- Bind data access to verified issuer/subject. Never let a tool or request choose its owner.
- Keep one container writer / one Uvicorn worker with this SQLite/R2 design.
- Memory capacity is storage-based; do not introduce a fixed item count. Prompt selection
  and pagination limits are not storage limits.
- Change the runtime `REVISION` when deploying image or environment changes.
- Run `uv run ruff check app agent tests scripts`, `uv run ruff format --check app agent tests scripts`,
  `uv run pytest`, `node --check app/static/app.js`, and
  `node --test deploy/cloudflare/worker.test.mjs` for relevant changes.
- Do not commit `.env`, generated `wrangler.jsonc`, `.dev.vars`, data, checkpoint archives,
  tokens, or private test output. Do not weaken authentication for a live smoke test.
