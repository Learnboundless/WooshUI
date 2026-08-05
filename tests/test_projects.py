from pathlib import Path

import pytest

from woosh_studio.config import StudioPaths
from woosh_studio.projects import MANIFEST_NAME, ProjectService
from woosh_studio.schemas import ProjectManifestV1
from woosh_studio.storage import LibraryDatabase


@pytest.fixture
def project_service(tmp_path: Path) -> ProjectService:
    paths = StudioPaths(tmp_path / "app").ensure()
    return ProjectService(LibraryDatabase(paths.database))


def test_project_round_trip_and_recovery(
    tmp_path: Path, project_service: ProjectService
) -> None:
    root, created = project_service.create(tmp_path, "Game: SFX", "prototype")
    assert root.name == "Game- SFX.woosh"
    assert all(
        (root / directory).is_dir()
        for directory in ("Sources", "Generated", "Renders", "Exports", ".cache")
    )
    created.description = "updated"
    saved = project_service.save(root, created)
    assert project_service.open(root).description == "updated"

    (root / MANIFEST_NAME).write_text("not-json", encoding="utf-8")
    recovered = project_service.open(root)
    assert recovered.id == saved.id
    assert recovered.description == "prototype"


def test_resolve_project_file_rejects_traversal(
    tmp_path: Path, project_service: ProjectService
) -> None:
    root, _ = project_service.create(tmp_path, "Safe")
    with pytest.raises(ValueError, match="越界"):
        project_service.resolve_project_file(root, "../outside.wav")


def test_open_migrates_v1_project_with_backup(
    tmp_path: Path, project_service: ProjectService
) -> None:
    root = tmp_path / "Legacy.woosh"
    root.mkdir()
    legacy = ProjectManifestV1(name="Legacy")
    manifest_path = root / MANIFEST_NAME
    manifest_path.write_text(
        legacy.model_dump_json(indent=2),
        encoding="utf-8",
    )

    migrated = project_service.open(root)

    assert migrated.schema_version == 2
    assert (root / f"{MANIFEST_NAME}.bak").is_file()
