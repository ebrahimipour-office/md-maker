# Build a standalone md-maker for Windows: a folder with md-maker.exe (CLI) and
# md-maker-gui.exe (double-click GUI) that runs on any Windows 10/11 PC
# without Python, OCR data included.
#   powershell -ExecutionPolicy Bypass -File scripts\build-windows.ps1
#
# Output: dist\md-maker\md-maker[-gui].exe and dist\md-maker-windows-amd64.zip
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv..."
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

Push-Location $repo
try {
    uv sync
    uv run --with pyinstaller python scripts\build.py
} finally {
    Pop-Location
}
