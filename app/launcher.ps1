# PDF 解析器啟動程式，由最外層的 run.bat 呼叫，不要直接搬動這個檔案。
#
# 用法（在最外層資料夾）：
#   run.bat                     開啟網頁工具，開啟前會檢查更新
#   run.bat run -t workspace\templates\x.json -i 資料夾
#   run.bat doctor              檢查環境
#   run.bat version             顯示版本
#   run.bat update              安裝資料夾裡的新版 ZIP
#
# 更新方式：從 GitLab Release 下載 pdf-mapper-版本.zip 和 SHA256SUMS.txt，不用解壓，放進這個資料夾，
# 雙擊 run.bat 就會核對檔案並詢問要不要安裝。程式不會連網檢查新版。
#   run.bat rollback            退回上一版（再執行一次就回到新版）
#   加上 --no-update 可以跳過開啟前的新版檢查
#
# 資料夾分工：app\ 是程式，更新時整包換掉；workspace\ 是使用者資料，更新不會動；
# runtime\ 放 uv、Python 和套件，壞掉時可以整個刪掉，下次啟動會重建。
# 全部都在這個資料夾內，不會安裝到系統 Python，也不會改動 PATH。
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$AppDir = $PSScriptRoot
$Root = Split-Path $AppDir -Parent
Set-Location -LiteralPath $Root

$UvVersion = "0.13.6"
# 官方 release 的 .sha256；升級 uv 版本時要一起更新，下載內容不符就不執行
$UvSha256 = @{
    "x86_64"  = "a2a8820d5eea32f08ef467ef3b7f66883a9b076d5737a2fc2fbb5f458d1bb50f"
    "aarch64" = "c2426c0c8e28b53d8c440e47a18d96ad4db51e159866c0e81435b196d7f0081c"
}
$Runtime = Join-Path $Root "runtime"
$uv = Join-Path $Runtime "uv\uv.exe"
$venv = Join-Path $Runtime "venv"
$python = Join-Path $venv "Scripts\python.exe"

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:PDFMAPPER_HOME = $Root          # 程式依這個位置找 workspace
$env:PYTHONPATH = $AppDir
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Runtime "python"
$env:UV_CACHE_DIR = Join-Path $Runtime "cache"
$env:UV_PROJECT_ENVIRONMENT = $venv
$env:UV_SYSTEM_CERTS = "1"           # 使用 Windows 憑證，公司網路的 HTTPS 檢查才不會失敗
$env:UV_PYTHON_PREFERENCE = "only-managed"
$env:UV_NO_PROGRESS = "1"

$rest = @()
$skipUpdate = $false
foreach ($arg in $args) {
    if ($arg -eq "--no-update") { $skipUpdate = $true } else { $rest += $arg }
}
$command = if ($rest.Count -gt 0) { [string]$rest[0] } else { "" }
$interactive = ($command -eq "")    # 雙擊開啟時才暫停顯示錯誤，指令列批次不會卡住

function Stop-WithMessage([string]$message) {
    Write-Host $message -ForegroundColor Red
    if ($interactive) { Read-Host "按 Enter 關閉" | Out-Null }
    exit 1
}

function Get-AppVersion([string]$dir) {
    $file = Join-Path $dir "pyproject.toml"
    if (-not (Test-Path $file)) { return $null }
    $match = Select-String -Path $file -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($match) { return $match.Matches[0].Groups[1].Value }
    return $null
}

function ConvertTo-Version([string]$text) {
    try { return [version]($text.Trim().TrimStart("v")) } catch { return $null }
}

function Rename-WithRetry([string]$path, [string]$newName) {
    # 防毒軟體或檔案總管偶爾會短暫鎖住資料夾，稍等再試
    for ($i = 1; $i -le 5; $i++) {
        try { Rename-Item -LiteralPath $path -NewName $newName; return }
        catch { if ($i -eq 5) { throw } ; Start-Sleep -Seconds 1 }
    }
}

# 把資料夾裡的新版 ZIP 安裝到 app\
function Install-Update([string]$version, [string]$zipPath) {
    $updates = Join-Path $Root "updates"
    Remove-Item -Recurse -Force $updates -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $updates | Out-Null
    $extract = Join-Path $updates "extract"
    Expand-Archive -Path $zipPath -DestinationPath $extract | Out-Null
    $newApp = Get-ChildItem -Path $extract -Directory -Recurse -Depth 2 |
        Where-Object { $_.Name -eq "app" -and (Test-Path (Join-Path $_.FullName "launcher.ps1")) } |
        Select-Object -First 1
    if (-not $newApp) { throw "ZIP 內容不完整，找不到 app 資料夾" }
    if ((Get-AppVersion $newApp.FullName) -ne $version) { throw "ZIP 裡的版本和檔名不符" }

    # 先把舊版改名保留，新版到位後才算完成；中途失敗就換回原狀
    $old = Join-Path $Root "app.old"
    Remove-Item -Recurse -Force $old -ErrorAction SilentlyContinue
    Rename-WithRetry $AppDir "app.old"
    try {
        Move-Item -LiteralPath $newApp.FullName -Destination (Join-Path $Root "app")
    } catch {
        Rename-WithRetry $old "app"
        throw
    }
    foreach ($name in @("run.bat", "run.sh")) {
        $file = Join-Path $newApp.Parent.FullName $name
        if (Test-Path $file) { Copy-Item -Force -LiteralPath $file -Destination (Join-Path $Root $name) }
    }
    Remove-Item -Recurse -Force $updates -ErrorAction SilentlyContinue
    Write-Host "已更新到 $version。上一版保留在 app.old，有問題時執行 run.bat rollback。" -ForegroundColor Green
}

# 找出資料夾裡比目前版本新的 ZIP（從 GitLab Release 下載後放進來的）
function Find-Update([bool]$report) {
    $mine = ConvertTo-Version (Get-AppVersion $AppDir)
    $best = $null
    foreach ($zip in Get-ChildItem -LiteralPath $Root -Filter "pdf-mapper-*.zip" -File) {
        if ($zip.Name -notmatch '^pdf-mapper-(\d+\.\d+\.\d+)\.zip$') { continue }
        $version = ConvertTo-Version $Matches[1]
        if ($mine -and $version -le $mine) {
            Write-Host "資料夾裡的 $($zip.Name) 不比目前版本新，可以刪掉。" -ForegroundColor DarkGray
            continue
        }
        if (-not $best -or $version -gt (ConvertTo-Version $best.version)) {
            $best = @{ version = $Matches[1]; path = $zip.FullName }
        }
    }
    if (-not $best -and $report) {
        Write-Host "沒有找到新版。把 GitLab Release 下載的 pdf-mapper-版本.zip 和 SHA256SUMS.txt 放進這個資料夾，再執行一次。"
    }
    return $best
}

# 核對 ZIP 和 Release 頁上的 SHA256SUMS.txt。擋下載不完整、拿錯檔案，或被改名冒充的 ZIP。
# 瀏覽器重複下載時會變成 SHA256SUMS (1).txt，所以每一份都找。
function Test-UpdateChecksum([string]$zipPath) {
    $name = Split-Path $zipPath -Leaf
    $expected = @()
    foreach ($sums in Get-ChildItem -LiteralPath $Root -Filter "SHA256SUMS*.txt" -File) {
        foreach ($line in Get-Content -LiteralPath $sums.FullName) {
            if ($line -match '^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$' -and $Matches[2] -eq $name) {
                $expected += $Matches[1].ToLower()
            }
        }
    }
    if ($expected.Count -eq 0) {
        throw "找不到 $name 的核對資料。請從同一個 Release 頁下載 SHA256SUMS.txt，和 ZIP 放在一起"
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $zipPath).Hash.ToLower()
    if ($expected -notcontains $actual) {  # 重複下載時有多份核對檔，任一份相符即可
        throw "$name 和 SHA256SUMS.txt 對不上，檔案可能不完整或不是正式發布的版本，請重新下載"
    }
    return $actual
}

# 回傳 $true 代表已經換成新版，要改由新版的啟動程式繼續
function Update-App([bool]$report) {
    $update = Find-Update $report
    if (-not $update) { return $false }
    Write-Host ""
    Write-Host "找到新版本 $($update.version)（目前 $(Get-AppVersion $AppDir)）" -ForegroundColor Cyan
    try {
        $digest = Test-UpdateChecksum $update.path
    } catch {
        Write-Host "不會安裝這個版本：$($_.Exception.Message)" -ForegroundColor Yellow
        return $false
    }
    Write-Host "檔案核對相符（SHA256 $digest）" -ForegroundColor DarkGray
    $answer = Read-Host "要現在更新嗎？範本和匯出資料不會受影響 [Y/n]"
    if ($answer -match '^(n|no|否)$') { return $false }
    try {
        Install-Update $update.version $update.path | Out-Null  # 有些指令會輸出物件，不能混進回傳值
        Remove-Item -LiteralPath $update.path -ErrorAction SilentlyContinue
        return $true
    } catch {
        Remove-Item -Recurse -Force (Join-Path $Root "updates") -ErrorAction SilentlyContinue
        Write-Host "更新失敗，繼續使用目前版本：$($_.Exception.Message)" -ForegroundColor Yellow
        Write-Host "可以照使用手冊「手動更新」的步驟處理。" -ForegroundColor Yellow
        return $false
    }
}

function Invoke-Rollback {
    $old = Join-Path $Root "app.old"
    if (-not (Test-Path (Join-Path $old "launcher.ps1"))) { Stop-WithMessage "找不到上一版（app.old），無法退回。" }
    $from = Get-AppVersion $AppDir
    $to = Get-AppVersion $old
    $temp = "app.swap"
    Remove-Item -Recurse -Force (Join-Path $Root $temp) -ErrorAction SilentlyContinue
    Rename-WithRetry $AppDir $temp
    Rename-WithRetry $old "app"
    Rename-WithRetry (Join-Path $Root $temp) "app.old"
    Write-Host "已從 $from 退回 $to。再執行一次 run.bat rollback 可以回到 $from。" -ForegroundColor Green
}

function Install-Uv {
    Write-Host "第一次使用，正在下載 uv..."
    $arch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "aarch64" } else { "x86_64" }
    $url = "https://github.com/astral-sh/uv/releases/download/$UvVersion/uv-$arch-pc-windows-msvc.zip"
    $temp = Join-Path $Runtime "uv-download"
    New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
    Remove-Item -Recurse -Force $temp -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $temp | Out-Null
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile (Join-Path $temp "uv.zip")
        $actual = (Get-FileHash -Algorithm SHA256 (Join-Path $temp "uv.zip")).Hash.ToLower()
        if ($actual -ne $UvSha256[$arch]) { throw "下載的檔案驗證不符（SHA256 $actual），可能被竄改或下載不完整" }
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

function Move-LegacyRuntime {
    # 0.1 版把 uv 和 Python 放在 .tools，搬過來就不用重新下載
    $legacy = Join-Path $Root ".tools"
    if ((Test-Path $uv) -or -not (Test-Path (Join-Path $legacy "uv\uv.exe"))) { return }
    New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
    foreach ($name in @("uv", "python")) {
        $from = Join-Path $legacy $name
        if ((Test-Path $from) -and -not (Test-Path (Join-Path $Runtime $name))) { Move-Item $from (Join-Path $Runtime $name) }
    }
    Write-Host "已沿用舊版下載的 uv 與 Python。確認新版正常後，可以刪除 .tools 和 .venv。"
}

function Initialize-Environment {
    Move-LegacyRuntime
    if (-not (Test-Path $uv)) { Install-Uv }
    $ErrorActionPreference = "Continue"  # uv 把進度寫到 stderr，不能當成錯誤
    if (Test-Path $python) {
        & $python -c "pass" 2>$null
        if ($LASTEXITCODE -ne 0) { Remove-Item -Recurse -Force $venv -ErrorAction SilentlyContinue }  # 資料夾搬過位置
    }
    if (-not (Test-Path $python)) { Write-Host "正在準備 Python 與套件，第一次約需 1 到 3 分鐘..." }

    $wheels = Join-Path $AppDir "wheels"
    if (Test-Path (Join-Path $wheels "requirements.txt")) {
        # 發布包附帶套件檔，不需要連到 PyPI；sync 會讓環境和清單完全一致，舊版多出的套件也會移除
        if (-not (Test-Path $python)) {
            $version = (Get-Content (Join-Path $AppDir ".python-version") | Select-Object -First 1).Trim()
            & $uv venv --clear --python $version $venv
        }
        if ($LASTEXITCODE -eq 0) {
            $env:UV_OFFLINE = "1"
            & $uv pip sync --python $python --no-index --find-links $wheels (Join-Path $wheels "requirements.txt")
            Remove-Item Env:\UV_OFFLINE
        }
    } else {
        # 開發時沒有 wheels，從 PyPI 安裝；環境已經正確時會在一瞬間結束
        & $uv sync --frozen --no-dev --project $AppDir
    }
    if ($LASTEXITCODE -ne 0) {
        Stop-WithMessage "環境建立失敗。請確認網路，或參考使用手冊的離線安裝。"
    }
}

switch ($command) {
    "version" { Write-Host (Get-AppVersion $AppDir); exit 0 }
    "rollback" { Invoke-Rollback; exit 0 }
    "update" {
        if ((Update-App $true) -eq $true) { Write-Host "下次執行 run.bat 就會使用新版。" }
        exit 0
    }
}

if ($interactive -and -not $skipUpdate) {
    if ((Update-App $false) -eq $true) {
        # 改由新版的啟動程式繼續，套件更新也由新版處理
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "app\launcher.ps1") --no-update @rest
        exit $LASTEXITCODE
    }
}

Initialize-Environment
# -P：不把目前資料夾加進模組搜尋路徑，資料夾裡的同名 .py 不會被誤載入
& $python -P -m pdfmapper @rest
$code = $LASTEXITCODE
if ($code -ne 0 -and $interactive) { Read-Host "按 Enter 關閉" | Out-Null }
exit $code
