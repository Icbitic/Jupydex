# Jupydex

Jupydex makes a Jupyter Server feel like a lightweight SSH target for Codex.

It deliberately avoids notebook abstractions. The model is:

- Jupyter Contents API as remote file access.
- Jupyter terminal websocket as remote shell execution.
- A selected workspace as the remote working directory.

## Install

```bash
uv venv
uv sync --dev
```

## Connect

Use a JupyterLab URL with a token. The token is saved in your local Jupydex
profile, so prefer a short-lived development token.

Put connection parameters in `jupydex.local.json`:

```json
{
  "profile": "default",
  "url": "http://host:8888/lab?token=TOKEN",
  "workspace": "/mnt/code/user/project",
  "mirror": ".jupydex/mirrors/default"
}
```

Then connect from that file:

```bash
jupydex connect-config
```

`jupydex.local.json` is ignored by git because it usually contains a token.

You can still connect from CLI args:

```bash
jupydex --profile default connect 'http://host:8888/lab?token=TOKEN' \
  --workspace /mnt/code/user/project
```

Jupydex accepts either an absolute remote path or a Jupyter contents path. If an
absolute path is provided, it tries suffixes until it finds the matching contents
path under the Jupyter server root.

## SSH-like Usage

Pull the remote workspace into the local shadow mirror first:

```bash
jupydex pull
jupydex mirror
```

By default the mirror lives at:

```text
.jupydex/mirrors/<profile>
```

That local mirror is where Codex should inspect files, run `rg`, and apply
patches. Push changed local files back to Jupyter when ready:

```bash
jupydex push
```

Use `--delete` to also delete remote files that were removed locally.

```bash
jupydex status
jupydex ls
jupydex cat pyproject.toml
jupydex run -- pwd
jupydex run -- ls -la
jupydex run -- python -V
```

`jupydex run` pushes dirty mirror files before executing, so the common loop is:

```bash
cd "$(jupydex mirror)"
nano sleep.py
cd -
jupydex run -- python sleep.py
```

Use `--no-sync` if you intentionally want to run the current remote state
without pushing local mirror changes first.

Command output is streamed as it arrives, so long-running jobs show live logs:

```bash
jupydex run -- python train.py
```

For a more SSH-like interactive session:

```bash
jupydex shell
```

This opens a Jupyter terminal websocket in the selected workspace. It is not a
real SSH daemon, but it behaves like a local terminal connected to the remote
Jupyter server. Exit with `exit` or `Ctrl-D`.

File transfer:

```bash
jupydex put local.py remote.py
jupydex get remote.py local.py
jupydex write notes.txt < notes.txt
jupydex mkdir data
jupydex rm old.txt
```

Paths are workspace-relative. A leading `/` means workspace root, not host root,
so `jupydex cat /README.md` reads `README.md` in the selected workspace.

## Design Notes

This is intentionally closer to `ssh` plus `sftp` than to a notebook client.
For Codex, that means the useful primitive operations are simple:

- inspect files
- patch files
- run commands
- fetch logs/artifacts

The shadow mirror is intentionally first-class because it gives Codex local
tooling ergonomics while preserving remote execution on the Jupyter machine.

Notebook cell editing and execution are out of scope.
