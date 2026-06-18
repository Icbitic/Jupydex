import re

from jupydex.terminal import TerminalOutputParser


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
