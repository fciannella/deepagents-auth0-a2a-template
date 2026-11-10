# A2A text client contract

Local base URL: `http://localhost:9183`. Deployed URL, Auth0 issuer, audience, and scopes
come from the clone's settings; this template has no hosted endpoint or preconfigured tenant.

All card/message/task routes require `Authorization: Bearer <user access token>`.
Send `A2A-Version: 1.0` on message/task requests. Use `application/a2a+json` or
`application/json` when submitting JSON. Browser clients must be CORS-allowed.

```http
POST /message:send
Authorization: Bearer <access token>
A2A-Version: 1.0
Content-Type: application/a2a+json

{
  "message": {
    "messageId": "client-turn-001",
    "role": "ROLE_USER",
    "parts": [{"text": "Hello"}]
  },
  "configuration": {"historyLength": 2}
}
```

Successful HTTP submission returns a task envelope. Inspect `status.state`: HTTP 200
alone does not mean model execution succeeded.

```json
{
  "task": {
    "id": "<server task UUID>",
    "contextId": "<server conversation UUID>",
    "status": {"state": "TASK_STATE_COMPLETED", "timestamp": "<UTC timestamp>"},
    "artifacts": [{"artifactId":"<opaque ID>","name":"response","parts":[{"text":"Hello!"}]}]
  }
}
```

Continue by setting `message.contextId` to the returned UUID and choosing a **new**
message ID. `message.taskId` continuation is not supported. Read output from response
artifact text parts, not from an assumed message position. IDs and page tokens are opaque.

Within an account, `messageId` is an idempotency key. Retrying the same JSON payload
returns the recorded task without executing tools again, including recorded failures.
Changing any payload field for the same message ID returns 409. Keep the exact payload
for network retries. An overlapping active turn for the account also returns 409.
After an uncertain response, inspect tasks before issuing a new message ID. The template
does not guarantee exactly-once external tool side effects across abrupt failure.

Supported task states are `TASK_STATE_WORKING`, `TASK_STATE_COMPLETED`, `TASK_STATE_FAILED`.
An interrupted process marks in-flight tasks failed on startup. Failed turns can leave
partial LangGraph state or tool effects; continuing with a new message does not roll them back.

`GET /tasks/{id}?historyLength=2` returns a task **directly**, without a `task` envelope.
`GET /tasks` returns `{tasks, nextPageToken, pageSize, totalSize}`. List parameters:

| Parameter | Behavior |
|---|---|
| `pageSize` | 1–100, default 50 |
| `pageToken` | Opaque cursor returned by the preceding page |
| `contextId` | Restrict to one conversation |
| `status` | Filter one of the three supported states |
| `statusTimestampAfter` | Timezone-aware ISO 8601 timestamp |
| `historyLength` | 0–100, default 0; each task contains at most its user and agent message |
| `includeArtifacts` | `true` or `false`, default false for listing |

Tasks are listed newest first. Follow `nextPageToken` until empty; reverse the result for
chronological display. User ownership applies to list, get, and continuation. Unknown or
other-user task/context IDs return 404. Do not manufacture cursors or retain cursors across
unrelated backends/migrations.

Other limits: 64 KiB HTTP request body, 12,000 text characters, 1–16 text parts, one active
turn per account, eight active accounts by default, and a 120-second turn timeout.
Multiple input text parts are joined with newlines. Metadata is not used as identity,
time, or trusted instructions. `returnImmediately=true` and non-text parts are rejected.

Errors use `application/problem+json` with `type`, `title`, `status`, and `detail`.
Typical statuses: 400 invalid input/version, 401 invalid/missing user token, 403 scope/origin,
404 owner-scoped absence, 409 concurrency/replay conflict, 413 body limit, 415 content type,
429 capacity, 503 unconfigured/unavailable service. Cloudflare startup failure may return
plain text 503, so clients should check Content-Type before decoding JSON errors.

The authenticated card at `/.well-known/agent-card.json` advertises HTTP+JSON 1.0 and
no streaming or push. This starter does not implement JSON-RPC, gRPC, streaming,
async execution, file parts, cancellation, subscriptions, or push notification APIs.
It is a documented subset, not a full A2A conformance certification.
