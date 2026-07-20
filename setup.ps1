$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$pythonCommand = Get-Command py -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
}
if (-not $pythonCommand) {
    Write-Error "Python 3.12以降をインストールしてから再実行してください。"
}

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    & $pythonCommand.Source -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
& ".\.venv\Scripts\python.exe" manage.py migrate
Write-Host "準備が完了しました。次に .\start.ps1 を実行してください。"
