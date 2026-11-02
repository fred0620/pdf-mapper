# 在可連網、且作業系統與 Python 版本相同的電腦上執行，產生 wheels 資料夾。
# 把整個專案連同 wheels 複製到不能連網的電腦後，start.bat 會自動改用離線安裝。
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Split-Path $PSScriptRoot -Parent)
python -m pip download -r requirements.txt -d wheels
if ($LASTEXITCODE -ne 0) { exit 1 }
Write-Host "完成，請把整個專案資料夾複製到目標電腦。"
