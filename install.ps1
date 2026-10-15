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
& (Join-Path $Dir "vendor\arc-cua-windows\.venv\Scripts\python.exe") (Join-Path $Dir "nitrolane.py") doctor
Write-Host "Installed to $Dir. Quickstart: see $Dir\README.md (a TYPESAFE_API_KEY is required for the default provider)."
