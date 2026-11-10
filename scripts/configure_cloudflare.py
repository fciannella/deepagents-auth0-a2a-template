"""Generate a new agent's local Cloudflare config. Does not create or deploy resources."""

import argparse
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
for name in ["name", "account-id", "public-origin", "auth0-domain", "auth0-client-id", "auth0-audience"]:
    parser.add_argument("--" + name, required=True)
parser.add_argument("--scope", default="agent:chat")
args = parser.parse_args()
if not re.fullmatch(r"[a-z][a-z0-9-]{2,49}", args.name):
    parser.error("Use a unique lowercase name (3–50 letters, digits, hyphens)")
if not re.fullmatch(r"[0-9a-f]{32}", args.account_id):
    parser.error("Expected a 32-character Cloudflare account ID")
from app.config import Settings  # noqa: E402

settings = Settings(
    _env_file=None,
    public_origin=args.public_origin,
    auth0_domain=args.auth0_domain,
    auth0_client_id=args.auth0_client_id,
    auth0_audience=args.auth0_audience,
    auth0_required_scopes=args.scope,
)
if not settings.auth_configured:
    parser.error("Supply your own Auth0 application and API settings")
path = root / "deploy/cloudflare/wrangler.jsonc"
config = json.loads((path.parent / "wrangler.example.jsonc").read_text())
config.update(name=args.name, account_id=args.account_id)
config["r2_buckets"][0]["bucket_name"] = args.name + "-state"
config["vars"].update(
    PUBLIC_ORIGIN=settings.public_origin,
    AUTH0_REDIRECT_URI=settings.public_origin + "/",
    AUTH0_DOMAIN=args.auth0_domain,
    AUTH0_CLIENT_ID=args.auth0_client_id,
    AUTH0_AUDIENCE=args.auth0_audience,
    AUTH0_REQUIRED_SCOPES=args.scope,
)
with path.open("x") as output:
    output.write(json.dumps(config, indent=2) + "\n")
print("Created deploy/cloudflare/wrangler.jsonc; gateway remains disabled until verified.")
