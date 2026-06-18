# Jupydex

Jupydex makes a Jupyter Server feel like a small SSH target for Codex and local terminal work. It uses Jupyter's existing APIs, so it does not require SSH access or notebook-specific behavior.

The core model is simple:

- `~/jdx-mirrors/<profile>` is the local shadow copy Codex edits.
- Jupyter Contents API handles file sync.
- Jupyter terminal websockets run commands on the server.
- `jdx run` syncs local edits first, then streams remote output live.
- `jdx shell` opens an interactive remote terminal in the selected workspace.

Notebook cell editing/execution is intentionally out of scope.

## Install

For development dependencies and tests:

```bash
uv venv
uv sync --dev
```

Install the `jdx` command globally from this checkout:

```bash
uv tool install --editable .
```

After that, use `jdx ...` directly from any shell.

## Configure

Save a Jupyter server as a named profile:

```bash
jdx --profile lab1 connect 'http://host:8888/lab?token=TOKEN' \
  --workspace /mnt/code/user/project
```

Profiles are stored in the global jdx config at `~/.config/jupydex/config.json`.

List profiles and choose the one used when `--profile` is omitted:

```bash
jdx profiles
jdx default lab1
jdx default
```

`workspace` may be either an absolute server path or a Jupyter contents path. If you pass an absolute path, Jupydex searches for the matching path under the Jupyter server root.

## Mirror Workflow

Pull the remote workspace into the visible local mirror:

```bash
jdx pull
jdx mirror
```

By default, mirrors live at:

```text
~/jdx-mirrors/<profile>
```

Edit files in that mirror with normal local tools:

```bash
cd "$(jdx mirror)"
nano sleep.py
```

Run commands remotely from the selected Jupyter workspace:

```bash
jdx run -- python sleep.py
```

`run` pushes dirty mirror files before executing. Output streams live, so long-running jobs show logs as they happen:

```bash
jdx run -- python train.py
```

Use `--no-sync` when you intentionally want to run the current remote state without pushing local edits:

```bash
jdx run --no-sync -- python script.py
```

## Interactive Shell

Open a remote shell in the selected workspace:

```bash
jdx shell
```

The shell uses raw passthrough after setup. Terminal apps such as `nano`, `less`, and `top` should work. It is still a Jupyter terminal websocket rather than a real SSH daemon, so very demanding TUI programs may expose terminal-emulation differences. Exit with `exit` or `Ctrl-D`.

## Commands

```bash
jdx status              # server, workspace, and mirror info
jdx default [profile]   # show or set default profile
jdx profiles            # saved local profiles
jdx mirror              # print local mirror path
jdx dirty               # local mirror changes since last sync

jdx pull                # remote -> local mirror
jdx push                # local mirror -> remote
jdx push --delete       # also delete remote files removed locally

jdx ls [path]
jdx cat path
jdx put local.py remote.py
jdx get remote.py local.py
jdx write notes.txt < notes.txt
jdx mkdir data
jdx rm old.txt
jdx run -- python -V
jdx shell
```

Paths passed to file commands are workspace-relative. A leading `/` means workspace root, not the host root, so `jdx cat /README.md` reads `README.md` inside the selected workspace.

## Safety Notes

- Tokens are stored in the global jdx profile config. Prefer short-lived development tokens.
- `push` checks whether tracked remote files changed since the last pull and stops on conflicts unless `--force` is used.
- `run` and `shell` sync dirty mirror changes first by default. Use `--no-sync` to skip that.
- If the local terminal receives `SIGHUP` or `SIGTERM`, `jdx` tries to close only the Jupyter terminal it created for that command. An uncatchable `SIGKILL` cannot be cleaned up by any CLI.
- The mirror sync state is stored as `jupydex-mirror-state.json` inside each mirror and is not pushed to the Jupyter workspace.
