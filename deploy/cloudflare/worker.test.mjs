import { readFile } from "node:fs/promises";
import test from "node:test";
import assert from "node:assert/strict";
const source = (
  await readFile(new URL("./worker.js", import.meta.url), "utf8")
).replace(
  'import { DurableObject, WorkerEntrypoint } from "cloudflare:workers";',
  "class DurableObject {} class WorkerEntrypoint {}",
);
const { StorageBridge, default: worker } = await import(
  "data:text/javascript;base64," + Buffer.from(source).toString("base64")
);
test("first boot is empty; missing initialized state fails closed; bridge stays private", async () => {
  const values = new Map();
  const bridge = new StorageBridge();
  bridge.env = {
    STATE: {
      async get(key) {
        return values.has(key) ? { body: values.get(key) } : null;
      },
      async head(key) {
        return values.has(key) ? {} : null;
      },
      async put(key, body) {
        values.set(
          key,
          typeof body === "string" ? body : await new Response(body).text(),
        );
      },
    },
  };
  const url = "http://storage.internal/deepagents-state.zip";
  assert.equal((await bridge.fetch(new Request(url))).status, 404);
  assert.equal(
    (
      await bridge.fetch(
        new Request(url, { method: "PUT", body: "checkpoint" }),
      )
    ).status,
    204,
  );
  assert.equal(
    await (await bridge.fetch(new Request(url))).text(),
    "checkpoint",
  );
  values.delete("state/v1/state.zip");
  assert.equal((await bridge.fetch(new Request(url))).status, 503);
  assert.equal(
    (await bridge.fetch(new Request("http://storage.internal/legacy.sqlite")))
      .status,
    404,
  );
  assert.equal(
    (await worker.fetch(new Request("https://example.com/"), {})).status,
    503,
  );
});
