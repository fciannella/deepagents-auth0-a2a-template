import hashlib
from dataclasses import dataclass

import jwt
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool

from .config import Settings


@dataclass(frozen=True)
class Identity:
    owner: str


class Authenticator:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.jwks = jwt.PyJWKClient(settings.issuer + ".well-known/jwks.json", lifespan=300, timeout=10)

    def verify(self, token: str) -> Identity:
        try:
            key = self.jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self.settings.auth0_audience,
                issuer=self.settings.issuer,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
            if not isinstance(claims["sub"], str) or not claims["sub"] or claims["sub"].endswith("@clients"):
                raise jwt.InvalidTokenError("End-user token required")
            scope = claims.get("scope", "")
            if not isinstance(scope, str):
                raise jwt.InvalidTokenError("Invalid scope claim")
            scopes = set(scope.split())
            if not set(self.settings.auth0_required_scopes.split()) <= scopes:
                raise HTTPException(403, "Required permission is missing")
            owner = hashlib.sha256((claims["iss"] + "\0" + claims["sub"]).encode()).hexdigest()
            return Identity(owner)
        except jwt.PyJWTError:
            raise HTTPException(
                401, "Invalid or expired access token", headers={"WWW-Authenticate": "Bearer"}
            )

    async def __call__(self, request: Request) -> Identity:
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token or len(token) > 16384:
            raise HTTPException(401, "Sign in to continue", headers={"WWW-Authenticate": "Bearer"})
        if not self.settings.auth_configured:
            raise HTTPException(503, "Auth0 is not configured")
        return await run_in_threadpool(self.verify, token)
