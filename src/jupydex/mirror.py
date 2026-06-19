from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .client import JupyterClient, workspace_relative_path
from .config import MirrorConfig, Profile


METADATA_FILE = "jupydex-mirror-state.json"


@dataclass
class MirrorSummary:
    pulled: int = 0
    pushed: int = 0
    deleted_remote: int = 0
    skipped: int = 0


class MirrorConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class MirrorPolicy:
    max_file_size_bytes: int | None
    ignore_dirs: tuple[str, ...]
    ignore_globs: tuple[str, ...]

    @classmethod
    def from_config(cls, mirror_config: MirrorConfig | None) -> MirrorPolicy:
        config = mirror_config or MirrorConfig()
        return cls(
            max_file_size_bytes=config.max_file_size_bytes,
            ignore_dirs=tuple(config.ignore_dirs),
            ignore_globs=tuple(config.ignore_globs),
        )

    def ignores_path(self, rel_path: str, *, is_dir: bool = False) -> bool:
        rel = workspace_relative_path(rel_path)
        parts = rel.split("/") if rel else []
        if any(part in self.ignore_dirs for part in parts):
            return True
        if is_dir:
            return False
        name = parts[-1] if parts else rel
        return any(
            fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel, pattern)
            for pattern in self.ignore_globs
        )

    def ignores_size(self, size: int | None) -> bool:
        return (
            self.max_file_size_bytes is not None
            and size is not None
            and size >= self.max_file_size_bytes
        )


def default_mirror_path(profile_name: str, root: Path | None = None) -> Path:
    mirror_root = root or (Path.home() / "jdx-mirrors")
    return (mirror_root / profile_name).resolve()


def mirror_path_for_profile(profile_name: str, profile: Profile) -> Path:
    if profile.mirror_path:
        return Path(profile.mirror_path).expanduser().resolve()
    return default_mirror_path(profile_name)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def metadata_path(mirror_root: Path) -> Path:
    return mirror_root / METADATA_FILE


def load_metadata(mirror_root: Path) -> dict[str, Any]:
    path = metadata_path(mirror_root)
    if not path.exists():
        return {"version": 1, "files": {}}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("version", 1)
    data.setdefault("files", {})
    return data


def save_metadata(mirror_root: Path, metadata: dict[str, Any]) -> None:
    mirror_root.mkdir(parents=True, exist_ok=True)
    path = metadata_path(mirror_root)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def remote_signature(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "last_modified": model.get("last_modified"),
        "size": model.get("size"),
        "type": model.get("type"),
        "hash": model.get("hash"),
        "hash_algorithm": model.get("hash_algorithm"),
    }


def safe_local_path(mirror_root: Path, rel_path: str) -> Path:
    rel = workspace_relative_path(rel_path)
    target = (mirror_root / rel).resolve()
    root = mirror_root.resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"Path escapes mirror root: {rel_path}")
    return target


def iter_remote_files(
    client: JupyterClient,
    workspace: str,
    rel_path: str = ".",
    *,
    policy: MirrorPolicy | None = None,
) -> Iterator[dict[str, Any]]:
    policy = policy or MirrorPolicy.from_config(None)
    for item in client.list_dir(workspace, rel_path):
        typ = item.get("type")
        item_path = str(item.get("path", ""))
        workspace_prefix = workspace.strip("/")
        if item_path == workspace_prefix:
            child_rel = ""
        elif item_path.startswith(workspace_prefix + "/"):
            child_rel = item_path[len(workspace_prefix) + 1 :]
        else:
            child_rel = str(item.get("name", ""))

        if typ == "directory":
            if not policy.ignores_path(child_rel, is_dir=True):
                yield from iter_remote_files(client, workspace, child_rel, policy=policy)
        elif typ == "file":
            if not policy.ignores_path(child_rel):
                yield {**item, "workspace_relative_path": child_rel}


def pull_mirror(
    client: JupyterClient,
    profile_name: str,
    profile: Profile,
    *,
    subpath: str = ".",
    max_size_bytes: int | None = None,
    mirror_config: MirrorConfig | None = None,
    prune: bool = False,
) -> MirrorSummary:
    policy = MirrorPolicy.from_config(mirror_config)
    if max_size_bytes is not None:
        policy = MirrorPolicy(max_size_bytes, policy.ignore_dirs, policy.ignore_globs)
    mirror_root = mirror_path_for_profile(profile_name, profile)
    mirror_root.mkdir(parents=True, exist_ok=True)
    metadata = load_metadata(mirror_root)
    metadata.update(
        {
            "version": 1,
            "profile": profile_name,
            "base_url": profile.base_url,
            "workspace": profile.workspace,
            "mirror_root": str(mirror_root),
            "updated_at": now_iso(),
        }
    )
    files = metadata.setdefault("files", {})

    remote_files = iter_remote_files(client, profile.workspace, subpath, policy=policy)
    seen: set[str] = set()
    summary = MirrorSummary()

    for model in remote_files:
        rel = str(model["workspace_relative_path"])
        seen.add(rel)
        size = model.get("size")
        if policy.ignores_size(size if isinstance(size, int) else None):
            summary.skipped += 1
            continue

        data, fresh_model = client.read_file(profile.workspace, rel)
        local_path = safe_local_path(mirror_root, rel)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)
        files[rel] = {
            "remote": remote_signature(fresh_model),
            "local_sha256": sha256_file(local_path),
            "pulled_at": now_iso(),
        }
        summary.pulled += 1

    if prune:
        for rel, info in list(files.items()):
            if local_file_ignored(mirror_root, rel, policy):
                continue
            if rel in seen:
                continue
            local_path = safe_local_path(mirror_root, rel)
            if local_path.exists() and local_path.is_file():
                current_hash = sha256_file(local_path)
                if current_hash == info.get("local_sha256"):
                    local_path.unlink()
            files.pop(rel, None)

    save_metadata(mirror_root, metadata)
    return summary


def iter_local_files(mirror_root: Path, policy: MirrorPolicy | None = None) -> Iterator[Path]:
    policy = policy or MirrorPolicy.from_config(None)
    if not mirror_root.exists():
        return
    for root, dirs, files in os.walk(mirror_root):
        root_path = Path(root)
        kept_dirs: list[str] = []
        for dirname in dirs:
            rel_dir = relative_to_mirror(mirror_root, root_path / dirname)
            if not policy.ignores_path(rel_dir, is_dir=True):
                kept_dirs.append(dirname)
        dirs[:] = kept_dirs

        for name in files:
            path = root_path / name
            if path.name == METADATA_FILE:
                continue
            rel = relative_to_mirror(mirror_root, path)
            if policy.ignores_path(rel) or policy.ignores_size(path.stat().st_size):
                continue
            yield path


def relative_to_mirror(mirror_root: Path, path: Path) -> str:
    rel = path.resolve().relative_to(mirror_root.resolve())
    return rel.as_posix()


def parent_dir(rel_path: str) -> str:
    parts = rel_path.split("/")
    if len(parts) <= 1:
        return ""
    return "/".join(parts[:-1])


def local_file_ignored(mirror_root: Path, rel_path: str, policy: MirrorPolicy) -> bool:
    if policy.ignores_path(rel_path):
        return True
    local_path = safe_local_path(mirror_root, rel_path)
    return (
        local_path.exists()
        and local_path.is_file()
        and policy.ignores_size(local_path.stat().st_size)
    )


def push_mirror(
    client: JupyterClient,
    profile_name: str,
    profile: Profile,
    *,
    force: bool = False,
    delete: bool = False,
    mirror_config: MirrorConfig | None = None,
) -> MirrorSummary:
    policy = MirrorPolicy.from_config(mirror_config)
    mirror_root = mirror_path_for_profile(profile_name, profile)
    metadata = load_metadata(mirror_root)
    files = metadata.setdefault("files", {})
    summary = MirrorSummary()

    local_files = iter_local_files(mirror_root, policy)
    local_rel_paths = {relative_to_mirror(mirror_root, path): path for path in local_files}

    for rel, local_path in sorted(local_rel_paths.items()):
        current_hash = sha256_file(local_path)
        tracked = files.get(rel)
        if tracked and tracked.get("local_sha256") == current_hash:
            continue

        remote_model = client.contents(
            client.under_workspace(profile.workspace, rel),
            content=False,
            require_ok=False,
        )
        if tracked and not force:
            expected = tracked.get("remote")
            if remote_model is not None and remote_signature(remote_model) != expected:
                raise MirrorConflict(
                    f"Remote changed since last pull: {rel}. Pull first or use --force."
                )

        client.ensure_dir(profile.workspace, parent_dir(rel))
        client.write_file(profile.workspace, rel, local_path.read_bytes())
        fresh_model = client.contents(
            client.under_workspace(profile.workspace, rel),
            content=False,
            require_ok=False,
        )
        files[rel] = {
            "remote": remote_signature(fresh_model or {}),
            "local_sha256": sha256_file(local_path),
            "pushed_at": now_iso(),
        }
        summary.pushed += 1

    if delete:
        for rel, tracked in list(files.items()):
            if local_file_ignored(mirror_root, rel, policy):
                continue
            if rel in local_rel_paths:
                continue
            remote_model = client.contents(
                client.under_workspace(profile.workspace, rel),
                content=False,
                require_ok=False,
            )
            if remote_model is None:
                files.pop(rel, None)
                continue
            if not force and remote_signature(remote_model) != tracked.get("remote"):
                raise MirrorConflict(
                    f"Remote changed since last pull: {rel}. Pull first or use --force."
                )
            client.delete(profile.workspace, rel)
            files.pop(rel, None)
            summary.deleted_remote += 1

    metadata.update(
        {
            "version": 1,
            "profile": profile_name,
            "base_url": profile.base_url,
            "workspace": profile.workspace,
            "mirror_root": str(mirror_root),
            "updated_at": now_iso(),
        }
    )
    save_metadata(mirror_root, metadata)
    return summary


def mirror_status(
    profile_name: str,
    profile: Profile,
    *,
    mirror_config: MirrorConfig | None = None,
) -> dict[str, list[str]]:
    policy = MirrorPolicy.from_config(mirror_config)
    mirror_root = mirror_path_for_profile(profile_name, profile)
    metadata = load_metadata(mirror_root)
    files = metadata.setdefault("files", {})
    local_rel_paths = {
        relative_to_mirror(mirror_root, path): path
        for path in iter_local_files(mirror_root, policy)
    }

    added: list[str] = []
    modified: list[str] = []
    deleted: list[str] = []

    for rel, path in sorted(local_rel_paths.items()):
        tracked = files.get(rel)
        if not tracked:
            added.append(rel)
            continue
        if tracked.get("local_sha256") != sha256_file(path):
            modified.append(rel)

    for rel in sorted(files):
        if local_file_ignored(mirror_root, rel, policy):
            continue
        if rel not in local_rel_paths:
            deleted.append(rel)

    return {"added": added, "modified": modified, "deleted": deleted}
