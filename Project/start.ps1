[CmdletBinding()]
param(
    [switch]$Install
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$backend = Join-Path $projectRoot 'backend'
$frontend = Join-Path $projectRoot 'frontend'

if (-not (Get-Command poetry -ErrorAction SilentlyContinue)) {
    throw 'Poetry が見つかりません。Poetryをインストールしてから再実行してください。'
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw 'npm が見つかりません。Node.jsをインストールしてから再実行してください。'
}

if ($Install) {
    Push-Location $backend
    try { poetry install } finally { Pop-Location }
    Push-Location $frontend
    try { npm install } finally { Pop-Location }
} elseif (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    throw 'フロントエンド依存関係が未導入です。初回のみ .\start.ps1 -Install を実行してください。'
}

$backendCommand = "Set-Location '$backend'; poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000"
$frontendCommand = "Set-Location '$frontend'; npm run dev"

Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoProfile', '-Command', $backendCommand
Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoProfile', '-Command', $frontendCommand

Write-Host 'BCMan を起動しました。'
Write-Host '  Frontend: http://localhost:5173/bcman/'
Write-Host '  API:      http://localhost:8000/bcman/api/health'
