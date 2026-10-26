# Install md-maker on Windows from this source folder.
#   powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1
#
# - installs uv (Python tool manager) if missing
# - installs the `md-maker` command (uv also fetches Python if needed)
# - downloads Persian + English OCR data
# - installs the Claude Code skill into %USERPROFILE%\.claude\skills
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv..."
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

uv tool install --force --editable $repo
uv tool update-shell  # put uv's tool folder on PATH for new terminals

$exe = Join-Path (uv tool dir --bin) "md-maker.exe"
& $exe --install-ocr

$skills = Join-Path $env:USERPROFILE ".claude\skills"
New-Item -ItemType Directory -Force -Path $skills | Out-Null
Copy-Item -Recurse -Force (Join-Path $repo "skill\md-maker") $skills

Write-Host ""
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Host "Claude Code (claude) was not found, so md-maker will convert locally only."
    Write-Host "For AI repair of hard PDF pages, install it and log in once:"
    Write-Host "    irm https://claude.ai/install.ps1 | iex"
    Write-Host "    claude          (then /login)"
    Write-Host ""
}
Write-Host "Done. Open a new terminal and run:  md-maker <file.pdf|file.docx>"
