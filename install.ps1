# nitrolane one-command install (Windows): clone, set up, doctor.
#   irm https://raw.githubusercontent.com/koopmannleon19977-cmyk/nitrolane/main/install.ps1 | iex
param([string]$Dir = "$HOME\nitrolane", [string]$Repo = "https://github.com/koopmannleon19977-cmyk/nitrolane.git")
$ErrorActionPreference = "Stop"
if (Test-Path $Dir) {
    git -C $Dir pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw "git pull failed in $Dir" }
} else {
    git clone $Repo $Dir
    if ($LASTEXITCODE -ne 0) { throw "git clone failed" }
}
& (Join-Path $Dir "setup.ps1")
# --deep sends one real decision, so a wrong key or endpoint fails here, not on the first task.
& (Join-Path $Dir "vendor\arc-cua-windows\.venv\Scripts\python.exe") (Join-Path $Dir "nitrolane.py") doctor --deep
if ($LASTEXITCODE -ne 0) { throw "nitrolane doctor --deep failed (see the JSON above); fix it and re-run install.ps1" }
if (-not (Get-Command cua-driver -ErrorAction SilentlyContinue)) {
    Write-Host "Optional: install cua-driver (https://github.com/trycua/cua) for background desktop control without focus changes."
}
Write-Host "Installed to $Dir. Quickstart: see $Dir\README.md."
