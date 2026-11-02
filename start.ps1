# PDF 解析器啟動腳本。第一次執行會自動建立環境，之後直接開啟。
# 用法：.\start.ps1            開啟網頁工具
#      .\start.ps1 run -t templates\x.json -i pdfs -o output\x.xlsx
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

function Find-Python {
    foreach ($candidate in @(@("py", "-3"), @("python"), @("python3"))) {
        $exe = $candidate[0]
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        $prefix = @($candidate | Select-Object -Skip 1)
        try {
            $ok = & $exe @prefix -c "import sys; print(int(sys.version_info >= (3, 10)))" 2>$null
            if ($ok -eq "1") { return ,$candidate }
        } catch { continue }
    }
    return $null
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$stamp = Join-Path $PSScriptRoot ".venv\.installed"
$requirements = Join-Path $PSScriptRoot "requirements.txt"

$needsInstall = -not (Test-Path $stamp)
if (-not $needsInstall) {
    $needsInstall = (Get-Item $requirements).LastWriteTime -gt (Get-Item -Force $stamp).LastWriteTime
}

if ($needsInstall) {
    if (-not (Test-Path $venvPython)) {
        $python = Find-Python
        if ($null -eq $python) {
            Write-Host "找不到 Python 3.10 以上版本。請到 https://www.python.org/downloads/ 安裝，安裝時勾選 Add python.exe to PATH。" -ForegroundColor Red
            exit 1
        }
        Write-Host "第一次使用，正在建立環境..."
        $exe = $python[0]
        $prefix = @($python | Select-Object -Skip 1)
        & $exe @prefix -m venv .venv
        if ($LASTEXITCODE -ne 0) { Write-Host "建立環境失敗。" -ForegroundColor Red; exit 1 }
    }
    Write-Host "正在安裝套件，約需 1 到 3 分鐘..."
    $wheels = Join-Path $PSScriptRoot "wheels"
    if (Test-Path $wheels) {
        & $venvPython -m pip install --quiet --no-index --find-links $wheels -r $requirements
    } else {
        & $venvPython -m pip install --quiet --disable-pip-version-check -r $requirements
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "安裝失敗。公司網路擋 pip 時，請參考 README 的離線安裝。" -ForegroundColor Red
        exit 1
    }
    New-Item -ItemType File -Path $stamp -Force | Out-Null
}

& $venvPython -m pdfmapper @args
exit $LASTEXITCODE
