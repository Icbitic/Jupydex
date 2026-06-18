from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .client import JupyterClient, parse_jupyter_url
from .config import ConfigStore, Profile, load_connect_params
from .mirror import (
    default_mirror_path,
    mirror_path_for_profile,
    mirror_status,
    pull_mirror,
    push_mirror,
)
from .terminal import interactive_terminal_sync, run_terminal_command_sync


def resolve_mirror_path(path: str | None, profile_name: str) -> Path:
    if not path:
        return default_mirror_path(profile_name)

    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.home() / candidate
    return candidate.resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jdx",
        description="SSH-like access to a selected Jupyter Server workspace.",
    )
    parser.add_argument("--profile", help="Profile name")

    sub = parser.add_subparsers(dest="command_name", required=True)

    connect = sub.add_parser("connect", help="Create or update a Jupyter profile")
    connect.add_argument("url", help="JupyterLab/server URL, optionally with ?token=...")
    connect.add_argument("--token", help="Token if not included in the URL")
    connect.add_argument("--workspace", required=True, help="Workspace path to use")
    connect.add_argument("--mirror", help="Local shadow mirror path")

    connect_config = sub.add_parser("connect-config", help="Create or update a profile from a JSON params file")
    connect_config.add_argument("path", nargs="?", default="jupydex.local.json")

    default = sub.add_parser("default", help="Show or set the default profile")
    default.add_argument("profile_name", nargs="?", help="Profile to use when --profile is omitted")

    sub.add_parser("profiles", help="List saved profiles")
    sub.add_parser("status", help="Show Jupyter server status")
    sub.add_parser("mirror", help="Print the local shadow mirror path")

    pull = sub.add_parser("pull", help="Pull the remote workspace into the local mirror")
    pull.add_argument("path", nargs="?", default=".")
    pull.add_argument("--max-size-mb", type=float, default=50.0)
    pull.add_argument("--all", action="store_true", help="Pull files without a size limit")
    pull.add_argument("--prune", action="store_true", help="Remove clean tracked files missing remotely")

    push = sub.add_parser("push", help="Push local mirror changes back to Jupyter")
    push.add_argument("--force", action="store_true", help="Overwrite remote files even if they changed")
    push.add_argument("--delete", action="store_true", help="Delete remote files removed from the mirror")

    sub.add_parser("dirty", help="Show local mirror changes since the last pull/push")

    ls = sub.add_parser("ls", help="List a workspace directory")
    ls.add_argument("path", nargs="?", default=".")

    cat = sub.add_parser("cat", help="Print a remote file")
    cat.add_argument("path")

    write = sub.add_parser("write", help="Write stdin to a remote file")
    write.add_argument("path")

    put = sub.add_parser("put", help="Upload a local file")
    put.add_argument("local")
    put.add_argument("remote", nargs="?")

    get = sub.add_parser("get", help="Download a remote file")
    get.add_argument("remote")
    get.add_argument("local", nargs="?")

    mkdir = sub.add_parser("mkdir", help="Create a remote directory")
    mkdir.add_argument("path")

    rm = sub.add_parser("rm", help="Delete a remote file or empty directory")
    rm.add_argument("path")

    run = sub.add_parser("run", help="Sync local mirror changes, then run a command in the selected workspace")
    run.add_argument("--timeout", type=float, default=300.0)
    run.add_argument("--no-sync", action="store_true", help="Run without pushing local mirror changes first")
    run.add_argument("--force-sync", action="store_true", help="Overwrite remote changes while syncing before run")
    run.add_argument("remote_command", nargs=argparse.REMAINDER)

    shell = sub.add_parser("shell", help="Sync local mirror changes, then open an interactive remote shell")
    shell.add_argument("--no-sync", action="store_true", help="Open shell without pushing local mirror changes first")
    shell.add_argument("--force-sync", action="store_true", help="Overwrite remote changes while syncing before shell")

    return parser


def client_for_profile(profile_name: str) -> tuple[JupyterClient, Profile]:
    profile = ConfigStore().get_profile(profile_name)
    return JupyterClient(profile.base_url, profile.token), profile


def print_listing(entries: list[dict[str, object]]) -> None:
    for entry in sorted(entries, key=lambda item: str(item.get("name", ""))):
        typ = "d" if entry.get("type") == "directory" else "-"
        size = entry.get("size")
        size_text = "" if size is None else str(size)
        name = entry.get("name", "")
        print(f"{typ} {size_text:>10} {name}")


def command_connect(args: argparse.Namespace) -> int:
    return connect_with_values(
        profile_name=args.profile,
        url=args.url,
        token=args.token,
        workspace_input=args.workspace,
        mirror=args.mirror,
    )


def connect_with_values(
    *,
    profile_name: str,
    url: str,
    token: str | None,
    workspace_input: str,
    mirror: str | None,
) -> int:
    info = parse_jupyter_url(url, token)
    with JupyterClient(info.base_url, info.token) as client:
        workspace = client.resolve_workspace(workspace_input)
        client.status()

    mirror_path = resolve_mirror_path(mirror, profile_name)
    profile = Profile(
        base_url=info.base_url,
        token=info.token,
        workspace=workspace,
        workspace_input=workspace_input,
        mirror_path=str(mirror_path),
    )
    ConfigStore().save_profile(profile_name, profile)
    print(f"Connected profile {profile_name!r}")
    print(f"Server: {info.base_url}")
    print(f"Workspace: {workspace}")
    print(f"Mirror: {mirror_path}")
    return 0


def command_connect_config(args: argparse.Namespace) -> int:
    params = load_connect_params(args.path)
    return connect_with_values(
        profile_name=params.profile,
        url=params.url,
        token=params.token,
        workspace_input=params.workspace,
        mirror=params.mirror,
    )


def command_profiles(_args: argparse.Namespace) -> int:
    profiles = ConfigStore().list_profiles()
    if not profiles:
        print("No profiles saved")
        return 0
    for name, profile in sorted(profiles.items()):
        print(f"{name}\t{profile.base_url}\t{profile.workspace}")
    return 0


def command_default(args: argparse.Namespace) -> int:
    store = ConfigStore()
    if not args.profile_name:
        print(store.default_profile_name())
        return 0

    store.set_default_profile(args.profile_name)
    print(f"Default profile: {args.profile_name}")
    return 0


def command_status(args: argparse.Namespace) -> int:
    client, profile = client_for_profile(args.profile)
    with client:
        status = client.status()
        terminals = client.terminals()
    print(f"server: {status.get('started')}")
    print(f"kernels: {status.get('kernels')}")
    print(f"connections: {status.get('connections')}")
    print(f"terminals: {len(terminals)}")
    print(f"workspace: {profile.workspace}")
    print(f"mirror: {mirror_path_for_profile(args.profile, profile)}")
    return 0


def command_mirror(args: argparse.Namespace) -> int:
    profile = ConfigStore().get_profile(args.profile)
    print(mirror_path_for_profile(args.profile, profile))
    return 0


def command_pull(args: argparse.Namespace) -> int:
    client, profile = client_for_profile(args.profile)
    max_size = None if args.all else int(args.max_size_mb * 1024 * 1024)
    with client:
        summary = pull_mirror(
            client,
            args.profile,
            profile,
            subpath=args.path,
            max_size_bytes=max_size,
            prune=args.prune,
        )
    print(f"mirror: {mirror_path_for_profile(args.profile, profile)}")
    print(f"pulled: {summary.pulled}")
    if summary.skipped:
        print(f"skipped: {summary.skipped}")
    return 0


def command_push(args: argparse.Namespace) -> int:
    client, profile = client_for_profile(args.profile)
    with client:
        summary = push_mirror(
            client,
            args.profile,
            profile,
            force=args.force,
            delete=args.delete,
        )
    print(f"pushed: {summary.pushed}")
    if summary.deleted_remote:
        print(f"deleted remote: {summary.deleted_remote}")
    return 0


def command_dirty(args: argparse.Namespace) -> int:
    profile = ConfigStore().get_profile(args.profile)
    status = mirror_status(args.profile, profile)
    for label in ("added", "modified", "deleted"):
        for path in status[label]:
            print(f"{label[0].upper()} {path}")
    return 1 if any(status.values()) else 0


def command_ls(args: argparse.Namespace) -> int:
    client, profile = client_for_profile(args.profile)
    with client:
        print_listing(client.list_dir(profile.workspace, args.path))
    return 0


def command_cat(args: argparse.Namespace) -> int:
    client, profile = client_for_profile(args.profile)
    with client:
        data, _model = client.read_file(profile.workspace, args.path)
    sys.stdout.buffer.write(data)
    if data and not data.endswith(b"\n"):
        sys.stdout.write("\n")
    return 0


def command_write(args: argparse.Namespace) -> int:
    data = sys.stdin.buffer.read()
    client, profile = client_for_profile(args.profile)
    with client:
        client.write_file(profile.workspace, args.path, data)
    return 0


def command_put(args: argparse.Namespace) -> int:
    local = Path(args.local)
    remote = args.remote or local.name
    data = local.read_bytes()
    client, profile = client_for_profile(args.profile)
    with client:
        client.write_file(profile.workspace, remote, data)
    print(f"{local} -> {remote}")
    return 0


def command_get(args: argparse.Namespace) -> int:
    local = Path(args.local or Path(args.remote).name)
    client, profile = client_for_profile(args.profile)
    with client:
        data, _model = client.read_file(profile.workspace, args.remote)
    local.write_bytes(data)
    print(f"{args.remote} -> {local}")
    return 0


def command_mkdir(args: argparse.Namespace) -> int:
    client, profile = client_for_profile(args.profile)
    with client:
        client.mkdir(profile.workspace, args.path)
    return 0


def command_rm(args: argparse.Namespace) -> int:
    client, profile = client_for_profile(args.profile)
    with client:
        client.delete(profile.workspace, args.path)
    return 0


def command_run(args: argparse.Namespace) -> int:
    command = remote_command_text(args.remote_command)
    if not command:
        raise SystemExit("Usage: jdx run -- <command>")

    client, profile = client_for_profile(args.profile)
    with client:
        sync_before_remote_action(client, args.profile, profile, args.no_sync, args.force_sync)

        result = run_terminal_command_sync(
            client,
            profile.workspace_input or profile.workspace,
            command,
            timeout=args.timeout,
            stream=True,
        )

    if result.timed_out:
        print(f"Command timed out after {args.timeout:g}s", file=sys.stderr)
    return result.exit_code


def remote_command_text(parts: list[str]) -> str:
    command = " ".join(parts).strip()
    if command.startswith("-- "):
        return command[3:].strip()
    return command


def sync_before_remote_action(
    client: JupyterClient,
    profile_name: str,
    profile: Profile,
    no_sync: bool,
    force_sync: bool,
) -> None:
    if no_sync:
        return

    status = mirror_status(profile_name, profile)
    if not any(status.values()):
        return

    summary = push_mirror(
        client,
        profile_name,
        profile,
        force=force_sync,
        delete=True,
    )
    print(
        f"synced: pushed {summary.pushed}, deleted remote {summary.deleted_remote}",
        file=sys.stderr,
    )


def command_shell(args: argparse.Namespace) -> int:
    client, profile = client_for_profile(args.profile)
    with client:
        sync_before_remote_action(client, args.profile, profile, args.no_sync, args.force_sync)
        interactive_terminal_sync(
            client,
            profile.workspace_input or profile.workspace,
        )
    return 0


COMMANDS = {
    "connect": command_connect,
    "connect-config": command_connect_config,
    "default": command_default,
    "profiles": command_profiles,
    "status": command_status,
    "mirror": command_mirror,
    "pull": command_pull,
    "push": command_push,
    "dirty": command_dirty,
    "ls": command_ls,
    "cat": command_cat,
    "write": command_write,
    "put": command_put,
    "get": command_get,
    "mkdir": command_mkdir,
    "rm": command_rm,
    "run": command_run,
    "shell": command_shell,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.profile is None:
        args.profile = ConfigStore().default_profile_name()
    try:
        return COMMANDS[args.command_name](args)
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except KeyError as exc:
        message = exc.args[0] if exc.args else str(exc)
        print(f"jdx: {message}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"jdx: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
