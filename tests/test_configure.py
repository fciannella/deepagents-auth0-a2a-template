import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_clone_config_generator_is_portable_and_refuses_overwrite(tmp_path):
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "scripts").mkdir()
    deployment = tmp_path / "deploy/cloudflare"
    deployment.mkdir(parents=True)
    shutil.copyfile(root / "scripts/configure_cloudflare.py", tmp_path / "scripts/configure_cloudflare.py")
    shutil.copyfile(root / "deploy/cloudflare/wrangler.example.jsonc", deployment / "wrangler.example.jsonc")
    command = [
        sys.executable,
        str(tmp_path / "scripts/configure_cloudflare.py"),
        "--name",
        "sample-agent",
        "--account-id",
        "0" * 32,
        "--public-origin",
        "https://sample.example.com",
        "--auth0-domain",
        "sample.auth0.com",
        "--auth0-client-id",
        "sample-client",
        "--auth0-audience",
        "https://sample.example/api",
    ]
    env = {**os.environ, "PYTHONPATH": str(root)}
    result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    config = json.loads((deployment / "wrangler.jsonc").read_text())
    assert config["vars"]["PUBLIC_GATEWAY_READY"] == "false"
    assert config["r2_buckets"][0]["bucket_name"] == "sample-agent-state"
    assert config["vars"]["AUTH0_REDIRECT_URI"] == "https://sample.example.com/"
    assert subprocess.run(command, cwd=tmp_path, env=env, capture_output=True).returncode != 0
