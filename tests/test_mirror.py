from pathlib import Path

from jupydex.config import Profile
from jupydex.mirror import (
    METADATA_FILE,
    default_mirror_path,
    metadata_path,
    mirror_path_for_profile,
    mirror_status,
    save_metadata,
)


def profile(tmp_path: Path) -> Profile:
    return Profile(
        base_url="http://example.com",
        token="tok",
        workspace="workspace",
        workspace_input="/remote/workspace",
        mirror_path=str(tmp_path),
    )


def test_default_mirror_path_is_project_local(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert default_mirror_path("x") == tmp_path / "jupydex-mirrors" / "x"


def test_mirror_path_uses_profile_path(tmp_path):
    assert mirror_path_for_profile("default", profile(tmp_path)) == tmp_path


def test_mirror_status_reports_local_changes(tmp_path):
    prof = profile(tmp_path)
    (tmp_path / "a.py").write_text("old", encoding="utf-8")
    save_metadata(
        tmp_path,
        {
            "version": 1,
            "files": {
                "a.py": {
                    "local_sha256": "not-the-current-hash",
                    "remote": {"type": "file", "size": 3},
                },
                "deleted.py": {
                    "local_sha256": "anything",
                    "remote": {"type": "file", "size": 1},
                },
            },
        },
    )

    dirty = mirror_status("default", prof)

    assert dirty["modified"] == ["a.py"]
    assert dirty["deleted"] == ["deleted.py"]


def test_metadata_file_is_visible(tmp_path):
    assert METADATA_FILE == "jupydex-mirror-state.json"
    assert metadata_path(tmp_path) == tmp_path / "jupydex-mirror-state.json"
