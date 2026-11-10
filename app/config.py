from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    agent_id: str = "generic-assistant"
    agent_name: str = "Deep Agent"
    agent_description: str = "A configurable text assistant."
    agent_version: str = "0.1.0"
    auth0_domain: str = "example.invalid"
    auth0_client_id: str = "configure-me"
    auth0_audience: str = "https://example.invalid/api"
    auth0_required_scopes: str = "agent:chat"
    auth0_redirect_uri: str = ""
    public_origin: str = "http://localhost:9183"
    cors_origins: list[str] = []
    model_name: str = "google/gemini-3.1-flash-lite"
    model_base_url: str = "https://openrouter.ai/api/v1"
    model_api_key: str = Field(default="", repr=False)
    data_dir: Path = Path("data")
    prompt_file: Path = Path("agent/prompt.md")
    turn_timeout_seconds: int = Field(default=120, ge=10, le=120)
    max_concurrent_turns: int = Field(default=8, ge=1, le=100)
    checkpoint_url: str = ""
    checkpoint_interval_seconds: int = Field(default=30, ge=5)
    release_id: str = "local"

    @model_validator(mode="after")
    def validate_settings(self):
        if not self.auth0_domain or any(c in self.auth0_domain for c in "/ :?#"):
            raise ValueError("AUTH0_DOMAIN must be a tenant hostname")
        if not self.auth0_required_scopes.strip():
            raise ValueError("At least one required API scope must be configured")
        self.public_origin = self.public_origin.rstrip("/")
        for origin in [self.public_origin, *self.cors_origins]:
            parsed = urlsplit(origin)
            if (
                (
                    parsed.scheme != "https"
                    and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"})
                )
                or not parsed.netloc
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username
            ):
                raise ValueError("Origins must be HTTPS origins or loopback HTTP origins, without paths")
        if self.auth0_redirect_uri and self.auth0_redirect_uri not in {
            self.public_origin,
            self.public_origin + "/",
        }:
            raise ValueError("AUTH0_REDIRECT_URI must match PUBLIC_ORIGIN (optional trailing slash)")
        return self

    @property
    def issuer(self):
        return f"https://{self.auth0_domain}/"

    @property
    def auth_configured(self):
        return bool(
            self.auth0_client_id
            and self.auth0_audience
            and self.auth0_client_id != "configure-me"
            and not self.auth0_domain.endswith(".invalid")
            and "example.invalid" not in self.auth0_audience
        )
