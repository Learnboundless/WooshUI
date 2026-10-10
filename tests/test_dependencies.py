import tomllib
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_music_environment_is_pinned_to_one_python_312_lock() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["requires-python"] == ">=3.12,<3.13"
    # Qwen3-TTS 0.1.1 requires the same 4.57.3 pin used by the shared runtime.
    assert "qwen-tts==0.1.1" in project["dependency-groups"]["speech"]
    assert "transformers==4.57.3" in project["project"]["dependencies"]
    assert project["tool"]["uv"]["override-dependencies"] == ["transformers==4.57.3"]
    assert project["tool"]["uv"]["sources"]["heartlib"]["rev"] == (
        "3783bdb8441f2c298b1e64c8651173aac200361c"
    )
    assert {
        "demucs==4.1.0",
        "mmgp==3.7.10",
        "numpy==2.0.2",
        "tokenizers==0.22.1",
        "torchao==0.9.0",
        "torchtune==0.4.0",
    }.issubset(project["dependency-groups"]["music"])


def test_lock_contains_compatible_heartlib_and_transformers() -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    packages = {package["name"]: package for package in lock["package"]}
    assert packages["transformers"]["version"] == "4.57.3"
    assert packages["heartlib"]["source"]["git"].endswith(
        "3783bdb8441f2c298b1e64c8651173aac200361c"
    )
