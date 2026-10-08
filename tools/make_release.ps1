# Build the Windows binary and pack a release zip for GitHub Releases.
# Pure ASCII on purpose: Windows PowerShell 5.1 reads a UTF-8 .ps1 without a BOM as ANSI.
param(
    [string]$Version = "0.1.0",
    [string]$Name = "KenoBOT"
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
Set-Location $root

$exe = Join-Path $root "dist\$Name.exe"
if (-not (Test-Path $exe)) {
    Write-Host "building $Name.exe ..."
    powershell -ExecutionPolicy Bypass -File (Join-Path $root "build_exe.ps1")
}
if (-not (Test-Path $exe)) { throw "build failed: $exe missing" }

$stage = Join-Path $root "dist\_stage"
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force -Path $stage | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $stage "docs") | Out-Null

Copy-Item $exe $stage
foreach ($f in "README.md", "LICENSE", "CONTRIBUTING.md") {
    if (Test-Path (Join-Path $root $f)) { Copy-Item (Join-Path $root $f) $stage }
}
# Launchers by wildcard: the repo ships a Chinese-named .bat, and this script stays ASCII.
Get-ChildItem (Join-Path $root "*.bat") -File | ForEach-Object { Copy-Item $_.FullName $stage }
Copy-Item (Join-Path $root "docs\*.md") (Join-Path $stage "docs")
Copy-Item (Join-Path $root "docs\QUICKSTART_zh.txt") (Join-Path $stage "docs")
if (Test-Path (Join-Path $root "README.zh-CN.md")) { Copy-Item (Join-Path $root "README.zh-CN.md") $stage }
if (Test-Path (Join-Path $root "docs\images")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $stage "docs\images") | Out-Null
    Copy-Item (Join-Path $root "docs\images\*.png") (Join-Path $stage "docs\images")
}

"Keno BOT $Version (Windows x64)" | Set-Content -Encoding ASCII (Join-Path $stage "VERSION.txt")
"Run: " + $Name + ".exe   (state dir: %LOCALAPPDATA%\KenoBOT, override with KENO_BOT_HOME)" |
    Add-Content -Encoding ASCII (Join-Path $stage "VERSION.txt")

$zip = Join-Path $root "dist\$Name-$Version-win64.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -Force
Remove-Item -Recurse -Force $stage

$hash = (Get-FileHash $zip -Algorithm SHA256).Hash
Write-Host ("release: {0} ({1:N0} bytes)" -f $zip, (Get-Item $zip).Length)
Write-Host ("sha256 : {0}" -f $hash)
Get-ChildItem $stage -ErrorAction SilentlyContinue | Out-Null
