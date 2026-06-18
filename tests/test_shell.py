from jupydex.terminal import shell_intro_command, split_before_marker


def test_shell_intro_wraps_interactive_bash_with_markers():
    command = shell_intro_command(
        "/remote/workspace",
        "__START__",
        "__DONE__",
    )

    assert "cd /remote/workspace" in command
    assert "__START__" in command
    assert "bash --noprofile --norc -i" in command
    assert "__DONE__" in command


def test_split_before_marker_flushes_plain_prompt():
    output, pending, found = split_before_marker(
        "[jupydex] /mnt/code/liang.zeng/nips/sandbox/workspace-kalen $ ",
        "__JUPYDEX_SHELL_DONE_abc__",
    )

    assert output == "[jupydex] /mnt/code/liang.zeng/nips/sandbox/workspace-kalen $ "
    assert pending == ""
    assert found is False


def test_split_before_marker_keeps_only_possible_marker_prefix():
    output, pending, found = split_before_marker(
        "hello __JUPYDEX",
        "__JUPYDEX_SHELL_DONE_abc__",
    )

    assert output == "hello "
    assert pending == "__JUPYDEX"
    assert found is False


def test_split_before_marker_detects_marker():
    output, pending, found = split_before_marker(
        "bye\n__JUPYDEX_SHELL_DONE_abc__:0\n",
        "__JUPYDEX_SHELL_DONE_abc__",
    )

    assert output == "bye\n"
    assert pending == "__JUPYDEX_SHELL_DONE_abc__:0\n"
    assert found is True
