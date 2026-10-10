from threading import Event, Thread
from types import SimpleNamespace

import pytest

from woosh_studio.jobs import JobCancelled, JobControl
from woosh_studio.model_runtime import ModelRuntimeManager
from woosh_studio.schemas import RuntimeSettings


def payload(root, number=0, **changes):
    return {"command": "generate", "model_path": str(root / "tts"), "output_path": str(root / f"line-{number}.wav"), "text": "测试配音", "device": "cpu", **changes}


def test_persistent_worker_reuses_model_across_languages_and_reloads_on_file_change(tmp_path, monkeypatch):
    monkeypatch.setenv("WOOSH_SPEECH_WORKER_FAKE", "1")
    (tmp_path / "tts").mkdir()
    config = tmp_path / "tts" / "config.json"
    config.write_text("{}")
    runtime = ModelRuntimeManager(tmp_path)
    try:
        runtime.run("woosh_studio.speech_worker", payload(tmp_path, language="Chinese"), JobControl(), lambda event: None)
        first = runtime.status()
        runtime.run("woosh_studio.speech_worker", payload(tmp_path, 1, language="Japanese"), JobControl(), lambda event: None)
        assert runtime.status()["pid"] == first["pid"]
        assert runtime.status()["load_count"] == 1
        assert runtime.status()["cache_hits"] == 1
        config.write_text('{"changed":true}')
        runtime.run("woosh_studio.speech_worker", payload(tmp_path, 2), JobControl(), lambda event: None)
        assert runtime.status()["load_count"] == 2
        runtime.release()
        assert runtime.status()["state"] == "unloaded"
    finally:
        worker = runtime._worker
        runtime.close()
        if worker:
            assert worker.process.poll() is not None


def test_cancel_running_worker_reaps_process_and_next_request_recovers(tmp_path, monkeypatch):
    monkeypatch.setenv("WOOSH_SPEECH_WORKER_FAKE", "1")
    runtime = ModelRuntimeManager(tmp_path)
    control = JobControl()
    try:
        def cancel(event):
            control.cancelled.set()
        with pytest.raises(JobCancelled):
            runtime.run("woosh_studio.speech_worker", payload(tmp_path), control, cancel)
        assert runtime._worker is None
        runtime.run("woosh_studio.speech_worker", payload(tmp_path, 1), JobControl(), lambda event: None)
        assert (tmp_path / "line-1.wav").is_file()
    finally:
        runtime.close()


def test_waiting_lease_can_be_cancelled_without_interrupting_current_model(tmp_path):
    runtime = ModelRuntimeManager(tmp_path)
    entered, release = Event(), Event()
    def owner():
        with runtime.sequence(JobControl()):
            entered.set()
            release.wait(5)
    thread = Thread(target=owner)
    thread.start()
    assert entered.wait(2)
    control = JobControl()
    control.cancelled.set()
    try:
        with pytest.raises(JobCancelled):
            with runtime.sequence(control):
                pytest.fail("cancelled waiter acquired the model")
        with pytest.raises(RuntimeError, match="正在使用"):
            runtime.release()
    finally:
        release.set()
        thread.join(3)
        runtime.close()


def test_release_policy_keeps_model_for_entire_batch(tmp_path, monkeypatch):
    monkeypatch.setenv("WOOSH_SPEECH_WORKER_FAKE", "1")
    runtime = ModelRuntimeManager(tmp_path, lambda: RuntimeSettings(model_residency="release"))
    try:
        with runtime.sequence(JobControl()):
            for number in range(2):
                runtime.run("woosh_studio.speech_worker", payload(tmp_path, number), JobControl(), lambda event: None)
            assert runtime.status()["load_count"] == 1
        assert runtime.status()["state"] == "unloaded"
    finally:
        runtime.close()


def test_real_qwen_adapter_loads_once_and_reuses_reference_prompt(tmp_path, monkeypatch):
    import sys
    import numpy as np
    from woosh_studio import speech_worker as worker
    monkeypatch.delenv("WOOSH_SPEECH_WORKER_FAKE", raising=False)
    worker.unload()
    loads, encodings, spoken = [], [], []
    class Model:
        @classmethod
        def from_pretrained(cls, *args, **kwargs):
            loads.append(args)
            return cls()
        def create_voice_clone_prompt(self, **kwargs):
            encodings.append(kwargs)
            return ["encoded-reference"]
        def generate_voice_clone(self, **kwargs):
            spoken.append(kwargs)
            return [np.ones(1000, dtype="float32") * 0.1], 24000
    monkeypatch.setitem(sys.modules, "qwen_tts", SimpleNamespace(Qwen3TTSModel=Model))
    reference = tmp_path / "ref.wav"
    import soundfile as sf
    sf.write(reference,np.ones(2400,dtype="float32")*0.1,24000)
    try:
        for number, language in enumerate(("Chinese", "English", "Japanese")):
            worker.generate(payload(tmp_path, number, language=language, mode="clone", reference_audio=str(reference), reference_text="reference words"))
        assert len(loads) == 1
        assert len(encodings) == 1
        assert [item["language"] for item in spoken] == ["Chinese", "English", "Japanese"]
        sf.write(reference,np.ones(2400,dtype="float32")*0.2,24000)
        worker.generate(payload(tmp_path, 3, mode="clone", reference_audio=str(reference), reference_text="reference words"))
        assert len(encodings) == 2
        assert len(loads) == 1
    finally:
        worker.unload()
