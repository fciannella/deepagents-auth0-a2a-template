# Authentication and A2A clients

Decide whether callers represent people, services, or both. For personal memory,
derive ownership from validated issuer and subject, not a body-supplied user ID.
A machine token must not implicitly become a human identity. Define service
permissions and ownership explicitly if service access is wanted.

For Auth0/another OIDC provider validate algorithm/signature, issuer, API
audience, expiry, and permissions. Use access tokens, not ID tokens. Browser
and native apps should use an appropriate SDK with Authorization Code + PKCE;
backends may forward user access tokens. Never ship a confidential client
secret to a public client.

Configure each new app's client, exact callback/logout URLs, and any required
identity-provider web origins. Preserve existing entries. Configure gateway
CORS separately for intended browser origins. CORS is not authentication and
does not restrict native/server HTTP clients. Callers should need neither
Cloudflare account tokens nor model-provider API keys.

## A2A 1.0 HTTP+JSON profile

This is the selected subset used by the reference text gateway, not a claim
that all A2A transports/features are implemented. Check a new framework's
actual protocol against its current SDK/spec before adopting the example.

| Route | Purpose |
|---|---|
| `GET /.well-known/agent-card.json` | Capabilities/auth discovery |
| `POST /message:send` | Blocking text request |
| `GET /tasks` | Owner-scoped task listing |
| `GET /tasks/{id}` | Owner-scoped task retrieval |

The trial protected the card with a user bearer too. If a new product needs
public discovery, expose only deliberately public metadata and document it.
Send `A2A-Version: 1.0` for message/task requests in this profile.

```sh
curl "$AGENT_BASE_URL/message:send" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'A2A-Version: 1.0' \
  -H 'Content-Type: application/a2a+json' \
  -d '{"message":{"messageId":"unique-message-001","role":"ROLE_USER","parts":[{"text":"Hello"}]}}'
```

The response is a task envelope. Continue with its `contextId` in the next
`message`, using a fresh message ID. Persist owner-bound replay records. After
an indeterminate timeout inspect state before resubmitting new work. Bound
inputs, allowlist routes, and enforce ownership on history/task retrieval as
well as submission. Never expose internal admin endpoints through a generic
public reverse proxy.

Advertise only supported capabilities; this profile has no streaming or push
notifications. A2A text is separate from WebRTC audio signaling.

## Client guide and verification

Write project-local `A2A-INTEGRATION.md` with actual base URL, issuer, audience,
permissions, caller setup, routes, examples, continuation/retry behavior, and
verification status. Old audiences, scopes, and client IDs are not defaults.

Verify missing, expired, wrong-audience, and insufficient-permission tokens;
then exercise a real reply, continuation, and cross-user denial. Login success
or a 401 alone does not prove model invocation works.

- [Auth0 PKCE](https://auth0.com/docs/get-started/authentication-and-authorization-flow/authorization-code-flow-with-pkce)
- [A2A specification](https://a2a-protocol.org/latest/specification/)
