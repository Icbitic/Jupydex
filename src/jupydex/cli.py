from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys

from .client import JupyterClient, parse_jupyter_url, token_from_url
from .config import Profile, ProfileManager, config_path
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
    connect.add_argument("--workspace", help="Existing workspace path to use")
    connect.add_argument("--mirror", help="Local shadow mirror path")

    profile = sub.add_parser(
        "profile",
        help="Manage local profiles",
        description="Manage local profiles. Run without an action to open the interactive manager.",
    )
    profile_sub = profile.add_subparsers(dest="profile_action", metavar="[action]")

    profile_sub.add_parser("list", help="List saved profiles")
    default = profile_sub.add_parser("default", help="Show or set the default profile")
    default.add_argument("profile_name", nargs="?", help="Profile to use when --profile is omitted")
    remove_profile = profile_sub.add_parser("remove", help="Remove a saved profile")
    remove_profile.add_argument("profile_name", help="Profile to remove")
    show_profile = profile_sub.add_parser("show", help="Show profile details")
    show_profile.add_argument("profile_name", nargs="?", help="Profile to show")
    profile_sub.add_parser("path", help="Print the profile config path")

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
    profile = ProfileManager().get(profile_name)
    return JupyterClient(profile.base_url, profile.token), profile


def print_listing(entries: list[dict[str, object]]) -> None:
    for entry in sorted(entries, key=lambda item: str(item.get("name", ""))):
        typ = "d" if entry.get("type") == "directory" else "-"
        size = entry.get("size")
        size_text = "" if size is None else str(size)
        name = entry.get("name", "")
        print(f"{typ} {size_text:>10} {name}")


def command_connect(args: argparse.Namespace) -> int:
    profiles = ProfileManager()
    if not args.workspace:
        return connect_new_workspace(
            profiles=profiles,
            profile_name=args.profile,
            url=args.url,
            token=args.token,
            mirror=args.mirror,
        )

    return connect_existing_workspace(
        profiles=profiles,
        profile_name=args.profile or profiles.default_name(),
        url=args.url,
        token=args.token,
        workspace_input=args.workspace,
        mirror=args.mirror,
    )


def connect_existing_workspace(
    *,
    profiles: ProfileManager,
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
    profiles.save(profile_name, profile)
    print_connection(profile_name, info.base_url, workspace, mirror_path)
    return 0


def connect_new_workspace(
    *,
    profiles: ProfileManager,
    profile_name: str | None,
    url: str,
    token: str | None,
    mirror: str | None,
) -> int:
    info = parse_jupyter_url(url, token)
    if profile_name:
        resolved_name = profile_name
    else:
        resolved_name = auto_profile_name(info.base_url, info.token)
        reject_profile_collision(profiles, resolved_name, info.base_url, info.token)
    workspace = resolved_name

    with JupyterClient(info.base_url, info.token) as client:
        client.status()
        client.ensure_contents_dir(workspace)

    mirror_path = resolve_mirror_path(mirror, resolved_name)
    profile = Profile(
        base_url=info.base_url,
        token=info.token,
        workspace=workspace,
        workspace_input=workspace,
        mirror_path=str(mirror_path),
    )
    profiles.save(resolved_name, profile)
    profiles.set_default(resolved_name)

    print_connection(resolved_name, info.base_url, workspace, mirror_path, default=True)
    return 0


def auto_profile_name(base_url: str, token: str) -> str:
    digest = hashlib.sha256(f"{base_url}\0{token}".encode("utf-8")).hexdigest()
    return f"jdx-{digest[:6]}"


def reject_profile_collision(
    profiles: ProfileManager,
    name: str,
    base_url: str,
    token: str,
) -> None:
    existing = profiles.list().get(name)
    if existing is None:
        return
    if existing.base_url == base_url and existing.token == token:
        return
    raise ValueError(
        f"Profile {name!r} already exists for another server. "
        "Use `jdx --profile NAME connect URL` to choose a name."
    )


def print_connection(
    profile_name: str,
    base_url: str,
    workspace: str,
    mirror_path: Path,
    *,
    default: bool = False,
) -> None:
    print(f"Connected profile {profile_name!r}")
    print(f"Server: {base_url}")
    print(f"Workspace: {workspace}")
    print(f"Mirror: {mirror_path}")
    if default:
        print(f"Default profile: {profile_name}")


def command_profile(args: argparse.Namespace) -> int:
    action = args.profile_action
    if action is None:
        return command_profile_interactive(args)
    if action == "list":
        return command_profile_list(args)
    if action == "default":
        return command_profile_default(args)
    if action == "remove":
        return command_profile_remove(args)
    if action == "show":
        return command_profile_show(args)
    if action == "path":
        return command_profile_path(args)
    raise ValueError(f"Unknown profile action: {action}")


def command_profile_interactive(_args: argparse.Namespace) -> int:
    profiles = ProfileManager()
    while True:
        print()
        print("jdx profile manager")
        print(f"Config: {config_path()}")
        print_profile_table(profiles)
        print()
        print("1) Connect new profile")
        print("2) Set default profile")
        print("3) Remove profile")
        print("4) Show profile details")
        print("5) Print config path")
        print("q) Quit")

        try:
            choice = prompt("Select action", default="q").lower()
        except EOFError:
            return 0
        if choice in ("q", "quit", "exit"):
            return 0

        try:
            if choice in ("1", "connect", "new"):
                interactive_connect_profile(profiles)
            elif choice in ("2", "default"):
                interactive_set_default(profiles)
            elif choice in ("3", "remove", "delete"):
                interactive_remove_profile(profiles)
            elif choice in ("4", "show", "details"):
                interactive_show_profile(profiles)
            elif choice in ("5", "path"):
                print(config_path())
            else:
                print(f"Unknown action: {choice}")
        except EOFError:
            return 0
        except Exception as exc:
            print(f"jdx: {exc}", file=sys.stderr)


def command_profile_list(_args: argparse.Namespace) -> int:
    print_profile_table(ProfileManager())
    return 0


def print_profile_table(profiles: ProfileManager) -> bool:
    items = profiles.list()
    default_name = profiles.default_name()
    if not items:
        print("No profiles saved")
        return False
    for name, profile in sorted(items.items()):
        marker = "*" if name == default_name else " "
        print(f"{marker} {name}\t{profile.base_url}\t{profile.workspace}")
    return True


def command_profile_default(args: argparse.Namespace) -> int:
    profiles = ProfileManager()
    if not args.profile_name:
        print(profiles.default_name())
        return 0

    profiles.set_default(args.profile_name)
    print(f"Default profile: {args.profile_name}")
    return 0


def command_profile_remove(args: argparse.Namespace) -> int:
    default_name = ProfileManager().remove(args.profile_name)
    print(f"Removed profile {args.profile_name!r}")
    if default_name:
        print(f"Default profile: {default_name}")
    else:
        print("No profiles saved")
    return 0


def command_profile_show(args: argparse.Namespace) -> int:
    profiles = ProfileManager()
    profile_name = args.profile_name or profiles.default_name()
    print_profile_details(profile_name, profiles.get(profile_name))
    return 0


def command_profile_path(_args: argparse.Namespace) -> int:
    print(config_path())
    return 0


def interactive_connect_profile(profiles: ProfileManager) -> None:
    url = prompt_required("JupyterLab URL")
    token = token_from_url(url)
    if not token:
        token = prompt_required("Token")
    info = parse_jupyter_url(url, token)
    default_name = auto_profile_name(info.base_url, info.token)
    profile_name = prompt("Profile name", default=default_name)
    workspace = prompt("Existing workspace path, blank to create one", default="")
    mirror = prompt("Local mirror path, blank for default", default="") or None

    if workspace:
        connect_existing_workspace(
            profiles=profiles,
            profile_name=profile_name,
            url=url,
            token=token,
            workspace_input=workspace,
            mirror=mirror,
        )
        if confirm("Make this the default profile", default=True):
            profiles.set_default(profile_name)
            print(f"Default profile: {profile_name}")
        return

    connect_new_workspace(
        profiles=profiles,
        profile_name=profile_name,
        url=url,
        token=token,
        mirror=mirror,
    )


def interactive_set_default(profiles: ProfileManager) -> None:
    name = choose_profile(profiles, "Profile to make default")
    if not name:
        return
    profiles.set_default(name)
    print(f"Default profile: {name}")


def interactive_remove_profile(profiles: ProfileManager) -> None:
    name = choose_profile(profiles, "Profile to remove")
    if not name:
        return
    if not confirm(f"Remove profile {name!r}", default=False):
        print("Cancelled")
        return
    default_name = profiles.remove(name)
    print(f"Removed profile {name!r}")
    if default_name:
        print(f"Default profile: {default_name}")
    else:
        print("No profiles saved")


def interactive_show_profile(profiles: ProfileManager) -> None:
    name = choose_profile(profiles, "Profile to show")
    if name:
        print_profile_details(name, profiles.get(name))


def choose_profile(profiles: ProfileManager, label: str) -> str | None:
    names = sorted(profiles.list())
    if not names:
        print("No profiles saved")
        return None

    for idx, name in enumerate(names, start=1):
        marker = "*" if name == profiles.default_name() else " "
        print(f"{idx}) {marker} {name}")

    value = prompt(label, default="")
    if not value:
        return None
    if value.isdigit():
        idx = int(value)
        if 1 <= idx <= len(names):
            return names[idx - 1]
    if value in names:
        return value
    print(f"No profile selected for {value!r}")
    return None


def print_profile_details(name: str, profile: Profile) -> None:
    print(f"name: {name}")
    print(f"server: {profile.base_url}")
    print(f"token: {redact_token(profile.token)}")
    print(f"workspace: {profile.workspace}")
    print(f"workspace input: {profile.workspace_input}")
    print(f"mirror: {profile.mirror_path or default_mirror_path(name)}")


def redact_token(token: str) -> str:
    if len(token) <= 10:
        return "*" * len(token)
    return f"{token[:4]}...{token[-4:]}"


def prompt(label: str, *, default: str) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def prompt_required(label: str) -> str:
    while True:
        value = prompt(label, default="")
        if value:
            return value
        print(f"{label} is required")


def confirm(label: str, *, default: bool) -> bool:
    default_text = "Y/n" if default else "y/N"
    value = prompt(f"{label}? {default_text}", default="").lower()
    if not value:
        return default
    return value in ("y", "yes")


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
    profile = ProfileManager().get(args.profile)
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
    profile = ProfileManager().get(args.profile)
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
    "profile": command_profile,
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
    if args.profile is None and args.command_name not in ("connect", "profile"):
        args.profile = ProfileManager().default_name()
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
