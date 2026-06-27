import argparse

import jupydex.cli as cli
from jupydex.client import JupyterError
from jupydex.cli import auto_profile_name, parse_timeout, redact_token
from jupydex.config import Profile


def test_auto_profile_name_is_short_and_stable():
    first = auto_profile_name("http://example.com:8888", "tok")
    second = auto_profile_name("http://example.com:8888", "tok")

    assert first == second
    assert first.startswith("jdx-")
    assert len(first) == 10


def test_redact_token_keeps_only_edges():
    assert redact_token("short") == "*****"
    assert redact_token("1234567890abcdef") == "1234...cdef"


def test_parse_timeout_supports_disabled_and_seconds():
    assert parse_timeout("none") is None
    assert parse_timeout("off") is None
    assert parse_timeout("0") is None
    assert parse_timeout("1.5") == 1.5


def test_parse_timeout_rejects_invalid_value():
    try:
        parse_timeout("soon")
    except argparse.ArgumentTypeError:
        pass
    else:
        raise AssertionError("Expected ArgumentTypeError")


def test_connect_new_workspace_does_not_change_default(monkeypatch):
    class FakeClient:
        def __init__(self, base_url, token):
            self.base_url = base_url
            self.token = token

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def status(self):
            return {}

        def ensure_contents_dir(self, _workspace):
            return None

    class FakeProfiles:
        def __init__(self):
            self.saved = {}
            self.default_changes = []

        def list(self):
            return {}

        def save(self, name, profile):
            self.saved[name] = profile

        def set_default(self, name):
            self.default_changes.append(name)

    monkeypatch.setattr(cli, "JupyterClient", FakeClient)
    profiles = FakeProfiles()

    cli.connect_new_workspace(
        profiles=profiles,
        profile_name=None,
        url="http://example.com:8888/lab?token=abc",
        token=None,
        mirror=None,
    )

    assert list(profiles.saved) == ["jdx-cd9bbb"]
    assert profiles.default_changes == []


def stub_shell(monkeypatch):
    calls = []

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

    profile = Profile(
        base_url="http://example.com",
        token="tok",
        workspace="workspace",
        workspace_input="/remote/workspace",
    )

    monkeypatch.setattr(cli, "client_for_profile", lambda name: (FakeClient(), profile))
    monkeypatch.setattr(cli, "sync_before_remote_action", lambda *args: calls.append(("sync", args)))
    monkeypatch.setattr(cli, "interactive_terminal_sync", lambda *args: calls.append(("shell", args)))
    return calls


def test_shell_does_not_sync_by_default(monkeypatch):
    calls = stub_shell(monkeypatch)

    args = cli.build_parser().parse_args(["--profile", "lab1", "shell"])

    assert cli.command_shell(args) == 0
    assert [name for name, _args in calls] == ["shell"]


def test_shell_sync_is_opt_in(monkeypatch):
    calls = stub_shell(monkeypatch)

    args = cli.build_parser().parse_args(["--profile", "lab1", "shell", "--sync"])

    assert cli.command_shell(args) == 0
    assert [name for name, _args in calls] == ["sync", "shell"]
    _name, sync_args = calls[0]
    assert sync_args[-2:] == (False, False)


def test_shell_force_sync_implies_sync(monkeypatch):
    calls = stub_shell(monkeypatch)

    args = cli.build_parser().parse_args(["--profile", "lab1", "shell", "--force-sync"])

    assert cli.command_shell(args) == 0
    assert [name for name, _args in calls] == ["sync", "shell"]
    _name, sync_args = calls[0]
    assert sync_args[-2:] == (False, True)


def test_shell_error_names_profile(monkeypatch):
    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

    profile = Profile(
        base_url="http://example.com",
        token="tok",
        workspace="workspace",
        workspace_input="/remote/workspace",
    )

    monkeypatch.setattr(cli, "client_for_profile", lambda name: (FakeClient(), profile))
    monkeypatch.setattr(
        cli,
        "interactive_terminal_sync",
        lambda *_args: (_ for _ in ()).throw(JupyterError("POST /api/terminals failed: 502")),
    )

    args = cli.build_parser().parse_args(["--profile", "lab1", "shell"])

    try:
        cli.command_shell(args)
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected RuntimeError")

    assert "lab1" in message
    assert "http://example.com" in message
    assert "POST /api/terminals failed: 502" in message
