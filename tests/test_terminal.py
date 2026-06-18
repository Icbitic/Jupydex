import re

from jupydex.terminal import clean_terminal_output


def test_clean_terminal_output_uses_last_start_marker():
    start = "__JUPYDEX_START_abc__"
    done = "__JUPYDEX_DONE_abc__"
    done_re = re.compile(rf"{re.escape(done)}:(\d+)")
    raw = (
        f"printf '\\n{start}\\n'; cd /x && bash -lc 'echo X'; "
        f"printf '\\n{done}:%s\\n' \"$status\"\r\n"
        f"\x1b[?2004l\r\r\n{start}\r\nX\r\n{done}:0\r\n"
    )

    assert clean_terminal_output(raw, start, done_re) == "X"
