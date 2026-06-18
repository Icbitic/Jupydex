# Jupydex

Jupydex makes a Jupyter Server feel like a small SSH target for Codex and local terminal work. It uses Jupyter's existing APIs, so it does not require SSH access or notebook-specific behavior.

The core model is simple:

- `jupydex-mirrors/<profile>` is the local shadow copy Codex edits.
- Jupyter Contents API handles file sync.
- Jupyter terminal websockets run commands on the server.
- `jupydex run` syncs local edits first, then streams remote output live.
- `jupydex shell` opens an interactive remote terminal in the selected workspace.

Notebook cell editing/execution is intentionally out of scope.

## Install

For development dependencies and tests:

```bash
uv venv
uv sync --dev
```

Install the `jupydex` command globally from this checkout:

```bash
uv tool install --editable .
```

After that, use `jupydex ...` directly from any shell.

## Configure

Create `jupydex.local.json` in the project root:

```json
{
  "profile": "default",
  "url": "http://host:8888/lab?token=TOKEN",
  "workspace": "/mnt/code/user/project",
  "mirror": "jupydex-mirrors/default"
}
```

Then save the profile:

```bash
jupydex connect-config
```

`jupydex.local.json` is ignored by git because it usually contains a token.

You can also connect without a config file:

```bash
jupydex connect 'http://host:8888/lab?token=TOKEN' \
  --workspace /mnt/code/user/project
```

`workspace` may be either an absolute server path or a Jupyter contents path. If you pass an absolute path, Jupydex searches for the matching path under the Jupyter server root.

## Mirror Workflow

Pull the remote workspace into the visible local mirror:

```bash
jupydex pull
jupydex mirror
```

By default, mirrors live at:

```text
jupydex-mirrors/<profile>
```

Edit files in that mirror with normal local tools:

```bash
cd "$(jupydex mirror)"
nano sleep.py
```

Run commands remotely from the selected Jupyter workspace:

```bash
jupydex run -- python sleep.py
```

`run` pushes dirty mirror files before executing. Output streams live, so long-running jobs show logs as they happen:

```bash
jupydex run -- python train.py
```

Use `--no-sync` when you intentionally want to run the current remote state without pushing local edits:

```bash
jupydex run --no-sync -- python script.py
```

## Interactive Shell

Open a remote shell in the selected workspace:

```bash
jupydex shell
```

The shell uses raw passthrough after setup. Terminal apps such as `nano`, `less`, and `top` should work. It is still a Jupyter terminal websocket rather than a real SSH daemon, so very demanding TUI programs may expose terminal-emulation differences. Exit with `exit` or `Ctrl-D`.

## Commands

```bash
jupydex status              # server, workspace, and mirror info
jupydex profiles            # saved local profiles
jupydex mirror              # print local mirror path
jupydex dirty               # local mirror changes since last sync

jupydex pull                # remote -> local mirror
jupydex push                # local mirror -> remote
jupydex push --delete       # also delete remote files removed locally

jupydex ls [path]
jupydex cat path
jupydex put local.py remote.py
jupydex get remote.py local.py
jupydex write notes.txt < notes.txt
jupydex mkdir data
jupydex rm old.txt
jupydex run -- python -V
jupydex shell
```

Paths passed to file commands are workspace-relative. A leading `/` means workspace root, not the host root, so `jupydex cat /README.md` reads `README.md` inside the selected workspace.

## Safety Notes

- Tokens are stored in the local Jupydex profile config. Prefer short-lived development tokens.
- `push` checks whether tracked remote files changed since the last pull and stops on conflicts unless `--force` is used.
- `run` and `shell` sync dirty mirror changes first by default. Use `--no-sync` to skip that.
- The mirror sync state is stored as `jupydex-mirror-state.json` inside each mirror and is not pushed to the Jupyter workspace.
