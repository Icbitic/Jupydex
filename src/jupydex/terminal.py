from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
import re
import select
import secrets
import shlex
import shutil
import sys
import termios
import time
import tty
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


def terminal_size() -> tuple[int, int]:
    size = shutil.get_terminal_size(fallback=(80, 24))
    return size.lines, size.columns


def shell_intro_command(workspace_command_path: str, start_marker: str, done_marker: str) -> str:
    cd_target = shlex.quote(workspace_command_path)
    prompt = "[jupydex] \\w $ "
    return (
        f"cd {cd_target}; "
        "export TERM=${TERM:-xterm-256color}; "
        f"export PS1={shlex.quote(prompt)}; "
        f"printf '\\n{start_marker}\\n[jupydex] remote shell in %s\\n' \"$PWD\"; "
        "stty echo 2>/dev/null; "
        "bash --noprofile --norc -i; "
        "__jupydex_shell_status=$?; "
        f"printf '\\n{done_marker}:%s\\n' \"$__jupydex_shell_status\"\n"
    )


def split_before_marker(buffer: str, marker: str) -> tuple[str, str, bool]:
    marker_idx = buffer.find(marker)
    if marker_idx >= 0:
        return buffer[:marker_idx], buffer[marker_idx:], True

    keep_len = 0
    max_len = min(len(buffer), len(marker) - 1)
    for candidate_len in range(1, max_len + 1):
        if buffer.endswith(marker[:candidate_len]):
            keep_len = candidate_len

    if keep_len:
        return buffer[:-keep_len], buffer[-keep_len:], False
    return buffer, "", False


class TerminalOutputParser:
    def __init__(
        self,
        start_marker: str,
        done_marker: str,
        done_re: re.Pattern[str],
        emit: object | None = None,
    ) -> None:
        self.start_marker = start_marker
        self.done_marker = done_marker
        self.done_re = done_re
        self.emit = emit
        self.started = False
        self.pending = ""
        self.parts: list[str] = []

    @property
    def output(self) -> str:
        return "".join(self.parts).strip("\r\n")

    def feed(self, text: str) -> int | None:
        self.pending += text

        if not self.started:
            start_idx = self.pending.find(self.start_marker)
            if start_idx < 0:
                self.pending = self.pending[-len(self.start_marker):]
                return None
            self.pending = self.pending[start_idx + len(self.start_marker):]
            self.started = True

        match = self.done_re.search(self.pending)
        if match:
            self._flush(self.pending[: match.start()])
            self.pending = ""
            return int(match.group(1))

        output, self.pending, _found = split_before_marker(self.pending, self.done_marker)
        self._flush(output)
        return None

    def _flush(self, text: str) -> None:
        if not text:
            return
        self.parts.append(text)
        if self.emit is not None:
            self.emit(text)


async def interactive_terminal(
    client: JupyterClient,
    workspace_command_path: str,
) -> None:
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError(
            "The `websockets` package is required for `jupydex shell`. "
            "Install with `uv sync --dev`."
        ) from exc

    terminal_name = client.create_terminal()
    marker = secrets.token_hex(8)
    start_marker = f"__JUPYDEX_SHELL_START_{marker}__"
    done_marker = f"__JUPYDEX_SHELL_DONE_{marker}__"
    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    old_tty_attrs = termios.tcgetattr(stdin_fd) if sys.stdin.isatty() else None
    stop_event = asyncio.Event()

    async def send_stdin(ws: object) -> None:
        while not stop_event.is_set():
            ready, _, _ = await asyncio.to_thread(select.select, [stdin_fd], [], [], 0.1)
            if not ready:
                continue

            data = os.read(stdin_fd, 4096)
            if not data:
                await ws.send(json.dumps(["stdin", "exit\n"]))
                break
            await ws.send(json.dumps(["stdin", data.decode("utf-8", errors="ignore")]))

    async def recv_stdout(ws: object) -> None:
        started = False
        pending = ""
        while True:
            raw = await ws.recv()
            pending += terminal_payload(raw)

            if not started:
                start_idx = pending.find(start_marker)
                if start_idx < 0:
                    pending = pending[-len(start_marker):]
                    continue
                pending = pending[start_idx + len(start_marker):]
                started = True

            done_idx = pending.find(done_marker)
            if done_idx >= 0:
                output = pending[:done_idx].strip("\r\n")
                if output:
                    os.write(stdout_fd, output.encode("utf-8", errors="replace"))
                    os.write(stdout_fd, b"\n")
                stop_event.set()
                return

            output, pending, _found = split_before_marker(pending, done_marker)
            if output:
                os.write(stdout_fd, output.encode("utf-8", errors="replace"))

    try:
        async with websockets.connect(
            terminal_ws_url(client.base_url, client.token, terminal_name),
            max_size=None,
        ) as ws:
            rows, cols = terminal_size()
            await ws.send(json.dumps(["set_size", rows, cols]))
            await ws.send(json.dumps(["stdin", "stty -echo 2>/dev/null\n"]))
            await asyncio.sleep(0.1)
            await ws.send(json.dumps(["stdin", shell_intro_command(workspace_command_path, start_marker, done_marker)]))

            if old_tty_attrs is not None:
                tty.setraw(stdin_fd)

            stdin_task = asyncio.create_task(send_stdin(ws))
            stdout_task = asyncio.create_task(recv_stdout(ws))
            try:
                await stdout_task
            finally:
                stop_event.set()
                stdin_task.cancel()
                await asyncio.gather(stdin_task, return_exceptions=True)
    finally:
        if old_tty_attrs is not None:
            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_tty_attrs)
        client.delete_terminal(terminal_name)


async def run_terminal_command(
    client: JupyterClient,
    workspace_command_path: str,
    command: str,
    *,
    timeout: float = 300.0,
    stream: bool = False,
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
        f"printf '{start}'; "
        f"cd {cd_target} && bash -lc {quoted_command}; "
        "__jupydex_status=$?; "
        f"printf '{done}:%s\\n' \"$__jupydex_status\"\n"
    )

    deadline = time.monotonic() + timeout
    timed_out = False
    exit_code = 124
    stdout_fd = sys.stdout.fileno() if stream else None

    def emit_stdout(text: str) -> None:
        if stdout_fd is not None:
            os.write(stdout_fd, text.encode("utf-8", errors="replace"))

    parser = TerminalOutputParser(
        start,
        done,
        done_re,
        emit=emit_stdout if stream else None,
    )

    try:
        async with websockets.connect(terminal_ws_url(client.base_url, client.token, terminal_name), max_size=None) as ws:
            await ws.send(json.dumps(["stdin", "stty -echo 2>/dev/null\n"]))
            await asyncio.sleep(0.1)
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

                parsed_exit_code = parser.feed(terminal_payload(raw))
                if parsed_exit_code is not None:
                    exit_code = parsed_exit_code
                    break
    finally:
        client.delete_terminal(terminal_name)

    return CommandResult(
        command=command,
        exit_code=exit_code,
        output=parser.output,
        timed_out=timed_out,
    )


def run_terminal_command_sync(
    client: JupyterClient,
    workspace_command_path: str,
    command: str,
    *,
    timeout: float = 300.0,
    stream: bool = False,
) -> CommandResult:
    return asyncio.run(
        run_terminal_command(
            client,
            workspace_command_path,
            command,
            timeout=timeout,
            stream=stream,
        )
    )


def interactive_terminal_sync(
    client: JupyterClient,
    workspace_command_path: str,
) -> None:
    asyncio.run(interactive_terminal(client, workspace_command_path))
