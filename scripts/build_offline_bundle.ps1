# 在可連網的電腦上執行，準備給不能連網的電腦使用的檔案。
# 來源與目標電腦要是相同的作業系統和 CPU 架構，都不需要先安裝 Python。
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root

& (Join-Path $root "start.ps1") doctor
if ($LASTEXITCODE -ne 0) { exit 1 }

$env:UV_PYTHON_INSTALL_DIR = Join-Path $root ".tools\python"
$env:UV_CACHE_DIR = Join-Path $root ".tools\cache"
$env:UV_SYSTEM_CERTS = "1"
$env:UV_PYTHON_PREFERENCE = "only-managed"
$uv = Join-Path $root ".tools\uv\uv.exe"
$wheels = Join-Path $root "wheels"
New-Item -ItemType Directory -Force -Path $wheels | Out-Null
$list = Join-Path $wheels "requirements.txt"

& $uv export --frozen --no-dev --no-hashes --no-emit-project --output-file $list --quiet
if ($LASTEXITCODE -ne 0) { exit 1 }
& $uv run --no-project --with pip python -m pip download --quiet -r $list -d $wheels
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "完成。把整個資料夾複製到目標電腦，但不要複製 .venv 和 .tools\cache。"
