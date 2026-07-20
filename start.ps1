$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    Write-Error "Python環境がありません。先に setup.ps1 を実行してください。"
}

Set-Location -LiteralPath $PSScriptRoot
& $python manage.py migrate
Write-Host ""
Write-Host "当直表作成アプリを起動しました。"
Write-Host "PC: http://127.0.0.1:8000/"
Write-Host "スマートフォン: http://<このPCのIPアドレス>:8000/"
Write-Host "終了するには Ctrl+C を押してください。"
& $python manage.py runserver 0.0.0.0:8000
