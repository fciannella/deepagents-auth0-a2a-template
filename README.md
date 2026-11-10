# Deep Agents + Auth0 + A2A

A cloneable, text-only agent starter built with **LangChain Deep Agents**, **Auth0**,
and an **A2A 1.0 HTTP+JSON** interface. One container serves the agent and a small test UI.
The UI itself uses A2A. Customize the prompt and tools in source; no admin control plane.

```text
Browser / A2A client ── Auth0 access token ──> FastAPI A2A gateway
                                               │ verified owner
                                               ▼
                                          Deep Agents
                                               │
                              SQLite transcript + LangGraph checkpoints
                                               │ optional
                                      Cloudflare private R2 backup
```

## Start locally

Requirements: Docker with Compose; an Auth0 SPA application and API; a model-provider key.
For development, install Python 3.12 or 3.13, uv, and Node 22.

1. Use GitHub's **Use this template**, or clone this repository.
2. Copy `.env.example` to `.env`. Fill in your own Auth0 settings and `MODEL_API_KEY`.
3. Configure Auth0 following [docs/AUTH0.md](docs/AUTH0.md). Local callback, logout, and
   web origin are `http://localhost:9183` (no trailing slash in this local example).
4. Run:

```sh
docker compose up --build -d
```

Open **http://localhost:9183**, sign in, and send a message. If configuration is incomplete,
the UI explains what to configure and `/health` returns 503. There is no development auth
bypass and no shared anonymous account. Model credentials stay on the server.

The example provider is OpenRouter. `MODEL_BASE_URL`, `MODEL_NAME`, and `MODEL_API_KEY`
can target another OpenAI-compatible chat endpoint. Change `app/agent.py` to use another
LangChain model integration. Ensure the model supports tool calls and has a context profile
compatible with Deep Agents. The default is a tested example, not a required provider.

Stop with `docker compose down`. The named volume retains state. `down -v` deletes it.
Each clone that runs concurrently needs a unique Compose project name and local port.

## Make it your agent

| Change | File or setting |
|---|---|
| Role, workflow, tone, domain boundaries | `agent/prompt.md` |
| Domain tools and owner-scoped data access | `agent/tools.py` |
| Agent card name, description, skill ID, version | `AGENT_NAME`, `AGENT_DESCRIPTION`, `AGENT_ID`, `AGENT_VERSION` |
| Provider, tools, middleware, delegation, backend | `app/agent.py` |
| Sign-in and external browser clients | Auth0 settings, `PUBLIC_ORIGIN`, `CORS_ORIGINS` |
| Deployment | [Cloudflare instructions](docs/CLOUDFLARE.md) |

The generic prompt has no journal, scheduling, or application-specific rules. Default tools
save, search, and forget explicit user-requested facts. Memory has **no fixed item-count cap**;
available storage is the limit. The initial prompt uses a 12,000-character memory budget,
while a tool can search/page through all facts. Fact size limits apply to individual records.
Forgetting a fact does not erase conversation history or prior checkpoints. There is no
background extractor by default; add one only if it fits your product's privacy behavior.

Tools close over the verified owner. Do not add a model-supplied `user_id` or shared global
memory namespace. Deep Agents' default virtual filesystem is thread-scoped scratch state,
persisted in LangGraph checkpoints. Host filesystem and shell access are not enabled.
Adding a sandbox, sensitive tools, or domain policy requires an explicit implementation.

## A2A interface

See [docs/A2A-INTEGRATION.md](docs/A2A-INTEGRATION.md) for payloads, responses, auth,
continuation, replay semantics, pagination, and supported limits.

| Route | Function |
|---|---|
| `GET /.well-known/agent-card.json` | Authenticated agent card |
| `POST /message:send` | Blocking text turn |
| `GET /tasks` | Owner-scoped task list and filters |
| `GET /tasks/{id}` | Owner-scoped task retrieval |

This is an explicitly bounded A2A profile, not every A2A feature: no streaming, push,
async submission, task continuation/cancellation, files, JSON-RPC, or gRPC. Continue a
conversation with its `contextId` and a new `messageId`. Clients need an Auth0 **access
token** with the configured API audience and scope; ID tokens and machine identities are
not accepted. The only `/api` endpoint is public, nonsecret UI configuration.

## Develop and test

```sh
uv sync --frozen
npm ci
npm run vendor
uv run ruff check app agent tests scripts
uv run ruff format --check app agent tests scripts
uv run pytest -q
node --check app/static/app.js
node --test deploy/cloudflare/worker.test.mjs
```

Run the dev server after configuring `.env`:

```sh
uv run uvicorn app.main:app --host 127.0.0.1 --port 9183 --no-access-log
```

The tests run the actual Deep Agents graph with deterministic model fixtures and ephemeral
signed JWTs. Only the JWKS lookup is replaced; signature/issuer/audience/scope validation
is exercised. No production credentials or network model calls are needed in CI.

Optional real-model smoke test, using the configured container's provider key:

```sh
docker compose exec -T agent python - < scripts/smoke_model.py
```

It uses disposable databases, synthetic users, a synthetic JWKS, and the real model.
It verifies A2A reply, replay, cross-user denial, process-lifespan restart, and continuation.
It is **not** a live Auth0 tenant login test. See [verification notes](docs/VERIFICATION.md).

## Deploy with the Cloudflare skill

The [cloudflare-agent-deploy skill](.agents/skills/cloudflare-agent-deploy/SKILL.md) is
bundled under `.agents/skills/` for tools that discover repository skills. A compatible
coding assistant can be asked:

> Use $cloudflare-agent-deploy to deploy this agent, following docs/CLOUDFLARE.md.

If your tool does not discover repo skills, install that folder into its skills directory,
or follow the same instructions manually. The app-specific Worker/R2 adapter is already
provided; do not overwrite it with the skill's generic scaffolder.

[docs/CLOUDFLARE.md](docs/CLOUDFLARE.md) covers configuration generation, new resources,
secret transfer, exact Auth0 callback URLs, verification, and recovery. This template does
not deploy or connect to another agent automatically. You supply your own cloud account,
bucket, Auth0 app/API, and model credentials.

This SQLite/R2 deployment is a **single-writer prototype**, not high availability. Graceful
shutdown snapshots state. Abrupt failure may lose writes since the last successful periodic
backup. See the deployment guide before changing replica count or persistence.

## Framework references

- [Deep Agents customization](https://docs.langchain.com/oss/python/deepagents/customization)
- [A2A specification](https://a2a-protocol.org/latest/specification/)
- [Auth0 Authorization Code with PKCE](https://auth0.com/docs/get-started/authentication-and-authorization-flow/authorization-code-flow-with-pkce)
- [Cloudflare Durable Object Container API](https://developers.cloudflare.com/containers/api/durable-object-container/)

MIT licensed. Third-party dependencies retain their own licenses.
