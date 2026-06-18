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
