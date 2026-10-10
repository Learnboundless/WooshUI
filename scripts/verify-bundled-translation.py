"""Verify bundled translation from an empty model root, with networking disabled."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import socket
from pathlib import Path
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument(
        "--backend-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    archive = args.archive.resolve()
    output = args.data_root.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "models").exists() and any((output / "models").iterdir()):
        raise SystemExit(
            "Use a fresh data directory so verification cannot reuse previously installed models"
        )
    os.environ.update(
        {
            "WOOSH_STUDIO_OFFLINE": "1",
            "WOOSH_STUDIO_TRANSLATION_BUNDLE": str(archive),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
    )
    os.environ.pop("WOOSH_STUDIO_OFFLINE_MODELS", None)
    sys.path.insert(0, str(args.backend_root.resolve()))
    from fastapi.testclient import TestClient
    from woosh_studio.config import StudioPaths
    from woosh_studio.main import create_app
    from woosh_studio.translation_bundle import MODEL_ID, verify_directory

    attempts = []
    original_connect = socket.socket.connect

    def no_network(sock, address):
        # Windows asyncio implements socketpair through loopback. Only permit that
        # local IPC; a model request to any external host must fail this check.
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(sock, address)
        attempts.append(str(address))
        raise AssertionError("Verification forbids external network access")

    examples = [
        ("Chinese", "English", "欢迎来到我们的城市。"),
        ("English", "Chinese", "Welcome to our city."),
        ("Chinese", "Japanese", "欢迎来到我们的城市。"),
        ("Chinese", "Korean", "欢迎来到我们的城市。"),
        ("Chinese", "German", "欢迎来到我们的城市。"),
        ("Chinese", "French", "欢迎来到我们的城市。"),
        ("Chinese", "Russian", "欢迎来到我们的城市。"),
        ("Chinese", "Portuguese", "欢迎来到我们的城市。"),
        ("Chinese", "Spanish", "欢迎来到我们的城市。"),
        ("Chinese", "Italian", "欢迎来到我们的城市。"),
    ]
    results = []
    with patch("socket.socket.connect", no_network):
        with TestClient(create_app(StudioPaths(output))) as client:
            manifest = verify_directory(output / "models" / MODEL_ID)
            catalog = client.get("/api/v1/models").json()
            descriptor = next(model for model in catalog if model["id"] == MODEL_ID)
            assert descriptor["installed"] and descriptor["bundled"]
            assert not client.get("/api/v1/jobs").json(), (
                "Unexpected model download job"
            )
            for source, target, text in examples:
                response = client.post(
                    "/api/v1/translate",
                    json={
                        "text": text,
                        "source_language": source,
                        "target_language": target,
                    },
                )
                assert response.status_code == 200, response.text
                result = response.json()["translation"]
                assert result["model_id"] == MODEL_ID
                assert result["text"].strip() and result["text"] != text
                if target == "Chinese":
                    assert re.search(r"[\u4e00-\u9fff]", result["text"])
                if target == "Japanese":
                    assert re.search(r"[\u3040-\u30ff]", result["text"])
                if target == "Korean":
                    assert re.search(r"[\uac00-\ud7af]", result["text"])
                if target == "Russian":
                    assert re.search(r"[\u0400-\u04ff]", result["text"])
                results.append(result)
                print(f"{source} -> {target}: {result['text']}", flush=True)
        # Restart verification confirms the retained archive and cache work offline.
        stamp = (output / "models" / MODEL_ID / "model.bin").stat().st_mtime_ns
        with TestClient(create_app(StudioPaths(output))) as client:
            assert client.get("/api/v1/health").status_code == 200
            assert (
                stamp == (output / "models" / MODEL_ID / "model.bin").stat().st_mtime_ns
            )
    assert not attempts, attempts
    report = {
        "backend_root": str(args.backend_root.resolve()),
        "archive": str(archive),
        "network_attempts": 0,
        "fresh_install": True,
        "restart_reused_model": True,
        "installed_bytes": sum(item["size_bytes"] for item in manifest["files"]),
        "translations": results,
    }
    (output / "verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        "PASS: fresh offline deployment and ten language directions, without download jobs",
        flush=True,
    )


if __name__ == "__main__":
    main()
