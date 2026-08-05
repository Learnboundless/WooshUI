from pathlib import Path

from woosh_studio.config import StudioPaths


def test_model_home_uses_shared_environment_directory(
    tmp_path: Path, monkeypatch
) -> None:
    shared = tmp_path / "shared-models"
    monkeypatch.setenv("WOOSH_MODEL_HOME", str(shared))
    monkeypatch.setenv("WOOSH_STUDIO_HOME", str(tmp_path / "app"))

    paths = StudioPaths.from_environment().ensure()

    assert paths.models == shared.resolve()
    assert paths.downloads == shared.resolve() / ".downloads"
