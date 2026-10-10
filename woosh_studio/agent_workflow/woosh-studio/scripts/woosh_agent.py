#!/usr/bin/env python3
"""Small standard-library client for a running local Woosh Studio instance."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


def call(base: str, token: str, method: str, route: str, payload=None):
    address = urlparse(base)
    if (
        address.scheme != "http"
        or address.hostname not in {"localhost", "127.0.0.1", "::1"}
        or address.username
        or address.password
        or address.path not in {"", "/"}
        or address.query
        or address.fragment
    ):
        raise ValueError(
            "API URL must be a local http:// loopback origin without credentials or a path"
        )
    if not route.startswith("/") or route.startswith("//") or ".." in route.split("/"):
        raise ValueError("API route must start with / and remain inside /api/v1")
    headers = {"Accept": "application/json"}
    if token:
        headers["X-Woosh-Token"] = token
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(
        base.rstrip("/") + "/api/v1" + route, data=body, headers=headers, method=method
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.load(response)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code}: {detail}") from error
    except URLError as error:
        raise RuntimeError(
            f"Cannot connect to local Woosh Studio: {error.reason}"
        ) from error


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url", default=os.environ.get("WOOSH_STUDIO_API_URL", "http://127.0.0.1:8765")
    )
    parser.add_argument(
        "--token-env",
        default="WOOSH_STUDIO_API_TOKEN",
        help="Environment variable containing this session's token",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Read device capabilities and installed models")
    preview = commands.add_parser(
        "preview",
        help="Validate a script/voice JSON using the app's parser; does not save",
    )
    preview.add_argument("file", type=Path)
    request = commands.add_parser(
        "request", help="Call an API route relative to /api/v1"
    )
    request.add_argument("method", choices=["GET", "POST", "PUT", "PATCH", "DELETE"])
    request.add_argument("route")
    request.add_argument("--json", type=Path, dest="json_file")
    wait = commands.add_parser(
        "wait", help="Wait for a generation/export/download job to finish"
    )
    wait.add_argument("job_id")
    wait.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args(argv)
    token = os.environ.get(args.token_env, "")
    try:

        def invoke(method, route, data=None):
            return call(args.url, token, method, route, data)

        if args.command == "status":
            result = {
                "capabilities": invoke("GET", "/system/capabilities"),
                "models": invoke("GET", "/models"),
            }
        elif args.command == "preview":
            result = invoke(
                "POST",
                "/scripts/preview",
                {"text": args.file.read_text(encoding="utf-8-sig")},
            )
        elif args.command == "request":
            payload = (
                json.loads(args.json_file.read_text(encoding="utf-8-sig"))
                if args.json_file
                else None
            )
            result = invoke(args.method, args.route, payload)
        else:
            deadline = time.monotonic() + args.timeout
            while True:
                result = invoke("GET", "/jobs/" + quote(args.job_id, safe=""))
                if result["status"] in {
                    "completed",
                    "failed",
                    "cancelled",
                    "interrupted",
                }:
                    break
                if time.monotonic() >= deadline:
                    print(
                        json.dumps(
                            {"timeout": True, "job": result},
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                    return 2
                time.sleep(1)
            if result["status"] != "completed":
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
