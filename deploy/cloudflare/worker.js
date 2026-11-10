import { DurableObject, WorkerEntrypoint } from "cloudflare:workers";

const PORT = 9173;
const IDLE_MS = 60 * 60 * 1000;
const REVISION = "starter-v1";
const STATE_KEY = "state/v1/state.zip";
const INITIALIZED_KEY = "state/v1/initialized.json";
const VARIABLES = [
  "AUTH0_DOMAIN",
  "AUTH0_CLIENT_ID",
  "AUTH0_AUDIENCE",
  "AUTH0_REQUIRED_SCOPES",
  "AUTH0_REDIRECT_URI",
  "PUBLIC_ORIGIN",
  "MODEL_NAME",
  "MODEL_BASE_URL",
  "CORS_ORIGINS",
  "AGENT_ID",
  "AGENT_NAME",
  "AGENT_DESCRIPTION",
  "AGENT_VERSION",
];

// Container-only outbound bridge. No public route dispatches to this entrypoint.
export class StorageBridge extends WorkerEntrypoint {
  async fetch(request) {
    const path = new URL(request.url).pathname;
    if (path === "/deepagents-state.zip") {
      if (request.method === "GET") {
        const object = await this.env.STATE.get(STATE_KEY);
        if (object) return new Response(object.body);
        return new Response(null, {
          status: (await this.env.STATE.head(INITIALIZED_KEY)) ? 503 : 404,
        });
      }
      if (request.method === "PUT") {
        await this.env.STATE.put(STATE_KEY, request.body);
        await this.env.STATE.put(
          INITIALIZED_KEY,
          JSON.stringify({ release: REVISION }),
        );
        return new Response(null, { status: 204 });
      }
    }
    return new Response(null, { status: 404 });
  }
}

export class AgentContainer extends DurableObject {
  starting;
  constructor(ctx, env) {
    super(ctx, env);
    if (ctx.container?.running) {
      ctx.blockConcurrencyWhile(async () => {
        await ctx.container.interceptOutboundHttp(
          "storage.internal",
          ctx.exports.StorageBridge({}),
        );
        await ctx.container.setInactivityTimeout(IDLE_MS);
      });
      ctx.waitUntil(
        ctx.container
          .monitor()
          .catch(() => console.error("Agent container exited with an error")),
      );
    }
  }
  async ready() {
    const container = this.ctx.container;
    if (
      container.running &&
      (await this.ctx.storage.get("runtimeRevision")) !== REVISION
    ) {
      container.signal(15);
      await container.monitor();
    }
    if (!container.running) {
      await container.interceptOutboundHttp(
        "storage.internal",
        this.ctx.exports.StorageBridge({}),
      );
      const env = Object.fromEntries(
        VARIABLES.filter((key) => this.env[key]).map((key) => [
          key,
          this.env[key],
        ]),
      );
      // Pass only explicitly named secrets/configuration into this container.
      env.MODEL_API_KEY = this.env.MODEL_API_KEY;
      env.DATA_DIR = "/data";
      env.RELEASE_ID = REVISION;
      env.CHECKPOINT_URL = "http://storage.internal/deepagents-state.zip";
      container.start({
        image: container.images.agent,
        instance: "standard-1",
        enableInternet: true,
        env,
      });
      await this.ctx.storage.put("runtimeRevision", REVISION);
      this.ctx.waitUntil(
        container
          .monitor()
          .catch(() => console.error("Agent container exited with an error")),
      );
    }
    await container.setInactivityTimeout(IDLE_MS);
    const port = container.getTcpPort(PORT);
    for (let attempt = 0; attempt < 120; attempt++) {
      try {
        const response = await port.fetch("http://container/health", {
          signal: AbortSignal.timeout(1000),
        });
        const health = await response.json();
        if (
          response.ok &&
          health.status === "ok" &&
          health.engine === "deepagents" &&
          health.release === REVISION &&
          health.model_configured &&
          health.checkpoint?.last_success
        )
          return;
      } catch {
        /* Retry readiness only, never replay user requests. */
      }
      await scheduler.wait(500);
    }
    throw new Error("Agent did not become healthy");
  }
  async fetch(request) {
    this.starting ??= this.ready().finally(() => {
      this.starting = undefined;
    });
    await this.starting;
    const url = new URL(request.url);
    url.protocol = "http:";
    url.host = "container";
    const forwarded = new Request(url, request);
    forwarded.headers.delete("host");
    return this.ctx.container.getTcpPort(PORT).fetch(forwarded);
  }
}
export default {
  async fetch(request, env) {
    if (env.PUBLIC_GATEWAY_READY !== "true")
      return new Response("Configure and verify this deployment first", {
        status: 503,
      });
    try {
      return await env.AGENT.getByName("agent").fetch(request);
    } catch {
      console.error("Agent gateway request failed");
      return new Response("Agent temporarily unavailable", { status: 503 });
    }
  },
};
