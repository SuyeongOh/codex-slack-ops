#!/usr/bin/env python
from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path
from typing import Dict


DEFAULT_ENV = {
    "APP_ENV": "development",
    "APP_HOST": "0.0.0.0",
    "APP_PORT": "8000",
    "BASE_URL": "http://localhost:8000",
    "REDIS_URL": "memory://",
    "SLACK_APP_TOKEN": "",
    "SLACK_SIGNING_SECRET": "REPLACE_WITH_SLACK_SIGNING_SECRET",
    "SLACK_USE_SOCKET_MODE": "false",
    "SLACK_DEFAULT_CHANNEL_ID": "<approval-channel-id>",
    "SLACK_ALLOWED_APPROVER_IDS": "<comma-separated-slack-user-ids>",
    "APPROVAL_TTL_SECONDS": "600",
    "REDIS_LOCK_TTL_SECONDS": "10",
    "EXPIRATION_SWEEP_SECONDS": "15",
}

ENV_ORDER = [
    "APP_ENV",
    "APP_HOST",
    "APP_PORT",
    "BASE_URL",
    "INTERNAL_API_TOKEN",
    "DATABASE_URL",
    "REDIS_URL",
    "SLACK_BOT_TOKEN",
    "SLACK_APP_TOKEN",
    "SLACK_SIGNING_SECRET",
    "SLACK_USE_SOCKET_MODE",
    "SLACK_TEAM_ID",
    "SLACK_ALLOWED_APPROVER_IDS",
    "SLACK_DEFAULT_CHANNEL_ID",
    "APPROVAL_TTL_SECONDS",
    "REDIS_LOCK_TTL_SECONDS",
    "EXPIRATION_SWEEP_SECONDS",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap .env from the local Codex Slack MCP config.")
    parser.add_argument(
        "--codex-config",
        default=str(Path.home() / ".codex" / "config.toml"),
        help="Path to the Codex config.toml file.",
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parents[1] / ".env"),
        help="Target .env path.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing .env values instead of preserving them.",
    )
    return parser.parse_args()


def load_existing_env(path: Path) -> Dict[str, str]:
    data: Dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def extract_slack_env(config_path: Path) -> Dict[str, str]:
    if not config_path.exists():
        raise FileNotFoundError(f"Codex config not found: {config_path}")

    section = None
    slack_env: Dict[str, str] = {}
    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section != "mcp_servers.slack.env" or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        slack_env[key] = value

    if "SLACK_BOT_TOKEN" not in slack_env or "SLACK_TEAM_ID" not in slack_env:
        raise RuntimeError("SLACK_BOT_TOKEN or SLACK_TEAM_ID missing in [mcp_servers.slack.env]")
    return slack_env


def default_database_url(output_path: Path) -> str:
    database_path = (output_path.parent / "approvals.db").resolve()
    return f"sqlite+aiosqlite:///{database_path.as_posix()}"


def build_env(existing: Dict[str, str], slack_env: Dict[str, str], *, force: bool, output_path: Path) -> Dict[str, str]:
    values = {} if force else dict(existing)

    for key, value in DEFAULT_ENV.items():
        values.setdefault(key, value)
    values.setdefault("DATABASE_URL", default_database_url(output_path))

    values["SLACK_BOT_TOKEN"] = slack_env["SLACK_BOT_TOKEN"]
    values["SLACK_TEAM_ID"] = slack_env["SLACK_TEAM_ID"]
    values.setdefault("INTERNAL_API_TOKEN", secrets.token_urlsafe(32))
    return values


def write_env(path: Path, values: Dict[str, str]) -> None:
    lines = []
    for key in ENV_ORDER:
        if key in values:
            lines.append(f"{key}={values[key]}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    config_path = Path(args.codex_config).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    try:
        slack_env = extract_slack_env(config_path)
        existing_env = load_existing_env(output_path)
        values = build_env(existing_env, slack_env, force=args.force, output_path=output_path)
        write_env(output_path, values)
    except Exception as exc:
        print(f"bootstrap failed: {exc}", file=sys.stderr)
        return 1

    print(f"wrote {output_path}")
    if values["SLACK_SIGNING_SECRET"] == "REPLACE_WITH_SLACK_SIGNING_SECRET":
        print("next step: set SLACK_SIGNING_SECRET in the generated .env before enabling Slack Interactivity.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
