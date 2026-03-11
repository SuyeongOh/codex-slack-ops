#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT_SECONDS = 1800
DEFAULT_POLL_INTERVAL_SECONDS = 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a Slack approval request, wait, then run the command.")
    parser.add_argument("--base-url", default=os.environ.get("APPROVAL_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--internal-token", default=os.environ.get("INTERNAL_API_TOKEN"))
    parser.add_argument("--title", required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--rationale", required=True)
    parser.add_argument("--risk-level", default="medium", choices=["low", "medium", "high"])
    parser.add_argument("--requested-by", default=os.environ.get("USER", "codex-runner"))
    parser.add_argument("--channel-id", default=os.environ.get("SLACK_DEFAULT_CHANNEL_ID"))
    parser.add_argument("--workdir", default=os.getcwd())
    parser.add_argument("--shell-executable", default="/bin/bash")
    parser.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL_SECONDS)
    parser.add_argument("--approval-timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--context",
        action="append",
        default=[],
        help="Extra context in KEY=VALUE format. Can be passed multiple times.",
    )
    return parser.parse_args()


def parse_context(items: List[str], workdir: str) -> Dict[str, str]:
    context = {
        "cwd": workdir,
        "host": socket.gethostname(),
    }
    for item in items:
        if "=" not in item:
            raise ValueError(f"invalid context item: {item}")
        key, value = item.split("=", 1)
        context[key] = value
    return context


def emit(text: str, *, stderr: bool = False) -> None:
    stream = sys.stderr if stderr else sys.stdout
    print(text, file=stream, flush=True)


def request_json(method: str, url: str, *, token: str, payload: Optional[dict] = None) -> dict:
    body = None
    headers = {"X-Internal-Token": token}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            content = response.read().decode("utf-8")
            return json.loads(content) if content else {}
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with HTTP {exc.code}: {error_body}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc}") from exc


def create_approval(args: argparse.Namespace, context: Dict[str, str]) -> dict:
    payload = {
        "title": args.title,
        "command": args.command,
        "rationale": args.rationale,
        "risk_level": args.risk_level,
        "requested_by": args.requested_by,
        "channel_id": args.channel_id,
        "context": context,
    }
    return request_json("POST", f"{args.base_url}/api/v1/approvals", token=args.internal_token, payload=payload)


def wait_for_decision(args: argparse.Namespace, approval_id: str) -> dict:
    deadline = time.time() + args.approval_timeout
    while time.time() < deadline:
        approval = request_json(
            "GET",
            f"{args.base_url}/api/v1/approvals/{approval_id}",
            token=args.internal_token,
        )
        status = approval["status"]
        if status in {"approved", "rejected", "expired", "failed", "completed"}:
            return approval
        time.sleep(args.poll_interval)
    raise TimeoutError(f"approval {approval_id} was not decided within {args.approval_timeout} seconds")


def report_execution(args: argparse.Namespace, approval_id: str, status: str, result_summary: Optional[str]) -> dict:
    payload = {"status": status, "result_summary": result_summary}
    return request_json(
        "POST",
        f"{args.base_url}/api/v1/approvals/{approval_id}/execution",
        token=args.internal_token,
        payload=payload,
    )


def run_command(command: str, *, workdir: str, shell_executable: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        shell=True,
        executable=shell_executable,
        cwd=workdir,
        capture_output=True,
        text=True,
    )


def summarize_result(result: subprocess.CompletedProcess) -> str:
    parts = [f"exit_code={result.returncode}"]
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    if stdout:
        parts.append("stdout:\n" + truncate(stdout, 1200))
    if stderr:
        parts.append("stderr:\n" + truncate(stderr, 1200))
    return "\n\n".join(parts)


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def main() -> int:
    args = parse_args()
    if not args.internal_token:
        emit("INTERNAL_API_TOKEN is required. Pass --internal-token or export the env var.", stderr=True)
        return 2

    workdir = str(Path(args.workdir).expanduser().resolve())
    try:
        context = parse_context(args.context, workdir)
        approval = create_approval(args, context)
        approval_id = approval["id"]
        emit(f"approval created: {approval_id}")
        if approval.get("slack_channel_id") and approval.get("slack_message_ts"):
            emit(
                "approval message: "
                f"channel={approval['slack_channel_id']} "
                f"ts={approval['slack_message_ts']}"
            )
        emit("waiting for approval...")

        decision = wait_for_decision(args, approval_id)
        status = decision["status"]
        emit(f"approval status: {status}")

        if status == "rejected":
            return 3
        if status == "expired":
            return 4
        if status != "approved":
            emit(f"unexpected terminal status before execution: {status}", stderr=True)
            return 5

        execution_update = report_execution(args, approval_id, "executing", None)
        emit(f"execution status: {execution_update['status']}")
        result = run_command(args.command, workdir=workdir, shell_executable=args.shell_executable)
        summary = summarize_result(result)
        final_status = "completed" if result.returncode == 0 else "failed"
        final_update = report_execution(args, approval_id, final_status, summary)
        emit(f"execution status: {final_update['status']}")
        emit(f"execution exit_code: {result.returncode}")

        if result.stdout:
            sys.stdout.write(result.stdout)
            sys.stdout.flush()
        if result.stderr:
            sys.stderr.write(result.stderr)
            sys.stderr.flush()
        if not result.stdout and not result.stderr:
            emit(f"execution summary: {summary}")
        return result.returncode
    except TimeoutError as exc:
        emit(str(exc), stderr=True)
        return 6
    except Exception as exc:
        emit(f"runner failed: {exc}", stderr=True)
        return 7


if __name__ == "__main__":
    raise SystemExit(main())
