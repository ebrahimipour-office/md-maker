"""Backend that runs the user's installed Claude Code CLI (`claude -p`).

Each call is a fresh, tool-less, single-turn session: the page image goes in
as an image block over stream-json, and --json-schema makes the answer come
back as structured output. The CLI uses whatever login the user has
(subscription or API key), so md-maker never handles credentials.

Windows: an npm install runs as `claude.cmd`, and cmd.exe mangles arguments
holding newlines or & | < > ^ % !. So everything free-form (system prompt,
page text) goes through a file or stdin, never the command line.
"""

import base64
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .backend import AIError, AIResult
from .prompts import SCHEMA

_CMD_UNSAFE = set("\r\n&|<>^%!")


def find_claude(configured: str = "") -> str | None:
    if configured:
        return shutil.which(configured) or None
    return shutil.which("claude")


class ClaudeCLI:
    def __init__(self, settings):
        self.path = find_claude(settings.ai.claude_path)
        if not self.path:
            where = settings.ai.claude_path or "`claude` on PATH"
            raise AIError(f"Claude CLI not found ({where}); install Claude Code or set ai.claude_path")
        self.timeout = settings.ai.timeout_s
        # An empty working folder keeps project CLAUDE.md files and settings
        # out of the model's context.
        self._tmp = tempfile.TemporaryDirectory(prefix="md-maker-")
        self.cwd = self._tmp.name

    def _system_file(self, system: str) -> str:
        path = Path(self.cwd) / f"system-{hashlib.sha256(system.encode()).hexdigest()[:16]}.txt"
        if not path.exists():
            path.write_text(system, encoding="utf-8")
        return str(path)

    def _command(self, model, effort, system, budget_usd):
        cmd = [
            self.path, "-p",
            "--model", model,
            "--input-format", "stream-json",
            "--output-format", "stream-json", "--verbose",
            "--json-schema", SCHEMA,
            "--system-prompt-file", self._system_file(system),
            "--tools", "",
            "--no-session-persistence",
            "--disable-slash-commands",
            "--strict-mcp-config",
        ]
        if effort:
            cmd += ["--effort", effort]
        if budget_usd:
            cmd += ["--max-budget-usd", f"{budget_usd:.4f}"]
        if any(_CMD_UNSAFE & set(arg) for arg in cmd[1:]):
            raise AIError("internal: command-line argument not safe for Windows cmd.exe")
        return cmd

    def run(self, *, model, effort, system, prompt, image=None, budget_usd=None) -> AIResult:
        content = []
        if image:
            data = base64.b64encode(image).decode()
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}})
        content.append({"type": "text", "text": prompt})
        message = json.dumps({"type": "user", "message": {"role": "user", "content": content}})

        last = None
        for _ in range(2):  # one retry for transient failures
            try:
                return self._once(model, effort, system, budget_usd, message)
            except AIError as e:
                last = e
                if "budget" in str(e):
                    break
        raise last

    def _once(self, model, effort, system, budget_usd, message) -> AIResult:
        proc = subprocess.Popen(
            self._command(model, effort, system, budget_usd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=self.cwd,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            stdout, stderr = proc.communicate(message + "\n", timeout=self.timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            raise AIError(f"{model}: no answer after {self.timeout}s") from None
        result = None
        for line in stdout.splitlines():
            if line.startswith("{") and '"type":"result"' in line.replace(" ", ""):
                try:
                    result = json.loads(line)
                except json.JSONDecodeError:
                    pass
        if result is None:
            err = (stderr or stdout).strip().splitlines()
            raise AIError(f"{model}: CLI exited with {proc.returncode}: {err[-1] if err else 'no output'}")
        out = result.get("structured_output")
        if result.get("is_error") or not isinstance(out, dict) or "markdown" not in out:
            reason = result.get("subtype", "error")
            if "budget" in reason:
                raise AIError(f"{model}: budget reached")
            raise AIError(f"{model}: {reason}: {str(result.get('result', ''))[:200]}")
        return AIResult(
            markdown=out["markdown"],
            confidence=out.get("confidence", "medium"),
            notes=out.get("notes", ""),
            cost_usd=float(result.get("total_cost_usd") or 0),
            model=model,
        )


def _kill_tree(proc: subprocess.Popen):
    """Stop the CLI and its children (on Windows, claude.cmd starts node)."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    proc.kill()
    proc.communicate()
