import os
import subprocess
import sys
import json
import pytest


@pytest.mark.parametrize(
    "worker,flag",
    [
        ("music_worker", "WOOSH_MUSIC_WORKER_FAKE"),
        ("speech_worker", "WOOSH_SPEECH_WORKER_FAKE"),
    ],
)
def test_workers_roundtrip_unicode_under_legacy_windows_stdio(tmp_path, worker, flag):
    path = tmp_path / "测试项目_日本語" / "对白.wav"
    payload = {
        "command": "generate",
        "output_path": str(path),
        "text": "你好，幸存者。",
        "duration_seconds": 1,
        "seed": 42,
    }
    env = {**os.environ, flag: "1", "PYTHONIOENCODING": "gbk", "PYTHONUTF8": "0"}
    result = subprocess.run(
        [sys.executable, "-m", f"woosh_studio.{worker}"],
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        env=env,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert path.is_file(), result.stdout
    events = [
        json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")
    ]
    assert events[-1]["result"]["path"] == str(path)
