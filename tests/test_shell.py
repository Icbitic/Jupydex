from jupydex.terminal import shell_intro_command


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
