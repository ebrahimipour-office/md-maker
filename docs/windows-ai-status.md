# Windows status of AI-assisted conversion

Status: **implemented, not yet tested on Windows** (as of 2026-10-26).
Everything below was developed and tested on Linux only. Work through the
checklist at the end on a Windows machine before relying on it.

## What was done for Windows

### Fixed: `claude.cmd` argument mangling
An npm install of Claude Code runs as `claude.cmd`. Windows starts `.cmd`
files through `cmd.exe`, which breaks arguments that contain newlines,
Persian text or `& | < > ^ % !`. The first version passed the system prompt
on the command line, and that prompt contains all of these, so with an
npm install every AI call would have failed and fallen back to the local
draft.

Changes in `src/md_maker/ai/claude_cli.py`:
- The system prompt is written to a UTF-8 file in the per-run temp folder
  and passed with `--system-prompt-file`. This flag was checked against
  CLI 2.1.310 on Linux.
- The page text and image go through stdin (stream-json), as before.
- `_command()` refuses any argument containing a character that `cmd.exe`
  would mangle (`_CMD_UNSAFE`). The arguments left on the command line are
  model names, flags, a number and the JSON schema; the schema has quotes
  but no metacharacters.

### Fixed: orphaned processes on timeout
With `claude.cmd`, killing the process only kills `cmd.exe` and leaves
`node` running. On timeout, `_kill_tree()` now runs `taskkill /F /T` on
Windows.

### Added: no console windows for the background calls
The CLI is started with `CREATE_NO_WINDOW`, so no window flashes per call.
This matters for the standalone `md-maker.exe` launched by dragging files
onto it.

### Already Windows-aware (no change needed)
- Settings: `%APPDATA%\md-maker\config.toml`. Cache:
  `%LOCALAPPDATA%\md-maker\cache` (`config._user_dir`).
- `shutil.which("claude")` finds both `claude.exe` (native install) and
  `claude.cmd` (npm), through `PATHEXT`.
- All subprocess I/O is UTF-8 with `errors="replace"`, independent of the
  console code page.
- PyInstaller: the new modules are found by import analysis, and
  `data/config.toml` is picked up by `collect_data_files("md_maker")`, so
  `packaging/md-maker.spec` needs no change.

### Installers and docs
- `scripts/install-windows.ps1` and `scripts/install-linux.sh` print how to
  install Claude Code and log in once when `claude` is not found.
- README: an "AI requirement" section with Windows notes.

### Tests
- The `fake_claude` fixture in `tests/test_ai.py` creates a `claude.cmd`
  wrapper on Windows, the same path an npm install uses, and a shebang
  script elsewhere. The fake checks that the system prompt arrives intact
  through the file, Persian and newlines included.
- On Linux: 35 passed, 2 skipped. The live test (`MD_MAKER_LIVE=1`) passed
  against the real CLI.

## Known risks / open questions
- **Untested:** the `.cmd` branch of the fake-CLI tests and every real
  `claude` call on Windows.
- If the CLI ever rejects `--system-prompt-file`, older Claude Code
  versions included, every AI call fails. md-maker then falls back to the
  local draft with a warning; it does not crash.
- Claude Code on Windows may need Git Bash for some features. With
  `--tools ""` it should not, but this is unverified.
- On a timeout through `claude.cmd`, `taskkill` should end `node` too. Not
  verified.

## Checklist for a Windows machine

1. `powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1`.
   With `claude` missing, the install note should appear.
2. `claude` once, then `/login`.
3. `uv run pytest` must pass. Check that `test_claude_cli_backend` and
   `test_cli_ai_end_to_end` ran rather than being skipped.
4. `MD_MAKER_LIVE=1 uv run pytest -k live`
5. `md-maker tests\fixtures\persian.pdf --report`: the page should show
   `repair sonnet score ...`, and `persian.report.json` should have
   `"source": "ai"`.
6. Repeat step 5 with an npm install of Claude Code (`claude.cmd`), or set
   `ai.claude_path` to point at it.
7. Timeout: set `[ai] timeout_s = 1` in `md-maker.toml` and convert. Expect
   "no answer after 1s" and the local draft, and no `node.exe` left in Task
   Manager afterwards.
8. Standalone build: `scripts\build-windows.ps1`, then drag a Persian PDF
   onto `dist\md-maker\md-maker.exe`. Expect progress in its console, no
   extra windows, and an `.md` next to the PDF.
9. `md-maker --init-config` writes `%APPDATA%\md-maker\config.toml`, and
   `--show-config` reads it.

When it all passes, update the status line at the top of this file, or
delete the file and note the result in the README.
