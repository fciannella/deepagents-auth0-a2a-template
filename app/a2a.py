"""Blocking A2A 1.0 HTTP+JSON adapter for the companion's text subset."""

import re
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from .auth import Identity

STATE = {"pending": "TASK_STATE_WORKING", "complete": "TASK_STATE_COMPLETED", "failed": "TASK_STATE_FAILED"}
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


def parse_message(body):
    if not isinstance(body, dict) or set(body) - {"message", "configuration", "metadata", "tenant"}:
        raise HTTPException(400, "Expected an A2A text SendMessage request")
    if body.get("tenant", ""):
        raise HTTPException(400, "A tenant override is not supported")
    message = body.get("message")
    if not isinstance(message, dict) or set(message) - {
        "messageId",
        "contextId",
        "role",
        "parts",
        "metadata",
        "taskId",
    }:
        raise HTTPException(400, "Unsupported message fields")
    if message.get("role") != "ROLE_USER" or message.get("taskId"):
        raise HTTPException(400, "Send a new ROLE_USER message; task continuation is not supported")
    message_id = message.get("messageId")
    if not isinstance(message_id, str) or not IDENTIFIER.fullmatch(message_id):
        raise HTTPException(400, "Invalid messageId")
    parts = message.get("parts")
    if (
        not isinstance(parts, list)
        or not 1 <= len(parts) <= 16
        or any(not isinstance(p, dict) or set(p) != {"text"} or not isinstance(p["text"], str) for p in parts)
    ):
        raise HTTPException(400, "Only text parts are supported")
    text = "\n".join(p["text"] for p in parts)
    if not text.strip() or len(text) > 12000:
        raise HTTPException(400, "Send 1–12000 characters of text")
    context = message.get("contextId")
    if context is not None and not isinstance(context, str):
        raise HTTPException(400, "Invalid contextId")
    context = context or None
    try:
        if context:
            context = str(UUID(context))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, "Invalid contextId")
    config = body.get("configuration", {})
    if not isinstance(config, dict) or set(config) - {
        "acceptedOutputModes",
        "returnImmediately",
        "historyLength",
    }:
        raise HTTPException(400, "Unsupported configuration")
    if config.get("returnImmediately", False) is not False:
        raise HTTPException(400, "Only blocking responses are supported")
    modes = config.get("acceptedOutputModes", ["text/plain"])
    if (
        not isinstance(modes, list)
        or not modes
        or any(m not in ("text/plain", "text/markdown") for m in modes)
    ):
        raise HTTPException(400, "Only text output is supported")
    history = config.get("historyLength", 0)
    if type(history) is not int or not 0 <= history <= 100:
        raise HTTPException(400, "historyLength must be between 0 and 100")
    return message_id, text, context, history


def task_row(storage, owner, task_id):
    row = storage.db.execute(
        "SELECT t.*,m.message_id,m.updated FROM turns t LEFT JOIN turn_metadata m "
        "ON m.owner=t.owner AND m.request_id=t.request_id WHERE t.owner=? AND t.request_id=?",
        (owner, task_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Task not found")
    return dict(row)


def project_task(row, history_length=0, artifacts=True):
    task_id, context = row["request_id"], row["thread_id"]
    result = {
        "id": task_id,
        "contextId": context,
        "status": {"state": STATE[row["status"]], "timestamp": row.get("updated") or row["created"]},
    }
    if artifacts and row["output"] is not None:
        result["artifacts"] = [
            {"artifactId": task_id + "-response", "name": "response", "parts": [{"text": row["output"]}]}
        ]
    if history_length:
        history = [
            {
                "messageId": row.get("message_id") or task_id,
                "contextId": context,
                "taskId": task_id,
                "role": "ROLE_USER",
                "parts": [{"text": row["input"]}],
            }
        ]
        if row["output"] is not None:
            history.append(
                {
                    "messageId": task_id + "-reply",
                    "contextId": context,
                    "taskId": task_id,
                    "role": "ROLE_AGENT",
                    "parts": [{"text": row["output"]}],
                }
            )
        result["history"] = history[-history_length:]
    return result


def response(value):
    return JSONResponse(value, media_type="application/a2a+json", headers={"A2A-Version": "1.0"})


def version(request):
    if request.headers.get("a2a-version") != "1.0":
        raise HTTPException(400, "Send A2A-Version: 1.0")


def parameters(request, listing=False):
    version(request)
    values = dict(request.query_params)
    allowed = {"historyLength"}
    if listing:
        allowed |= {
            "pageSize",
            "pageToken",
            "contextId",
            "status",
            "statusTimestampAfter",
            "includeArtifacts",
        }
    if set(values) - allowed or len(values) != len(request.query_params.multi_items()):
        raise HTTPException(400, "Unsupported or repeated query parameter")
    for key, low, high in [("historyLength", 0, 100), ("pageSize", 1, 100)]:
        if key in values and (
            not values[key].isascii() or not values[key].isdigit() or not low <= int(values[key]) <= high
        ):
            raise HTTPException(400, f"Invalid {key}")
    if values.get("pageToken") and not re.fullmatch(r"before-[0-9]{1,19}", values["pageToken"]):
        raise HTTPException(400, "Invalid pageToken")
    if "includeArtifacts" in values and values["includeArtifacts"] not in ("true", "false"):
        raise HTTPException(400, "Invalid includeArtifacts")
    if "status" in values and values["status"] not in STATE.values():
        raise HTTPException(400, "Unsupported status filter")
    if "statusTimestampAfter" in values:
        try:
            value = datetime.fromisoformat(values["statusTimestampAfter"])
            if value.tzinfo is None:
                raise ValueError()
            values["statusTimestampAfter"] = value.astimezone(UTC).isoformat()
        except ValueError:
            raise HTTPException(400, "Invalid statusTimestampAfter")
    return values


def register_a2a(app, settings, auth, execute, input_type):
    @app.get("/.well-known/agent-card.json")
    async def card(identity: Identity = Depends(auth)):
        return response(
            {
                "name": settings.agent_name,
                "version": settings.agent_version,
                "description": settings.agent_description,
                "supportedInterfaces": [
                    {"url": settings.public_origin, "protocolBinding": "HTTP+JSON", "protocolVersion": "1.0"}
                ],
                "capabilities": {"streaming": False, "pushNotifications": False},
                "defaultInputModes": ["text/plain"],
                "defaultOutputModes": ["text/plain"],
                "skills": [
                    {
                        "id": settings.agent_id,
                        "name": settings.agent_name,
                        "description": settings.agent_description,
                        "tags": ["assistant", "text"],
                    }
                ],
                "securitySchemes": {
                    "auth0": {
                        "oauth2SecurityScheme": {
                            "flows": {
                                "authorizationCode": {
                                    "authorizationUrl": settings.issuer + "authorize",
                                    "tokenUrl": settings.issuer + "oauth/token",
                                    "scopes": {
                                        s: "Chat with the companion"
                                        for s in settings.auth0_required_scopes.split()
                                    },
                                    "pkceRequired": True,
                                }
                            }
                        }
                    }
                },
                "securityRequirements": [
                    {"schemes": {"auth0": {"list": settings.auth0_required_scopes.split()}}}
                ],
            }
        )

    @app.post("/message:send")
    async def send(request: Request, identity: Identity = Depends(auth)):
        version(request)
        if request.headers.get("content-type", "").split(";")[0].lower() not in {
            "application/json",
            "application/a2a+json",
        }:
            raise HTTPException(415, "Use application/a2a+json")
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(400, "Invalid JSON")
        message_id, text, context, history = parse_message(body)
        request_id = uuid5(NAMESPACE_URL, "deepagents:a2a:" + identity.owner + "\0" + message_id)
        try:
            await execute(
                input_type(message=text, request_id=request_id, thread_id=context),
                identity,
                message_id,
                body,
            )
        except HTTPException as error:
            if error.status_code != 502:
                raise
        return response(
            {"task": project_task(task_row(app.state.storage, identity.owner, str(request_id)), history)}
        )

    @app.get("/tasks/{task_id}")
    async def get_task(task_id: UUID, request: Request, identity: Identity = Depends(auth)):
        query = parameters(request)
        return response(
            project_task(
                task_row(app.state.storage, identity.owner, str(task_id)), int(query.get("historyLength", 0))
            )
        )

    @app.get("/tasks")
    async def tasks(request: Request, identity: Identity = Depends(auth)):
        query = parameters(request, True)
        clauses, args = ["t.owner=?"], [identity.owner]
        for key, column in [("contextId", "t.thread_id"), ("status", "t.status")]:
            if key in query:
                clauses.append(column + "=?")
                args.append(
                    next(k for k, v in STATE.items() if v == query[key]) if key == "status" else query[key]
                )
        if "statusTimestampAfter" in query:
            clauses.append("COALESCE(m.updated,t.created)>?")
            args.append(query["statusTimestampAfter"])
        source = (
            " FROM turns t LEFT JOIN turn_metadata m ON m.owner=t.owner AND m.request_id=t.request_id WHERE "
        )
        total = app.state.storage.db.execute(
            "SELECT count(*)" + source + " AND ".join(clauses), args
        ).fetchone()[0]
        if query.get("pageToken"):
            clauses.append("t.rowid<?")
            args.append(int(query["pageToken"].split("-")[1]))
        size = int(query.get("pageSize", 50))
        rows = list(
            app.state.storage.db.execute(
                "SELECT t.rowid AS sequence,t.*,m.message_id,m.updated"
                + source
                + " AND ".join(clauses)
                + " ORDER BY t.rowid DESC LIMIT ?",
                [*args, size + 1],
            )
        )
        return response(
            {
                "tasks": [
                    project_task(
                        dict(row), int(query.get("historyLength", 0)), query.get("includeArtifacts") == "true"
                    )
                    for row in rows[:size]
                ],
                "totalSize": total,
                "pageSize": size,
                "nextPageToken": f"before-{rows[size - 1]['sequence']}" if len(rows) > size else "",
            }
        )
