# PDF 解析器啟動腳本。第一次執行會自動建立環境，之後直接開啟。
# 用法：.\start.ps1            開啟網頁工具
#      .\start.ps1 run -t templates\x.json -i pdfs -o output\x.xlsx
#
# 環境由 uv 建立，uv、Python 和所有套件都放在這個資料夾內，
# 不會安裝到系統 Python，也不會改動 PATH。刪掉資料夾就完全移除。
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
Set-Location -LiteralPath $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$UvVersion = "0.13.6"
$tools = Join-Path $PSScriptRoot ".tools"
$uv = Join-Path $tools "uv\uv.exe"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

$env:UV_PYTHON_INSTALL_DIR = Join-Path $tools "python"
$env:UV_CACHE_DIR = Join-Path $tools "cache"
$env:UV_SYSTEM_CERTS = "1"          # 使用 Windows 憑證，公司網路的 HTTPS 檢查才不會失敗
$env:UV_PYTHON_PREFERENCE = "only-managed"
$env:UV_NO_PROGRESS = "1"

function Stop-WithMessage([string]$message) {
    Write-Host $message -ForegroundColor Red
    exit 1
}

function Install-Uv {
    Write-Host "第一次使用，正在下載 uv..."
    $arch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "aarch64" } else { "x86_64" }
    $url = "https://github.com/astral-sh/uv/releases/download/$UvVersion/uv-$arch-pc-windows-msvc.zip"
    $temp = Join-Path $tools "uv-download"
    New-Item -ItemType Directory -Force -Path $tools | Out-Null
    Remove-Item -Recurse -Force $temp -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $temp | Out-Null
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile (Join-Path $temp "uv.zip")
        Expand-Archive -Path (Join-Path $temp "uv.zip") -DestinationPath (Join-Path $temp "uv")
    } catch {
        Remove-Item -Recurse -Force $temp -ErrorAction SilentlyContinue
        Stop-WithMessage "無法下載 uv：$($_.Exception.Message)`n公司網路擋 GitHub 時，請參考使用手冊的離線安裝。"
    }
    # 解壓完成才移到正式位置，下載中斷時下次會重來
    Remove-Item -Recurse -Force (Split-Path $uv) -ErrorAction SilentlyContinue
    Move-Item (Join-Path $temp "uv") (Split-Path $uv)
    Remove-Item -Recurse -Force $temp -ErrorAction SilentlyContinue
}

if (-not (Test-Path $uv)) { Install-Uv }

$ErrorActionPreference = "Continue"  # uv 把進度寫到 stderr，不能當成錯誤
if (-not (Test-Path $python)) { Write-Host "正在準備 Python 與套件，第一次約需 1 到 3 分鐘..." }

$wheels = Join-Path $PSScriptRoot "wheels"
if (Test-Path $wheels) {
    # 離線安裝：Python 和套件都來自複製過來的檔案，不連網
    $env:UV_OFFLINE = "1"
    $usable = $false
    if (Test-Path $python) {
        & $python -c "pass" 2>$null
        $usable = ($LASTEXITCODE -eq 0)
    }
    if (-not $usable) { & $uv venv --clear .venv }
    if ($LASTEXITCODE -eq 0) {
        & $uv pip install --python $python --no-index --find-links $wheels -r (Join-Path $wheels "requirements.txt")
    }
} else {
    # 環境已經正確時，這一步會在一瞬間結束，也不需要連網
    & $uv sync --frozen --no-dev
}
if ($LASTEXITCODE -ne 0) {
    Stop-WithMessage "環境建立失敗。請確認網路，或參考使用手冊的離線安裝。"
}

& $python -m pdfmapper @args
exit $LASTEXITCODE
