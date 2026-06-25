from pathlib import Path

from jupydex.config import MirrorConfig, Profile
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


def test_default_mirror_path_is_user_level(tmp_path):
    assert default_mirror_path("x", root=tmp_path) == tmp_path / "x"


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


def test_mirror_status_ignores_global_policy(tmp_path):
    prof = profile(tmp_path)
    (tmp_path / "keep.py").write_text("print('ok')", encoding="utf-8")
    (tmp_path / ".DS_Store").write_text("ignored", encoding="utf-8")
    (tmp_path / "._keep.py").write_text("ignored", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "ignored.py").write_text("ignored", encoding="utf-8")
    (tmp_path / "weights.safetensors").write_text("ignored", encoding="utf-8")
    (tmp_path / "large.txt").write_bytes(b"")
    with (tmp_path / "large.txt").open("ab") as f:
        f.truncate(5 * 1024 * 1024)

    dirty = mirror_status(
        "default",
        prof,
        mirror_config=MirrorConfig(max_file_size_mb=5.0),
    )

    assert dirty["added"] == ["keep.py"]


def test_mirror_status_does_not_report_tracked_large_file_as_deleted(tmp_path):
    prof = profile(tmp_path)
    large = tmp_path / "large.txt"
    large.write_bytes(b"")
    with large.open("ab") as f:
        f.truncate(5 * 1024 * 1024)
    save_metadata(
        tmp_path,
        {
            "version": 1,
            "files": {
                "large.txt": {
                    "local_sha256": "old",
                    "remote": {"type": "file", "size": 1},
                },
            },
        },
    )

    dirty = mirror_status(
        "default",
        prof,
        mirror_config=MirrorConfig(max_file_size_mb=5.0),
    )

    assert dirty == {"added": [], "modified": [], "deleted": []}


def test_metadata_file_is_visible(tmp_path):
    assert METADATA_FILE == "jupydex-mirror-state.json"
    assert metadata_path(tmp_path) == tmp_path / "jupydex-mirror-state.json"
