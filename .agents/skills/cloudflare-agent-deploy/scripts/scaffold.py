#!/usr/bin/env python3
"""Create local Cloudflare hosting files for a project; no remote side effects."""
import argparse
from datetime import date
import json
import os
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--dockerfile", default="Dockerfile")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--health-path", default="/health")
    parser.add_argument("--env", action="append", default=[], help="Environment NAME to forward, not its value")
    parser.add_argument("--r2-bucket", help="Optional existing or planned project-specific bucket name")
    parser.add_argument("--instance", default="lite")
    parser.add_argument("--idle-seconds", type=int, default=300)
    parser.add_argument("--compatibility-date", default=date.today().isoformat())
    parser.add_argument("--wrangler-version", default="4.160.0")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", args.name):
        parser.error("name must be 1–63 lowercase letters, digits, or hyphens, starting with a letter")
    if not re.fullmatch(r"[a-fA-F0-9]{32}", args.account_id):
        parser.error("account-id must be the 32-character Cloudflare account ID")
    if not 1 <= args.port <= 65535 or not 1 <= args.idle_seconds <= 86400:
        parser.error("port must be 1–65535; idle-seconds must be 1–86400")
    if not re.fullmatch(r"/[A-Za-z0-9/_-]*", args.health_path):
        parser.error("health-path must be an absolute HTTP path without a query")
    if any(not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) for key in args.env):
        parser.error("--env accepts uppercase environment names, never NAME=value")
    if args.r2_bucket and not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", args.r2_bucket):
        parser.error("r2-bucket must be 3–63 lowercase letters/digits/hyphens, without edge hyphens")
    if not re.fullmatch(r"[a-z][a-z0-9-]*", args.instance):
        parser.error("invalid instance type; verify the type against current Cloudflare docs")
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.wrangler_version):
        parser.error("wrangler-version must be an exact release version")
    try:
        date.fromisoformat(args.compatibility_date)
    except ValueError:
        parser.error("compatibility-date must be YYYY-MM-DD")
    project = args.project.expanduser().resolve()
    dockerfile = (project / args.dockerfile).resolve()
    output = project / "deploy" / "cloudflare"
    if not project.is_dir() or not dockerfile.is_file() or not dockerfile.is_relative_to(project):
        parser.error("project must exist and dockerfile must be a file inside that project")
    if output.exists() or output.is_symlink():
        parser.error(f"refusing to overwrite {output}")
    if not output.parent.resolve().is_relative_to(project):
        parser.error("deployment parent must not resolve outside the project")

    settings = {
        "revision": "initial-v1", "port": args.port,
        "healthPath": args.health_path, "instance": args.instance,
        "idleMs": args.idle_seconds * 1000,
        "envNames": list(dict.fromkeys(["PUBLIC_BASE_URL", *args.env])),
    }
    template = Path(__file__).resolve().parent.parent / "assets" / "worker.js.tmpl"
    worker = template.read_text().replace("__SETTINGS__", json.dumps(settings, indent=2))
    config = {
        "$schema": "./node_modules/wrangler/config-schema.json",
        "name": args.name, "account_id": args.account_id,
        "main": "worker.js", "compatibility_date": args.compatibility_date,
        "workers_dev": True, "preview_urls": False,
        "containers": [{"class_name": "AgentRuntime", "scheduling_policy": "durable_object",
                        "images": {"agent": {"dockerfile": os.path.relpath(dockerfile, output)}}}],
        "durable_objects": {"bindings": [{"name": "AGENT", "class_name": "AgentRuntime"}]},
        "exports": {"AgentRuntime": {"type": "durable-object", "storage": "sqlite"}},
        "vars": {"PUBLIC_BASE_URL": "", "PUBLIC_GATEWAY_READY": "false"},
    }
    if args.r2_bucket:
        config["r2_buckets"] = [{"binding": "JOURNAL", "bucket_name": args.r2_bucket}]
    package = {
        "name": args.name + "-deployment", "private": True, "type": "module",
        "scripts": {"dev": "wrangler dev", "check": "wrangler deploy --dry-run", "deploy": "wrangler deploy"},
        "devDependencies": {"wrangler": args.wrangler_version},
    }
    files = {
        "worker.js": worker,
        "wrangler.jsonc": json.dumps(config, indent=2) + "\n",
        "package.json": json.dumps(package, indent=2) + "\n",
        ".gitignore": "node_modules/\n.wrangler/\n.bundle/\n.dev.vars*\n.env*\n.secrets*\n",
    }
    output.mkdir(parents=True, exist_ok=False)
    for name, value in files.items():
        with (output / name).open("x") as target:
            target.write(value)
    print(f"Created {output}")
    print("No resources created, secrets copied, dependencies installed, or deployment performed.")
    print("Implement and verify gateway auth; set PUBLIC_BASE_URL and PUBLIC_GATEWAY_READY before use.")


if __name__ == "__main__":
    main()
