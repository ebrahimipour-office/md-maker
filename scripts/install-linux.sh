#!/usr/bin/env bash
# Install md-maker on Linux from this source folder: the `md-maker` command,
# Persian + English OCR data, and the Claude Code skill.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"

if ! command -v uv >/dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

uv tool install --force --editable "$repo"
"$(uv tool dir --bin)/md-maker" --install-ocr

mkdir -p "$HOME/.claude/skills"
cp -r "$repo/skill/md-maker" "$HOME/.claude/skills/"

echo
echo "Done. Run:  md-maker <file.pdf|file.docx>"
