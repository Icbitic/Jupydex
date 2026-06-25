from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
from typing import Any


DEFAULT_PROFILE = "default"
DEFAULT_MIRROR_MAX_FILE_SIZE_MB = 5.0
DEFAULT_MIRROR_IGNORE_DIRS = [
    ".cache",
    ".env",
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "env",
    "node_modules",
    "venv",
]
DEFAULT_MIRROR_IGNORE_GLOBS = [
    ".DS_Store",
    "._*",
    "Desktop.ini",
    "Thumbs.db",
    "*.bin",
    "*.ckpt",
    "*.gguf",
    "*.h5",
    "*.hdf5",
    "*.joblib",
    "*.model",
    "*.onnx",
    "*.pkl",
    "*.pt",
    "*.pth",
    "*.safetensors",
    "*.tflite",
]


@dataclass
class Profile:
    base_url: str
    token: str
    workspace: str
    workspace_input: str
    mirror_path: str | None = None


@dataclass
class MirrorConfig:
    max_file_size_mb: float | None = DEFAULT_MIRROR_MAX_FILE_SIZE_MB
    ignore_dirs: list[str] = field(default_factory=lambda: list(DEFAULT_MIRROR_IGNORE_DIRS))
    ignore_globs: list[str] = field(default_factory=lambda: list(DEFAULT_MIRROR_IGNORE_GLOBS))

    @property
    def max_file_size_bytes(self) -> int | None:
        if self.max_file_size_mb is None:
            return None
        return int(self.max_file_size_mb * 1024 * 1024)


def config_path() -> Path:
    explicit = os.environ.get("JUPYDEX_CONFIG")
    if explicit:
        return Path(explicit).expanduser()

    xdg = os.environ.get("XDG_CONFIG_HOME")
    root = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return root / "jupydex" / "config.json"


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_path()

    def load_all(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"profiles": {}}

        with self.path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError(f"Invalid config file: {self.path}")

        data.setdefault("profiles", {})
        return data

    def save_all(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        tmp.replace(self.path)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def save_profile(self, name: str, profile: Profile) -> None:
        data = self.load_all()
        data["profiles"][name] = asdict(profile)
        self.save_all(data)

    def mirror_config(self) -> MirrorConfig:
        raw = self.load_all().get("mirror", {})
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid mirror config in {self.path}")

        max_file_size_mb = raw.get("max_file_size_mb", DEFAULT_MIRROR_MAX_FILE_SIZE_MB)
        if max_file_size_mb is not None:
            max_file_size_mb = float(max_file_size_mb)

        return MirrorConfig(
            max_file_size_mb=max_file_size_mb,
            ignore_dirs=list_config(raw, "ignore_dirs", DEFAULT_MIRROR_IGNORE_DIRS),
            ignore_globs=list_config(raw, "ignore_globs", DEFAULT_MIRROR_IGNORE_GLOBS),
        )

    def save_mirror_config(self, mirror_config: MirrorConfig) -> None:
        data = self.load_all()
        data["mirror"] = asdict(mirror_config)
        self.save_all(data)

    def remove_profile(self, name: str) -> str | None:
        data = self.load_all()
        profiles = data.get("profiles", {})
        if name not in profiles:
            raise KeyError(
                f"No jdx profile named {name!r}. Run `jdx profile` to see available profiles."
            )

        profiles.pop(name)
        default = data.get("default_profile")
        if default == name or default not in profiles:
            if profiles:
                data["default_profile"] = sorted(profiles)[0]
            else:
                data.pop("default_profile", None)

        self.save_all(data)
        return data.get("default_profile")

    def default_profile_name(self) -> str:
        data = self.load_all()
        value = data.get("default_profile")
        return str(value) if value else DEFAULT_PROFILE

    def set_default_profile(self, name: str) -> None:
        data = self.load_all()
        if name not in data.get("profiles", {}):
            raise KeyError(
                f"No jdx profile named {name!r}. Run `jdx profile` to see available profiles."
            )
        data["default_profile"] = name
        self.save_all(data)

    def get_profile(self, name: str = DEFAULT_PROFILE) -> Profile:
        data = self.load_all()
        raw = data.get("profiles", {}).get(name)
        if not raw:
            raise KeyError(
                f"No jdx profile named {name!r}. Run `jdx connect` first."
            )
        raw.setdefault("mirror_path", None)
        return Profile(**raw)

    def list_profiles(self) -> dict[str, Profile]:
        data = self.load_all()
        return {
            name: Profile(**{**raw, "mirror_path": raw.get("mirror_path")})
            for name, raw in data.get("profiles", {}).items()
        }


class ProfileManager:
    def __init__(self, store: ConfigStore | None = None) -> None:
        self.store = store or ConfigStore()

    def default_name(self) -> str:
        return self.store.default_profile_name()

    def get(self, name: str) -> Profile:
        return self.store.get_profile(name)

    def save(self, name: str, profile: Profile) -> None:
        self.store.save_profile(name, profile)

    def remove(self, name: str) -> str | None:
        return self.store.remove_profile(name)

    def set_default(self, name: str) -> None:
        self.store.set_default_profile(name)

    def list(self) -> dict[str, Profile]:
        return self.store.list_profiles()

    def mirror_config(self) -> MirrorConfig:
        return self.store.mirror_config()

    def save_mirror_config(self, mirror_config: MirrorConfig) -> None:
        self.store.save_mirror_config(mirror_config)


def list_config(raw: dict[str, Any], key: str, default: list[str]) -> list[str]:
    values = raw.get(key)
    if values is None:
        return list(default)
    if not isinstance(values, list):
        raise ValueError(f"Mirror config {key!r} must be a list")
    merged = list(default)
    for value in values:
        text = str(value)
        if text not in merged:
            merged.append(text)
    return merged
