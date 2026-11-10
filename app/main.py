import asyncio
import hashlib
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from .a2a import register_a2a
from .agent import build_model, run_turn
from .auth import Authenticator
from .checkpoints import Checkpoints, StateGate
from .config import Settings
from .storage import Storage

logger = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"


class ChatInput(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    request_id: UUID
    thread_id: UUID | None = None


def problem(status, detail, headers=None):
    return JSONResponse(
        {"type": "about:blank", "title": "Request rejected", "status": status, "detail": detail},
        status_code=status,
        headers={"A2A-Version": "1.0", **(headers or {})},
        media_type="application/problem+json",
    )


def create_app(settings=None, model=None):
    settings = settings or Settings()
    auth, gate = Authenticator(settings), StateGate()
    active = set()

    @asynccontextmanager
    async def lifespan(app):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        checkpoints = Checkpoints(settings, gate) if settings.checkpoint_url else None
        app.state.checkpoints = checkpoints
        if checkpoints:
            await checkpoints.restore()
        storage = Storage(settings.data_dir / "app.sqlite")
        app.state.storage = storage
        app.state.model = model or (build_model(settings) if settings.model_api_key else None)
        prompt = settings.prompt_file.read_text()
        app.state.prompt = prompt
        try:
            async with AsyncSqliteSaver.from_conn_string(
                str(settings.data_dir / "checkpoints.sqlite")
            ) as saver:
                await saver.setup()
                app.state.saver = saver
                if checkpoints:
                    await checkpoints.start()
                try:
                    yield
                finally:
                    if checkpoints:
                        await checkpoints.close()
        finally:
            storage.db.close()

    app = FastAPI(
        title=settings.agent_name, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.auth = auth
    origins = [settings.public_origin, *settings.cors_origins]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "A2A-Version"],
        expose_headers=["A2A-Version"],
        allow_credentials=False,
    )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, error):
        return problem(error.status_code, str(error.detail), error.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return problem(400, "Invalid request parameters")

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.headers.get("origin") and request.headers["origin"] not in origins:
            return problem(403, "Origin not allowed")
        # Enforce actual bytes, including requests without Content-Length.
        if request.method == "POST":
            body = bytearray()
            try:
                async with asyncio.timeout(15):
                    async for chunk in request.stream():
                        body.extend(chunk)
                        if len(body) > 65536:
                            return problem(413, "Request body exceeds 64 KiB")
            except TimeoutError:
                return problem(408, "Request body timed out")
            request._body = bytes(body)
            async with gate.operation():
                result = await call_next(request)
        else:
            result = await call_next(request)
        result.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": f"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self' {settings.issuer.rstrip('/')}; frame-src {settings.issuer.rstrip('/')}; worker-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
            }
        )
        return result

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/health")
    async def health():
        ready = settings.auth_configured and app.state.model is not None
        result = {
            "status": "ok" if ready else "needs_configuration",
            "engine": "deepagents",
            "release": settings.release_id,
            "auth_configured": settings.auth_configured,
            "model_configured": app.state.model is not None,
        }
        if app.state.checkpoints:
            result["checkpoint"] = {
                "last_success": app.state.checkpoints.last_success,
                "last_error": app.state.checkpoints.last_error,
            }
        return JSONResponse(result, status_code=200 if ready else 503)

    @app.get("/api/config")
    async def config():
        return {
            "name": settings.agent_name,
            "description": settings.agent_description,
            "configured": settings.auth_configured,
            "domain": settings.auth0_domain,
            "clientId": settings.auth0_client_id,
            "audience": settings.auth0_audience,
            "scope": settings.auth0_required_scopes,
            "redirectUri": settings.auth0_redirect_uri or settings.public_origin,
        }

    async def execute(body, identity, message_id, payload):
        owner, request_id = identity.owner, str(body.request_id)
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if owner in active:
            raise HTTPException(409, "A turn is already running for this account")
        if len(active) >= settings.max_concurrent_turns:
            raise HTTPException(429, "Agent is busy; retry later")
        active.add(owner)
        try:
            storage = app.state.storage
            prior = storage.request(owner, request_id)
            if prior:
                if prior["fingerprint"] != fingerprint:
                    raise HTTPException(409, "messageId was already used with a different payload")
                return  # Completed or failed: replay recorded outcome, never rerun tools.
            if app.state.model is None:
                raise HTTPException(503, "Model is not configured")
            thread = storage.resolve(owner, str(body.thread_id) if body.thread_id else None)
            storage.start(
                owner,
                request_id,
                thread,
                body.message,
                message_id,
                str(body.thread_id) if body.thread_id else None,
                fingerprint,
            )
            try:
                async with asyncio.timeout(settings.turn_timeout_seconds):
                    reply = await run_turn(
                        app.state.model,
                        app.state.saver,
                        storage,
                        owner,
                        thread,
                        app.state.prompt,
                        body.message,
                    )
                storage.finish(owner, request_id, reply)
            except asyncio.CancelledError:
                storage.finish(owner, request_id)
                raise
            except Exception as error:
                storage.finish(owner, request_id)
                logger.warning("Agent turn failed (%s)", type(error).__name__)
        finally:
            active.discard(owner)

    register_a2a(app, settings, auth, execute, ChatInput)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
