---
name: cloudflare-agent-deploy
description: Build or adapt an agent in the current project and host it on Cloudflare, including container runtimes, durable state, authenticated A2A text APIs, and optional WebRTC voice. Use for new agents and Cloudflare deployment changes; this workflow does not depend on an existing agent directory.
---

# Cloudflare agent deployment

Work from the user's selected project. This skill lives at user scope and can
be invoked from any directory. Its examples contain no account credentials,
agent prompts, customer data, or required links to a previous deployment.

## Start with the agent

Inspect the project's instructions, source, deployment files, and existing
runtime before choosing a design. For an empty project, establish the agent's
job, intended users, model/provider, tools, state, and required channels from
the request. Ask only for decisions that materially change the build and cannot
be inferred. Build the agent's actual behavior and local entrypoint; a healthy
HTTP server alone is not a working agent.

Choose the smallest suitable runtime:

- Use a Worker-native implementation when the agent and dependencies fit its
  execution model; consult current Workers/Agents SDK documentation.
- Use Workers + Durable Objects + Containers for a full Python/Node runtime,
  OS dependencies, subprocesses, or an existing Docker agent. This is the
  workflow in [references/containers.md](references/containers.md).
- Choose storage based on the data model. D1/external databases may suit
  multi-instance agents. For an existing SQLite agent, read
  [references/persistence.md](references/persistence.md) before using R2
  checkpoints. R2 is not a shared transactional SQLite filesystem.

Preserve the user's chosen framework and provider. Do not automatically reuse
an old agent's identity, resource names, Auth0 audience, prompts, tools, history,
or secrets. Reuse existing resources only when intended for this agent.

## Build and deploy

1. Make a local working agent with a health endpoint and the requested caller
   interface. Keep administrative operations private. Build a reproducible
   image if using Containers; pin tested dependency versions.
2. Establish user/service authorization and data ownership before exposing
   agent actions. Read [references/auth-a2a.md](references/auth-a2a.md) for A2A
   integration or bearer delegation. Read [references/voice.md](references/voice.md)
   only when voice is required.
3. Inspect the target Cloudflare account and verify the products actually
   needed: Workers/Containers, R2 when used, and Realtime TURN when used. An
   activation of one product does not prove the others are enabled. Prefer
   CLI/API; use the dashboard for unsupported operations.
4. Prepare unique Worker, bucket/database, and deployment names in this project.
   The optional `scripts/scaffold.py` creates local deployment files for an
   existing Dockerfile; see the container reference. It does not create an
   agent, deploy, install dependencies, or transfer secrets.
5. Transfer only this agent's required credentials into Worker secrets through
   stdin or another secret-aware mechanism. Keep secrets out of images, source,
   generated docs, and logs. Worker bindings are not automatically process
   environment variables; pass an explicit environment allowlist.
6. Validate the local runtime, authentication rejection, and persistence.
   Verify current official Cloudflare docs and the installed Wrangler schema
   before deployment; the examples use the direct Durable Object Container API
   verified on 2026-11-10 with Wrangler 4.160.0.
7. Deploy within the user's authorized scope, configure exact final login
   callbacks and browser origins, and run the checks below. Existing billing,
   credential, or domain approvals do not imply approval for unrelated changes.
   Follow active tool confirmation rules at consequential actions; do not invent
   an extra approval stage for ordinary authorized deployment.

If an external action fails, inspect its result before retrying: a successful
creation followed by a timeout must not create duplicate resources. When a
missing entitlement, permission, login, or tool capability blocks progress,
finish independent work and report the specific remaining action. Browser
failure is not evidence that the deployment is broken or that a test passed.

## Verify and hand off

Verify the deployed release, not only the local image:

- Health and UI/API availability; missing and invalid tokens rejected; private
  admin/storage paths inaccessible.
- A real authenticated agent reply and continuation of the same conversation.
  For per-user data, verify another identity cannot retrieve that conversation.
- Durable state after graceful restart, and failure behavior for corrupt or
  unavailable storage. For checkpoints, state the possible loss window.
- If voice is included, a connected call, transcription, generated audio, and
  clean teardown. TURN credential issuance alone is not an audio test.

Use synthetic smoke-test content. Microphone use needs appropriate user
authorization. Avoid silently resending indeterminate agent requests.

Write project-local deployment instructions and, when applicable, an A2A client
guide with actual URL, issuer, audience, permissions, routes, example request,
and supported protocol version. Record deployment identifiers, restart/rollback
steps, verified checks, and unresolved limits without secrets. Report what is
usable and what remains unverified. Do not call a single-container checkpoint
prototype a highly available production service.
