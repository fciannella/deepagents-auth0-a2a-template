import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from app.auth import Authenticator
from app.config import Settings


@pytest.fixture
def verifier():
    settings = Settings(_env_file=None)
    auth = Authenticator(settings)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    auth.jwks.get_signing_key_from_jwt = lambda token: SimpleNamespace(key=key.public_key())
    return auth, key, settings


def token(verifier, **changes):
    auth, key, settings = verifier
    claims = dict(
        iss=settings.issuer,
        aud=settings.auth0_audience,
        sub="auth0|alice",
        exp=int(time.time()) + 600,
        iat=int(time.time()),
        scope="openid agent:chat",
    )
    claims.update(changes)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})


def test_identity_is_stable_and_subject_scoped(verifier):
    auth, _, _ = verifier
    assert auth.verify(token(verifier)).owner == auth.verify(token(verifier)).owner
    assert auth.verify(token(verifier)).owner != auth.verify(token(verifier, sub="auth0|bob")).owner


@pytest.mark.parametrize(
    "changes,status",
    [
        ({"aud": "other-api"}, 401),
        ({"iss": "https://evil.example/"}, 401),
        ({"exp": 1}, 401),
        ({"scope": "openid"}, 403),
        ({"sub": "machine@clients"}, 401),
        ({"sub": ""}, 401),
        ({"iat": int(time.time()) + 3600}, 401),
    ],
)
def test_invalid_tokens(verifier, changes, status):
    with pytest.raises(HTTPException) as error:
        verifier[0].verify(token(verifier, **changes))
    assert error.value.status_code == status


def test_invalid_signature(verifier):
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode({"sub": "auth0|alice"}, other_key, algorithm="RS256")
    with pytest.raises(HTTPException) as error:
        verifier[0].verify(forged)
    assert error.value.status_code == 401
