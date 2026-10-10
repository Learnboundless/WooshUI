"""UTF-8 JSON-lines RPC; library output never shares the protocol stream."""
from __future__ import annotations

import gc
import json
import sys
from contextlib import redirect_stdout
from typing import Any, Callable

_output = sys.stdout
_request_id: str | None = None
_context: dict[str, str] = {}


def emit(event: str, **payload: Any) -> None:
    record = {"event": event, **_context, **payload}
    if _request_id is not None:
        record["request_id"] = _request_id
    print(json.dumps(record, ensure_ascii=False), file=_output, flush=True)


def progress(stage: str, value: float, message: str = "") -> None:
    emit("progress", stage=stage, progress=max(0.0, min(1.0, value)), message=message)


def release_memory() -> None:
    gc.collect()
    torch = sys.modules.get("torch")
    if torch is not None and torch.cuda.is_available():
        torch.cuda.empty_cache()


def serve(commands: dict[str, Callable], unload: Callable) -> None:
    global _request_id, _output, _context
    _output = sys.stdout
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="strict")
    for raw in sys.stdin:
        if not raw.strip():
            continue
        _request_id = None
        _context = {}
        try:
            payload = json.loads(raw)
            _request_id = payload.pop("request_id", None)
            _context = {key: payload[key] for key in ("job_id", "item_id") if key in payload}
            command = payload.pop("command")
            with redirect_stdout(sys.stderr):
                if command == "shutdown":
                    unload()
                    result = {"closed": True}
                elif command == "unload":
                    unload()
                    result = {"unloaded": True}
                elif command == "ping":
                    result = {"ready": True}
                elif command in commands:
                    result = commands[command](payload)
                else:
                    raise ValueError(f"未知工作命令: {command}")
            emit("result", result=result)
            if command == "shutdown":
                return
        except Exception as error:
            with redirect_stdout(sys.stderr):
                unload()
            emit("error", message=str(error), detail=type(error).__name__)
            # A legacy one-shot caller relies on the process exit code.
            if _request_id is None:
                raise SystemExit(1) from error
