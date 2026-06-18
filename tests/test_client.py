from jupydex.client import parse_jupyter_url, token_from_url, workspace_relative_path
from jupydex.terminal import terminal_ws_url, websocket_base_url


def test_parse_lab_url_root_server():
    info = parse_jupyter_url("http://example.com:8888/lab?token=abc")
    assert info.base_url == "http://example.com:8888"
    assert info.token == "abc"


def test_token_from_url_returns_token_only_when_present():
    assert token_from_url("http://example.com:8888/lab?token=abc") == "abc"
    assert token_from_url("http://example.com:8888/lab") is None


def test_parse_lab_url_with_base_path():
    info = parse_jupyter_url("https://example.com/user/alice/lab/tree/x?token=abc")
    assert info.base_url == "https://example.com/user/alice"
    assert info.token == "abc"


def test_workspace_relative_path_treats_leading_slash_as_workspace_root():
    assert workspace_relative_path("/a/b.py") == "a/b.py"


def test_workspace_relative_path_rejects_escape():
    try:
        workspace_relative_path("../secret")
    except ValueError as exc:
        assert "escapes" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_terminal_ws_url_keeps_base_path():
    assert websocket_base_url("https://example.com/user/alice") == "wss://example.com/user/alice"
    assert (
        terminal_ws_url("https://example.com/user/alice", "tok", "1")
        == "wss://example.com/user/alice/terminals/websocket/1?token=tok"
    )
