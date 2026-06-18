import jupydex.cli as cli
from jupydex.cli import auto_profile_name, redact_token


def test_auto_profile_name_is_short_and_stable():
    first = auto_profile_name("http://example.com:8888", "tok")
    second = auto_profile_name("http://example.com:8888", "tok")

    assert first == second
    assert first.startswith("jdx-")
    assert len(first) == 10


def test_redact_token_keeps_only_edges():
    assert redact_token("short") == "*****"
    assert redact_token("1234567890abcdef") == "1234...cdef"


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
