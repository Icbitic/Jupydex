from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from typing import Any


DEFAULT_PROFILE = "default"


@dataclass
class Profile:
    base_url: str
    token: str
    workspace: str
    workspace_input: str
    mirror_path: str | None = None


@dataclass
class ConnectParams:
    url: str
    workspace: str
    profile: str = DEFAULT_PROFILE
    token: str | None = None
    mirror: str | None = None


def config_path() -> Path:
    explicit = os.environ.get("JUPYDEX_CONFIG")
    if explicit:
        return Path(explicit).expanduser()

    xdg = os.environ.get("XDG_CONFIG_HOME")
    root = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return root / "jupydex" / "config.json"


def load_connect_params(path: str | Path) -> ConnectParams:
    config_file = Path(path).expanduser()
    with config_file.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid params file: {config_file}")

    missing = [key for key in ("url", "workspace") if not data.get(key)]
    if missing:
        raise ValueError(f"Missing required params in {config_file}: {', '.join(missing)}")

    return ConnectParams(
        url=str(data["url"]),
        workspace=str(data["workspace"]),
        profile=str(data.get("profile") or DEFAULT_PROFILE),
        token=str(data["token"]) if data.get("token") else None,
        mirror=str(data["mirror"]) if data.get("mirror") else None,
    )


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

    def get_profile(self, name: str = DEFAULT_PROFILE) -> Profile:
        data = self.load_all()
        raw = data.get("profiles", {}).get(name)
        if not raw:
            raise KeyError(
                f"No Jupydex profile named {name!r}. Run `jupydex connect` first."
            )
        raw.setdefault("mirror_path", None)
        return Profile(**raw)

    def list_profiles(self) -> dict[str, Profile]:
        data = self.load_all()
        return {
            name: Profile(**{**raw, "mirror_path": raw.get("mirror_path")})
            for name, raw in data.get("profiles", {}).items()
        }
