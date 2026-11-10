# Container workflow and starter

The hosting pattern is client → Worker → named Durable Object → container HTTP
gateway. Provider inference can run elsewhere; hosting the agent does not imply
hosting model weights or providing a GPU.

## Runtime contract

Provide a project Dockerfile and a public gateway listening on `0.0.0.0` at a
known port. Health must return 200 only when required components are ready.
A multi-process runtime needs a supervisor that terminates children and flushes
state on SIGTERM. Do not publish an appliance's admin interface because it
shares the image.

Package schemas, prompts, published UI assets, adapters, and libraries needed
by the serving release. An export format may omit schemas, disable auth, omit
a text gateway, or update a dependency during build. Inspect exports.

Build for the target architecture in current Cloudflare docs (the reference
deployment used Linux AMD64). Use `.dockerignore` to exclude `.git`, `.env*`,
secret files, local databases, caches, and personal history. Do not automatically
copy an original deployment's data.

## Generate local deployment files

From any working directory, invoke the skill's helper by absolute path:

```sh
python3 /path/to/cloudflare-agent-deploy/scripts/scaffold.py \
  --project /absolute/path/to/new-agent \
  --name new-agent-trial \
  --account-id YOUR_CLOUDFLARE_ACCOUNT_ID \
  --port 8080 \
  --env MODEL_API_KEY --env AUTH_ISSUER --env AUTH_AUDIENCE
```

Use `--dockerfile path/within/project/Dockerfile` if needed. Add
`--r2-bucket new-agent-trial-state` only when implementing the checkpoint
contract in the persistence reference. The helper refuses an existing
`deploy/cloudflare` directory and never replaces project files.

Generated files include `worker.js`, `wrangler.jsonc`, `package.json`, and a
local `.gitignore`. The Worker returns 503 until `vars.PUBLIC_GATEWAY_READY` is
`true`: first implement and verify the container gateway's authentication and
private-route boundary. This flag is a setup guard, not authentication.
Set `PUBLIC_BASE_URL` to the final HTTPS origin before deploying an app using it.

The starter routes to one named container and one gateway port. Adapt routing
explicitly for multiple gateways. The container must restrict its own public
routes; the starter cannot infer them. This is hosting plumbing, not an agent
implementation or authentication library.

## Cloudflare setup and operations

1. Install the project's pinned Wrangler and commit its lockfile. Verify the
   version supports the config.
2. Authenticate with `wrangler login` and inspect `wrangler whoami`. Confirm
   account selection and entitlements with bounded read-only checks. Do not
   log OAuth tokens; `wrangler auth token --json` output is a secret.
3. Establish the Workers.dev subdomain or requested domain. Set the final
   origin in runtime config and the identity provider.
4. Create only missing storage resources. Put credentials into Worker secrets
   (`secret put` or `secret bulk` with stdin). Adding secrets does not prove a
   running container received them: restart when its environment must change.
5. Run `wrangler deploy --dry-run`; Docker must be available for image-backed
   checks. Test the actual binding/interceptor integration with `wrangler dev`
   using nonproduction secrets and data.
6. Run `wrangler deploy`; allow time for image upload/preparation. Inspect
   deployment/image state before retrying a reported timeout.

`durable_object` scheduling uses an `images` map and image selection in
`ctx.container.start()`. Do not mix this with unrelated legacy config examples.
`container.running` does not mean HTTP is ready. The starter polls health and
observes container exit.

Redeployment does not prove image replacement. Change `settings.revision` for
an image or environment update: on the next request the starter sends SIGTERM,
waits for exit, and starts the new image. Deploy between conversations because
this interrupts sessions. Code rollback also needs the matching image/revision
and a data compatibility review; do not automatically roll state back with code.

One singleton limits routing to one writer, but is not an account spending
control. Unauthenticated requests can start the container in this starter.
Add edge auth and rate/cost controls when the application's exposure warrants
them. Choose instance size and idle timeout from measured needs; long timeouts
keep billable resources alive.

## Current official documentation

Verify these instead of assuming the dated recipe remains current:

- [Container API](https://developers.cloudflare.com/containers/api/durable-object-container/)
- [Get started](https://developers.cloudflare.com/containers/get-started/)
- [Container docs index](https://developers.cloudflare.com/containers/llms.txt)
- [Wrangler configuration](https://developers.cloudflare.com/workers/wrangler/configuration/)
- [Container pricing](https://developers.cloudflare.com/containers/pricing/)
- [Worker-native Agents SDK](https://developers.cloudflare.com/agents/)
