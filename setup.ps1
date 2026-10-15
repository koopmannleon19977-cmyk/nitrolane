# nitrolane setup: download the pinned arc-cua-windows archive, apply local patches, build the venv, verify.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Vendor = Join-Path $Root "vendor\arc-cua-windows"
$Commit = "659696da0134ae4946a40da76fc0ca6d56f292b7"

if (-not (Test-Path $Vendor)) {
    $Zip = Join-Path $env:TEMP "arc-cua-windows-$Commit.zip"
    Invoke-WebRequest "https://github.com/GreenKeewi/arc-cua-windows/archive/$Commit.zip" -OutFile $Zip
    Expand-Archive $Zip -DestinationPath (Join-Path $Root "vendor") -Force
    Move-Item (Join-Path $Root "vendor\arc-cua-windows-$Commit") $Vendor
    git -C $Vendor init -q
    git -C $Vendor apply (Join-Path $Root "patches\arc-cua-windows-local.patch")
    Copy-Item (Join-Path $Root "patches\LOCAL_PATCHES.md") (Join-Path $Vendor "LOCAL_PATCHES.md")
}
$Py = Join-Path $Vendor ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    python -m venv (Join-Path $Vendor ".venv")
    & $Py -m pip install -e "$Vendor[windows,browser]" pytest
}
& $Py -m arc_cua windows-smoke
& $Py -m pytest (Join-Path $Vendor "tests") -q -p no:cacheprovider --basetemp (Join-Path $Vendor ".pytest-tmp")
Write-Host "OK. Set TYPESAFE_API_KEY in your user environment, then run nitrolane.py (see README)."
