# Build dist/KenoBOT.exe (single file, console build so the log stays visible).
#
#   powershell -ExecutionPolicy Bypass -File build_exe.ps1
#
# Requires: python on PATH, and PyInstaller (installed automatically if missing).
param(
    [string]$Name = "KenoBOT",
    [switch]$Onedir
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "installing PyInstaller ..."
    python -m pip install --upgrade pyinstaller
}

if (-not (Test-Path "assets\icon.ico")) {
    python tools/make_icon.py
}
if (-not (Test-Path "data\samples\rounds_sample.jsonl")) {
    python tools/make_sample.py
}

Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

$mode = if ($Onedir) { "--onedir" } else { "--onefile" }
$args = @(
    "-m", "PyInstaller",
    "--noconfirm", "--clean", $mode,
    "--name", $Name,
    "--paths", "src",
    "--icon", "assets\icon.ico",
    "--add-data", "configs;configs",
    "--add-data", "data\reference;data/reference",
    "--add-data", "data\samples;data/samples",
    "--add-data", "src\keno\webapp\static;keno/webapp/static",
    "--collect-submodules", "keno",
    "--hidden-import", "websockets.legacy",
    "keno_bot_app.py"
)
python @args

Write-Host ""
Write-Host "built: $root\dist\$Name.exe"
Write-Host "first run writes state to %LOCALAPPDATA%\KenoBOT (override with KENO_BOT_HOME)"
