from jupydex.cli import auto_profile_name


def test_auto_profile_name_is_short_and_stable():
    first = auto_profile_name("http://example.com:8888", "tok")
    second = auto_profile_name("http://example.com:8888", "tok")

    assert first == second
    assert first.startswith("jdx-")
    assert len(first) == 10
