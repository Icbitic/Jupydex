import re
import signal

from jupydex.terminal import LOCAL_TERMINAL_RESTORE, TerminalCleanup, TerminalOutputParser


class FakeClient:
    def __init__(self):
        self.deleted = []

    def delete_terminal(self, name, *, wait=False):
        self.deleted.append((name, wait))


def test_terminal_cleanup_is_idempotent():
    client = FakeClient()
    cleanup = TerminalCleanup(client, "abc")

    cleanup.cleanup()
    cleanup.cleanup()

    assert client.deleted == [("abc", True)]


def test_terminal_cleanup_signal_exits_after_cleanup():
    client = FakeClient()
    cleanup = TerminalCleanup(client, "abc")

    try:
        cleanup._cleanup_from_signal(signal.SIGTERM, None)
    except SystemExit as exc:
        assert exc.code == 128 + signal.SIGTERM
    else:
        raise AssertionError("Expected SystemExit")

    assert client.deleted == [("abc", True)]


def test_terminal_output_parser_streams_before_done_marker():
    emitted = []
    start = "__JUPYDEX_START_abc__"
    done = "__JUPYDEX_DONE_abc__"
    done_re = re.compile(rf"{re.escape(done)}:(\d+)")
    parser = TerminalOutputParser(start, done, done_re, emit=emitted.append)

    assert parser.feed("ignored prompt") is None
    assert emitted == []
    assert parser.feed(f"{start}line 1\nli") is None
    assert emitted == ["line 1\nli"]
    assert parser.feed("ne 2\n__JUPY") is None
    assert emitted == ["line 1\nli", "ne 2\n"]
    assert parser.feed("DEX_DONE_abc__:7\n") == 7
    assert parser.output == "line 1\nline 2"


def test_terminal_output_parser_holds_only_done_marker_prefix():
    emitted = []
    start = "__JUPYDEX_START_abc__"
    done = "__JUPYDEX_DONE_abc__"
    done_re = re.compile(rf"{re.escape(done)}:(\d+)")
    parser = TerminalOutputParser(start, done, done_re, emit=emitted.append)

    assert parser.feed(f"{start}progress 1") is None
    assert emitted == ["progress 1"]


def test_local_terminal_restore_disables_tui_modes():
    assert "\x1b[?1049l" in LOCAL_TERMINAL_RESTORE
    assert "\x1b[?1000l" in LOCAL_TERMINAL_RESTORE
    assert "\x1b[?1006l" in LOCAL_TERMINAL_RESTORE
    assert "\x1b[?2004l" in LOCAL_TERMINAL_RESTORE
    assert "\x1b[?25h" in LOCAL_TERMINAL_RESTORE
