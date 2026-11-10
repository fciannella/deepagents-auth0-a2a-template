"""Real model + real JWT validation; synthetic JWKS and disposable state, no Auth0 tenant needed.
Run in the container: docker compose exec -T agent python - < scripts/smoke_model.py
Requires MODEL_API_KEY in the container. Does not touch its live /data.
"""

import asyncio
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import Settings
from app.main import create_app


async def main():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with TemporaryDirectory() as directory:
        settings = Settings(
            data_dir=Path(directory),
            auth0_domain="smoke.auth0.com",
            auth0_client_id="synthetic-client",
            auth0_audience="https://smoke.example/api",
            auth0_required_scopes="agent:chat",
            checkpoint_url="",
        )
        if not settings.model_api_key:
            raise RuntimeError("Configure MODEL_API_KEY before running the real-model smoke test")

        def headers(subject):
            token = jwt.encode(
                {
                    "iss": settings.issuer,
                    "aud": settings.auth0_audience,
                    "sub": subject,
                    "iat": int(time.time()),
                    "exp": int(time.time()) + 600,
                    "scope": "agent:chat",
                },
                key,
                algorithm="RS256",
            )
            return {"Authorization": "Bearer " + token, "A2A-Version": "1.0"}

        def build():
            app = create_app(settings)
            app.state.auth.jwks.get_signing_key_from_jwt = lambda token: SimpleNamespace(key=key.public_key())
            return app

        app = build()
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers=headers("auth0|alice"),
                timeout=150,
            ) as client,
        ):
            request = {
                "message": {
                    "messageId": "smoke-1",
                    "role": "ROLE_USER",
                    "parts": [
                        {
                            "text": "Synthetic integration test: the test phrase for this conversation is amber telescope. Acknowledge it briefly. Do not save a personal memory."
                        }
                    ],
                }
            }
            result = await client.post("/message:send", json=request)
            assert result.status_code == 200, result.text
            task = result.json()["task"]
            assert task["status"]["state"] == "TASK_STATE_COMPLETED", task
            assert "amber telescope" in task["artifacts"][0]["parts"][0]["text"].lower()
            assert (await client.post("/message:send", json=request)).json()["task"] == task
            assert (await client.get("/tasks/" + task["id"], headers=headers("auth0|bob"))).status_code == 404
            assert (await client.get("/tasks", headers=headers("auth0|bob"))).json()["tasks"] == []
        app = build()
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers=headers("auth0|alice"),
                timeout=150,
            ) as client,
        ):
            result = await client.post(
                "/message:send",
                json={
                    "message": {
                        "messageId": "smoke-2",
                        "contextId": task["contextId"],
                        "role": "ROLE_USER",
                        "parts": [
                            {
                                "text": "What was the exact test phrase from the previous message? Reply with only that phrase."
                            }
                        ],
                    }
                },
            )
            continued = result.json()["task"]
            assert continued["status"]["state"] == "TASK_STATE_COMPLETED", continued
            assert "amber telescope" in continued["artifacts"][0]["parts"][0]["text"].lower()
            assert continued["contextId"] == task["contextId"]
    print("PASS: real model, A2A, signed JWTs, replay, cross-owner denial, restart and continuation.")


asyncio.run(main())
