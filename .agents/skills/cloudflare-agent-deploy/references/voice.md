# Optional WebRTC voice

A text-only agent needs neither Realtime activation nor microphone access.
Verify the runtime's media transport support before implementing WebRTC.

For containers without publicly reachable UDP candidates, use a TURN relay.
The reference trial used Cloudflare Realtime TURN with temporary credentials.
Realtime activation and Workers/Containers/R2 activation are separate.

Create or select a dedicated TURN key for this deployment within authorized
scope. Store its ID and API token in Worker secrets, passing them only to
server processes. Wrangler OAuth may lack Calls Write even when deployment
works: use an authorized API credential or dashboard instead of retrying the
same insufficient token.

The reference credential-generation request is:

```text
POST https://rtc.live.cloudflare.com/v1/turn/keys/{key_id}/credentials/generate-ice-servers
Authorization: Bearer {turn_api_token}
Content-Type: application/json
User-Agent: your-agent-service/1.0

{"ttl":7200}
```

Validate `iceServers`, including TURN username/credential. Return temporary
credentials only to authenticated callers, never the long-lived TURN key.
Cache for less than their lifetime. The trial used a five-minute cache for
two-hour credentials; choose TTLs for the new product.

A local live test returned 403 with Python's default User-Agent and succeeded
with an explicit service User-Agent. For a new 403, inspect the actual response
and credentials rather than assuming this cause.

Configure browser and server ICE settings. Relay-only browser policy may be
needed with private container candidates. Check server-library TURN transport
support; valid credentials do not prove the peers can reach each other.

Media can flow through TURN without touching the Worker. Thus HTTP inactivity
can expire during a call. Use an authenticated heartbeat or session-aware
lifetime; a one-hour trial timeout is not a guarantee for longer calls.

Verify connected state, a spoken/synthetic phrase being transcribed, agent
audio being received, and clean teardown. Microphone access needs appropriate
authorization; stop test capture afterward. Do not claim voice works from
health, credential issuance, or signaling alone.

[Cloudflare TURN documentation](https://developers.cloudflare.com/realtime/turn/)
