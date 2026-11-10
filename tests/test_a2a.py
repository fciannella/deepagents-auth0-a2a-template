import time
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.config import Settings
from app.main import create_app
from app.storage import Storage


class ToolModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class HistoryModel(ToolModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        text = " | ".join(m.content for m in messages if m.type == "human")
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


@pytest.fixture
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def app_for(path, key, responses=None):
    settings = Settings(
        _env_file=None,
        data_dir=path,
        auth0_domain="test.auth0.com",
        auth0_client_id="test-client",
        auth0_audience="https://test.example/api",
    )
    model = (
        ToolModel(responses=responses) if responses else HistoryModel(responses=[AIMessage(content="unused")])
    )
    app = create_app(settings, model)
    app.state.auth.jwks.get_signing_key_from_jwt = lambda token: SimpleNamespace(key=key.public_key())
    return app


def headers(key, sub="auth0|alice", **claims):
    payload = {
        "iss": "https://test.auth0.com/",
        "aud": "https://test.example/api",
        "sub": sub,
        "iat": int(time.time()),
        "exp": int(time.time()) + 600,
        "scope": "agent:chat",
    }
    payload.update(claims)
    return {"Authorization": "Bearer " + jwt.encode(payload, key, algorithm="RS256"), "A2A-Version": "1.0"}


def body(text="Hello", context=None, message_id=None):
    message = {"messageId": message_id or str(uuid4()), "role": "ROLE_USER", "parts": [{"text": text}]}
    if context:
        message["contextId"] = context
    return {"message": message}


def reply(task):
    return task["artifacts"][0]["parts"][0]["text"]


def test_signed_a2a_continuation_restart_replay_and_isolation(tmp_path, key):
    first = body("amber telescope")
    with TestClient(app_for(tmp_path, key), headers=headers(key)) as client:
        card = client.get("/.well-known/agent-card.json").json()
        assert card["name"] == "Deep Agent" and card["supportedInterfaces"][0]["protocolVersion"] == "1.0"
        task = client.post("/message:send", json=first).json()["task"]
        assert reply(task) == "amber telescope"
        assert client.post("/message:send", json=first).json()["task"] == task
        changed = {**first, "configuration": {"historyLength": 2}}
        assert client.post("/message:send", json=changed).status_code == 409
        assert client.get("/tasks/" + task["id"], headers=headers(key, "auth0|bob")).status_code == 404
        assert (
            client.post(
                "/message:send", json=body("steal", task["contextId"]), headers=headers(key, "auth0|bob")
            ).status_code
            == 404
        )
        assert client.get("/tasks", headers=headers(key, "auth0|bob")).json()["tasks"] == []
    with TestClient(app_for(tmp_path, key), headers=headers(key)) as client:
        assert client.post("/message:send", json=first).json()["task"] == task
        continued = client.post("/message:send", json=body("continue", task["contextId"])).json()["task"]
        assert reply(continued) == "amber telescope | continue"
        assert continued["contextId"] == task["contextId"]
        listing = client.get("/tasks?pageSize=1&includeArtifacts=true&historyLength=2").json()
        assert listing["totalSize"] == 2 and len(listing["tasks"][0]["history"]) == 2
        older = client.get("/tasks", params={"pageSize": 1, "pageToken": listing["nextPageToken"]}).json()
        assert older["tasks"][0]["id"] == task["id"] and not older["nextPageToken"]
        assert "artifacts" not in older["tasks"][0]


def test_memory_tools_are_owner_bound_and_persistent(tmp_path, key):
    responses = [
        AIMessage(
            content="",
            tool_calls=[
                {"id": "save1", "name": "memory_remember", "args": {"key": "favorite_color", "value": "teal"}}
            ],
        ),
        AIMessage(content="Saved teal."),
    ]
    with TestClient(app_for(tmp_path, key, responses), headers=headers(key)) as client:
        task = client.post("/message:send", json=body("Remember my favorite color is teal")).json()["task"]
        assert reply(task) == "Saved teal."
    db = Storage(tmp_path / "app.sqlite")
    assert db.db.execute("SELECT count(*) FROM memories").fetchone()[0] == 1
    assert db.memory_page("another-owner")["items"] == []
    db.db.close()


def test_memory_capacity_is_storage_not_item_count(tmp_path):
    db = Storage(tmp_path / "app.sqlite")
    for n in range(131):
        db.remember("alice", f"fact-{n:03}", "value " + str(n))
    assert len(db.memory_page("alice")["items"]) == 50
    assert db.memory_page("alice", offset=100)["next_offset"] is None
    assert len(db.memory_page("alice", offset=100)["items"]) == 31
    assert db.memory_page("bob")["items"] == []
    db.db.close()
    db = Storage(tmp_path / "app.sqlite")
    assert db.db.execute("SELECT count(*) FROM memories").fetchone()[0] == 131
    db.db.close()


@pytest.mark.parametrize(
    "claims,status",
    [
        ({"aud": "wrong"}, 401),
        ({"exp": 1}, 401),
        ({"scope": "openid"}, 403),
        ({"sub": "machine@clients"}, 401),
    ],
)
def test_signed_http_auth_rejection(tmp_path, key, claims, status):
    with TestClient(app_for(tmp_path, key)) as client:
        result = client.get("/tasks", headers=headers(key, **claims))
        assert result.status_code == status
        assert result.headers["content-type"].startswith("application/problem+json")
        assert result.json()["status"] == status


def test_validation_private_routes_and_cors(tmp_path, key):
    with TestClient(app_for(tmp_path, key)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/tasks").status_code == 401
        client.headers.update(headers(key))
        for path in ["/admin", "/runtime.sqlite", "/deepagents-state.zip", "/api/chat"]:
            assert client.get(path).status_code == 404
        assert client.get("/tasks", headers={"Origin": "https://evil.example"}).status_code == 403
        assert (
            client.options(
                "/message:send",
                headers={
                    "Origin": "http://localhost:9183",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization,a2a-version,content-type",
                },
            ).status_code
            == 200
        )
        assert client.post("/message:send", content=b"x" * 65537).status_code == 413
        assert client.post("/message:send", json=body(), headers={"A2A-Version": "0.3"}).status_code == 400
        assert (
            client.post("/message:send", json=body(), headers={"Content-Type": "text/plain"}).status_code
            == 415
        )
        assert (
            client.post(
                "/message:send", json={**body(), "configuration": {"returnImmediately": True}}
            ).status_code
            == 400
        )
        bad = body()
        bad["message"]["parts"] = [{"file": {"uri": "https://example.com"}}]
        assert client.post("/message:send", json=bad).status_code == 400
        assert client.get("/tasks?pageSize=0").status_code == 400
        assert client.get("/tasks?unknown=1").status_code == 400
        assert client.get("/tasks/not-a-uuid").status_code == 400
        assert "frame-ancestors 'none'" in client.get("/").headers["content-security-policy"]


def test_failure_is_recorded_and_replayed_without_provider_details(tmp_path, key, monkeypatch):
    calls = []

    async def fail(*args):
        calls.append(True)
        raise RuntimeError("private provider error")

    monkeypatch.setattr("app.main.run_turn", fail)
    request = body()
    with TestClient(app_for(tmp_path, key), headers=headers(key)) as client:
        result = client.post("/message:send", json=request)
        assert result.status_code == 200
        assert result.json()["task"]["status"]["state"] == "TASK_STATE_FAILED"
        assert "private provider" not in result.text
        assert client.post("/message:send", json=request).json() == result.json()
        assert len(calls) == 1


def test_unconfigured_startup_explains_setup(tmp_path):
    with TestClient(create_app(Settings(_env_file=None, data_dir=tmp_path))) as client:
        assert client.get("/").status_code == 200
        assert client.get("/health").status_code == 503
        assert client.get("/api/config").json()["configured"] is False
        assert client.get("/tasks").status_code == 401


@pytest.mark.asyncio
async def test_overlapping_turns_and_capacity(tmp_path, key, monkeypatch):
    import asyncio

    import httpx

    started, release = asyncio.Event(), asyncio.Event()

    async def slow(*args):
        started.set()
        await release.wait()
        return "Done"

    monkeypatch.setattr("app.main.run_turn", slow)
    app = app_for(tmp_path, key)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", headers=headers(key)
        ) as client,
    ):
        pending = asyncio.create_task(client.post("/message:send", json=body()))
        await started.wait()
        assert (await client.post("/message:send", json=body())).status_code == 409
        assert (await client.get("/tasks")).json()["tasks"][0]["status"]["state"] == "TASK_STATE_WORKING"
        release.set()
        assert (await pending).json()["task"]["status"]["state"] == "TASK_STATE_COMPLETED"
