/* The UI is an A2A client. Access tokens remain in the Auth0 SDK's memory cache. */
const el = (id) => document.getElementById(id);
let client,
  config,
  authenticated = false,
  busy = false,
  context = null,
  pageToken = "",
  listed = [];
function notice(text, error = false) {
  el("notice").textContent = text;
  el("notice").classList.toggle("error", error);
}
function controls() {
  for (const id of ["message", "send", "new", "more"])
    el(id).disabled = busy || !authenticated;
  el("logout").disabled = busy;
  document
    .querySelectorAll("#contexts button")
    .forEach((b) => (b.disabled = busy));
}
async function api(path, options = {}) {
  const token = await client.getTokenSilently();
  const response = await fetch(path, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      "A2A-Version": "1.0",
      "Content-Type": "application/a2a+json",
    },
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      data.detail || data.title || `Request failed (${response.status}).`,
    );
  return data;
}
function addMessage(role, text) {
  el("welcome").hidden = true;
  const article = document.createElement("article");
  article.className = `message ${role}`;
  const label = document.createElement("span");
  label.className = "label";
  label.textContent = role === "user" ? "You" : config.name;
  article.append(label, document.createTextNode(text));
  el("messages").append(article);
}
function showTask(task) {
  const user = (task.history || []).find((m) => m.role === "ROLE_USER");
  if (user) addMessage("user", user.parts.map((p) => p.text || "").join("\n"));
  const reply = (task.artifacts || [])
    .flatMap((a) => a.parts || [])
    .map((p) => p.text || "")
    .join("\n");
  addMessage(
    "assistant",
    reply ||
      (task.status.state === "TASK_STATE_FAILED"
        ? "This turn failed. You can inspect it and continue with a new message."
        : "This turn is still in progress."),
  );
}
async function refresh(reset = true) {
  if (reset) {
    listed = [];
    pageToken = "";
  }
  const params = new URLSearchParams({ pageSize: "50", historyLength: "1" });
  if (pageToken) params.set("pageToken", pageToken);
  const result = await api(`/tasks?${params}`);
  listed.push(...result.tasks);
  pageToken = result.nextPageToken;
  el("more").hidden = !pageToken;
  el("contexts").replaceChildren();
  const seen = new Set();
  for (const task of listed) {
    if (seen.has(task.contextId)) continue;
    seen.add(task.contextId);
    const button = document.createElement("button");
    button.textContent = `Conversation · ${task.contextId.slice(0, 8)}`;
    button.classList.toggle("active", task.contextId === context);
    button.onclick = () => openContext(task.contextId);
    el("contexts").append(button);
  }
  controls();
}
async function openContext(id) {
  if (busy) return;
  busy = true;
  controls();
  try {
    const tasks = [];
    let token = "";
    do {
      const params = new URLSearchParams({
        contextId: id,
        pageSize: "100",
        includeArtifacts: "true",
        historyLength: "2",
      });
      if (token) params.set("pageToken", token);
      const result = await api(`/tasks?${params}`);
      tasks.push(...result.tasks);
      token = result.nextPageToken;
    } while (token);
    context = id;
    el("messages").replaceChildren();
    tasks.reverse().forEach(showTask);
    await refresh();
    notice("Conversation restored.");
  } catch (error) {
    notice(error.message, true);
  } finally {
    busy = false;
    controls();
  }
}
el("composer").onsubmit = async (event) => {
  event.preventDefault();
  const text = el("message").value.trim();
  if (!authenticated || busy || !text) return;
  busy = true;
  controls();
  addMessage("user", text);
  el("message").value = "";
  notice("Working…");
  const message = {
    messageId: crypto.randomUUID(),
    role: "ROLE_USER",
    parts: [{ text }],
  };
  if (context) message.contextId = context;
  try {
    const { task } = await api("/message:send", {
      method: "POST",
      body: JSON.stringify({ message }),
    });
    context = task.contextId;
    const reply = (task.artifacts || [])
      .flatMap((a) => a.parts || [])
      .map((p) => p.text || "")
      .join("\n");
    addMessage(
      "assistant",
      reply ||
        "The turn did not complete. Check the conversation before sending a new message.",
    );
    notice(
      task.status.state === "TASK_STATE_COMPLETED"
        ? "Saved to your account."
        : "The task failed. A new message creates a new turn.",
      task.status.state !== "TASK_STATE_COMPLETED",
    );
    await refresh();
  } catch (error) {
    notice(
      `${error.message} Outcome may be uncertain. Open the conversation history before retrying. Message ID: ${message.messageId}`,
      true,
    );
    try {
      await refresh();
    } catch (_) {
      /* Keep the original error. */
    }
  } finally {
    busy = false;
    controls();
    el("message").focus();
  }
};
el("message").onkeydown = (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    el("composer").requestSubmit();
  }
};
el("new").onclick = () => {
  context = null;
  el("messages").replaceChildren();
  el("welcome").hidden = false;
  notice("Start a new conversation.");
  refresh().catch((e) => notice(e.message, true));
};
el("more").onclick = () => refresh(false).catch((e) => notice(e.message, true));
el("login").onclick = () =>
  client?.loginWithRedirect().catch((e) => notice(e.message, true));
el("logout").onclick = () =>
  client.logout({ logoutParams: { returnTo: config.redirectUri } });
async function start() {
  config = await (await fetch("/api/config")).json();
  document.title = config.name;
  el("brand").textContent = config.name;
  el("description").textContent = config.description;
  if (!config.configured) {
    el("login").textContent = "Setup required";
    notice("Configure Auth0 in .env and restart the container.", true);
    return;
  }
  if (location.origin !== new URL(config.redirectUri).origin)
    throw new Error(
      `Open ${config.redirectUri} for the configured sign-in callback.`,
    );
  client = await auth0.createAuth0Client({
    domain: config.domain,
    clientId: config.clientId,
    cacheLocation: "memory",
    authorizationParams: {
      audience: config.audience,
      redirect_uri: config.redirectUri,
      scope: `openid profile email ${config.scope}`,
    },
  });
  const params = new URLSearchParams(location.search);
  if (params.has("error")) {
    const text = params.get("error_description") || "Sign-in failed";
    history.replaceState({}, "", "/");
    throw new Error(text);
  }
  if (params.has("code") && params.has("state")) {
    await client.handleRedirectCallback();
    history.replaceState({}, "", "/");
  }
  authenticated = await client.isAuthenticated();
  el("login").disabled = false;
  el("login").textContent = "Sign in";
  el("login").hidden = authenticated;
  el("logout").hidden = !authenticated;
  controls();
  notice(
    authenticated ? "Ready when you are." : "Sign in to start a conversation.",
  );
  if (authenticated) await refresh();
}
start().catch((e) => notice(e.message, true));
