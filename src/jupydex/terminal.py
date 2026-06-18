from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import re
import secrets
import shlex
import time
import urllib.parse

from .client import JupyterClient


@dataclass
class CommandResult:
    command: str
    exit_code: int
    output: str
    timed_out: bool = False


def websocket_base_url(base_url: str) -> str:
    parsed = urllib.parse.urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urllib.parse.urlunparse((scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))


def terminal_ws_url(base_url: str, token: str, name: str) -> str:
    quoted_name = urllib.parse.quote(name, safe="")
    query = urllib.parse.urlencode({"token": token})
    return f"{websocket_base_url(base_url)}/terminals/websocket/{quoted_name}?{query}"


def terminal_payload(message: str) -> str:
    try:
        decoded = json.loads(message)
    except json.JSONDecodeError:
        return message

    if isinstance(decoded, list) and len(decoded) >= 2 and isinstance(decoded[1], str):
        return decoded[1]
    if isinstance(decoded, dict):
        data = decoded.get("data")
        if isinstance(data, str):
            return data
    return ""


def clean_terminal_output(buffer: str, start_marker: str, done_re: re.Pattern[str]) -> str:
    # Jupyter terminals may echo the submitted wrapper command. That echoed line
    # contains the marker literals, so use the last start marker: the one printed
    # immediately before the user's command runs.
    start_idx = buffer.rfind(start_marker)
    output = buffer[start_idx + len(start_marker):] if start_idx >= 0 else buffer
    match = done_re.search(output)
    if match:
        output = output[: match.start()]
    return output.strip("\r\n")


async def run_terminal_command(
    client: JupyterClient,
    workspace_command_path: str,
    command: str,
    *,
    timeout: float = 300.0,
) -> CommandResult:
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError(
            "The `websockets` package is required for `jupydex run`. "
            "Install with `python -m pip install -e .`."
        ) from exc

    terminal_name = client.create_terminal()
    marker = secrets.token_hex(8)
    start = f"__JUPYDEX_START_{marker}__"
    done = f"__JUPYDEX_DONE_{marker}__"
    done_re = re.compile(rf"{re.escape(done)}:(\d+)")

    cd_target = shlex.quote(workspace_command_path)
    quoted_command = shlex.quote(command)
    shell_line = (
        "stty -echo 2>/dev/null; "
        f"printf '\\n{start}\\n'; "
        f"cd {cd_target} && bash -lc {quoted_command}; "
        "__jupydex_status=$?; "
        f"printf '\\n{done}:%s\\n' \"$__jupydex_status\"\n"
    )

    buffer = ""
    deadline = time.monotonic() + timeout
    timed_out = False
    exit_code = 124

    try:
        async with websockets.connect(terminal_ws_url(client.base_url, client.token, terminal_name), max_size=None) as ws:
            await ws.send(json.dumps(["stdin", shell_line]))
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break

                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=min(1.0, remaining))
                except asyncio.TimeoutError:
                    continue

                buffer += terminal_payload(raw)
                match = done_re.search(buffer)
                if match:
                    exit_code = int(match.group(1))
                    break
    finally:
        client.delete_terminal(terminal_name)

    return CommandResult(
        command=command,
        exit_code=exit_code,
        output=clean_terminal_output(buffer, start, done_re),
        timed_out=timed_out,
    )


def run_terminal_command_sync(
    client: JupyterClient,
    workspace_command_path: str,
    command: str,
    *,
    timeout: float = 300.0,
) -> CommandResult:
    return asyncio.run(
        run_terminal_command(
            client,
            workspace_command_path,
            command,
            timeout=timeout,
        )
    )
