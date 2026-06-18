from __future__ import annotations

from dataclasses import dataclass
import base64
import posixpath
import urllib.parse

import httpx


@dataclass(frozen=True)
class ServerInfo:
    base_url: str
    token: str


class JupyterError(RuntimeError):
    pass


def parse_jupyter_url(url: str, token: str | None = None) -> ServerInfo:
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("Expected a full Jupyter URL such as http://host:8888/lab?token=...")

    query = urllib.parse.parse_qs(parsed.query)
    resolved_token = token or (query.get("token", [None])[0])
    if not resolved_token:
        raise ValueError("No token found. Pass --token or include ?token=... in the URL.")

    path = parsed.path.rstrip("/")
    for marker in ("/lab", "/tree", "/notebooks", "/edit", "/terminals"):
        idx = path.find(marker)
        if idx >= 0:
            path = path[:idx]
            break

    base_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))
    return ServerInfo(base_url=base_url.rstrip("/"), token=resolved_token)


def workspace_relative_path(path: str) -> str:
    """Normalize a user path so it cannot escape the selected workspace."""
    parts: list[str] = []
    for raw in path.replace("\\", "/").split("/"):
        if raw in ("", "."):
            continue
        if raw == "..":
            if not parts:
                raise ValueError("Path escapes the selected workspace")
            parts.pop()
        else:
            parts.append(raw)
    return "/".join(parts)


class JupyterClient:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.http = httpx.Client(
            headers={"Authorization": f"token {token}"},
            timeout=timeout,
            follow_redirects=True,
        )

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> JupyterClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def api_url(self, path: str) -> str:
        path = path.lstrip("/")
        return f"{self.base_url}/api/{path}"

    def content_url(self, path: str) -> str:
        normalized = path.strip("/")
        quoted = urllib.parse.quote(normalized, safe="/")
        if quoted:
            return self.api_url(f"contents/{quoted}")
        return self.api_url("contents")

    def request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        response = self.http.request(method, self.api_url(path), **kwargs)
        if response.status_code >= 400:
            raise JupyterError(f"{method} /api/{path} failed: {response.status_code} {response.text}")
        return response

    def status(self) -> dict[str, object]:
        return self.request("GET", "status").json()

    def kernelspecs(self) -> dict[str, object]:
        return self.request("GET", "kernelspecs").json()

    def contents(
        self,
        path: str = "",
        *,
        content: bool = True,
        require_ok: bool = True,
    ) -> dict[str, object] | None:
        response = self.http.get(
            self.content_url(path),
            params={"content": "1" if content else "0"},
        )
        if response.status_code == 404 and not require_ok:
            return None
        if response.status_code >= 400:
            raise JupyterError(f"GET contents/{path} failed: {response.status_code} {response.text}")
        return response.json()

    def exists(self, path: str) -> bool:
        return self.contents(path, content=False, require_ok=False) is not None

    def resolve_workspace(self, requested: str) -> str:
        raw = requested.strip()
        if not raw:
            raise ValueError("Workspace cannot be empty")

        direct = raw.strip("/")
        if self.exists(direct):
            model = self.contents(direct, content=False)
            if model and model.get("type") == "directory":
                return direct
            raise ValueError(f"Workspace is not a directory: {requested}")

        if raw.startswith("/"):
            parts = [part for part in raw.split("/") if part]
            for idx in range(1, len(parts)):
                suffix = "/".join(parts[idx:])
                if self.exists(suffix):
                    model = self.contents(suffix, content=False)
                    if model and model.get("type") == "directory":
                        return suffix

        raise ValueError(
            f"Could not find workspace {requested!r} under Jupyter contents root"
        )

    def under_workspace(self, workspace: str, path: str = ".") -> str:
        rel = workspace_relative_path(path)
        workspace = workspace.strip("/")
        return posixpath.join(workspace, rel) if rel else workspace

    def list_dir(self, workspace: str, path: str = ".") -> list[dict[str, object]]:
        model = self.contents(self.under_workspace(workspace, path), content=True)
        if not model:
            return []
        if model.get("type") != "directory":
            raise ValueError(f"Not a directory: {path}")
        content = model.get("content") or []
        if not isinstance(content, list):
            raise ValueError(f"Unexpected directory content model for {path}")
        return content

    def read_file(self, workspace: str, path: str) -> tuple[bytes, dict[str, object]]:
        model = self.contents(self.under_workspace(workspace, path), content=True)
        if not model:
            raise FileNotFoundError(path)
        if model.get("type") != "file":
            raise ValueError(f"Not a file: {path}")

        fmt = model.get("format")
        content = model.get("content")
        if not isinstance(content, str):
            raise ValueError(f"No readable content returned for {path}")

        if fmt == "base64":
            return base64.b64decode(content), model
        return content.encode("utf-8"), model

    def write_file(self, workspace: str, path: str, data: bytes) -> dict[str, object]:
        try:
            text = data.decode("utf-8")
            payload = {"type": "file", "format": "text", "content": text}
        except UnicodeDecodeError:
            payload = {
                "type": "file",
                "format": "base64",
                "content": base64.b64encode(data).decode("ascii"),
            }

        response = self.http.put(
            self.content_url(self.under_workspace(workspace, path)),
            json=payload,
        )
        if response.status_code >= 400:
            raise JupyterError(f"PUT contents/{path} failed: {response.status_code} {response.text}")
        return response.json()

    def mkdir(self, workspace: str, path: str) -> dict[str, object]:
        response = self.http.put(
            self.content_url(self.under_workspace(workspace, path)),
            json={"type": "directory"},
        )
        if response.status_code >= 400:
            raise JupyterError(f"MKDIR contents/{path} failed: {response.status_code} {response.text}")
        return response.json()

    def ensure_dir(self, workspace: str, path: str) -> None:
        path = workspace_relative_path(path)
        if not path:
            return

        parts = path.split("/")
        for idx in range(1, len(parts) + 1):
            current = "/".join(parts[:idx])
            model = self.contents(self.under_workspace(workspace, current), content=False, require_ok=False)
            if model is None:
                self.mkdir(workspace, current)
                continue
            if model.get("type") != "directory":
                raise ValueError(f"Remote path exists but is not a directory: {current}")

    def delete(self, workspace: str, path: str) -> None:
        response = self.http.delete(self.content_url(self.under_workspace(workspace, path)))
        if response.status_code >= 400:
            raise JupyterError(f"DELETE contents/{path} failed: {response.status_code} {response.text}")

    def terminals(self) -> list[dict[str, object]]:
        return self.request("GET", "terminals").json()

    def create_terminal(self) -> str:
        response = self.request("POST", "terminals", json={})
        data = response.json()
        name = data.get("name")
        if not isinstance(name, str):
            raise JupyterError(f"Unexpected terminal create response: {data!r}")
        return name

    def delete_terminal(self, name: str) -> None:
        quoted = urllib.parse.quote(name, safe="")
        response = self.http.delete(self.api_url(f"terminals/{quoted}"))
        if response.status_code not in (204, 404):
            raise JupyterError(f"DELETE terminal {name} failed: {response.status_code} {response.text}")
