[CmdletBinding()]
param(
    [switch]$Install,
    [ValidateSet('all', 'frontend', 'backend')]
    [string]$Target = 'all'
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$backend = Join-Path $projectRoot 'backend'
$frontend = Join-Path $projectRoot 'frontend'

# ネイティブexeの失敗は $ErrorActionPreference では止まらないため、明示的に終了コードを見る
function Invoke-Step {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][scriptblock]$Action
    )

    Write-Host ''
    Write-Host "==> $Name" -ForegroundColor Cyan
    Push-Location $WorkingDirectory
    try {
        # 前のコマンドの終了コードが残っていると誤判定するため、毎回リセットする
        $global:LASTEXITCODE = 0
        & $Action
        if ($LASTEXITCODE -ne 0) {
            throw "$Name に失敗しました (exit code $LASTEXITCODE)"
        }
    }
    finally {
        Pop-Location
    }
}

function Build-Backend {
    if (-not (Get-Command poetry -ErrorAction SilentlyContinue)) {
        throw 'Poetry が見つかりません。Poetryをインストールしてから再実行してください。'
    }

    if ($Install) {
        Invoke-Step -Name 'backend: poetry install' -WorkingDirectory $backend -Action { poetry install }
    }

    # 構文エラーと import 崩れをここで落とす（起動しないと気づけない事故を防ぐ）
    Invoke-Step -Name 'backend: import check' -WorkingDirectory $backend -Action {
        poetry run python -c 'import app.main'
    }
}

# node_modules の有無だけで判断すると、package.json に依存を足しても導入されず
# 「型定義が無い」等で後段のビルドが落ちる。導入済み内容より package.json が新しければ入れ直す。
function Test-NpmInstallNeeded {
    $nodeModules = Join-Path $frontend 'node_modules'
    if (-not (Test-Path $nodeModules)) {
        return $true
    }

    # SMB共有(Mac)上ではドットファイルに隠し属性が付き、-Force なしの Get-Item では読めない。
    # 判定できないときは入れ直す側に倒す（install は冪等なので、余計に走っても害はない）。
    $marker = Join-Path $nodeModules '.package-lock.json'
    $packageJson = Join-Path $frontend 'package.json'
    try {
        $markerItem = Get-Item -Force -LiteralPath $marker -ErrorAction Stop
        $packageItem = Get-Item -Force -LiteralPath $packageJson -ErrorAction Stop
    }
    catch {
        return $true
    }

    return $packageItem.LastWriteTimeUtc -gt $markerItem.LastWriteTimeUtc
}

function Build-Frontend {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw 'npm が見つかりません。Node.jsをインストールしてから再実行してください。'
    }

    if ($Install -or (Test-NpmInstallNeeded)) {
        Invoke-Step -Name 'frontend: npm install' -WorkingDirectory $frontend -Action { npm install }
    }

    # npm run build = tsc -b && vite build。型チェックはここでしか走らない（npm run dev は素通し）
    Invoke-Step -Name 'frontend: npm run build' -WorkingDirectory $frontend -Action { npm run build }
}

if ($Target -in @('all', 'backend')) {
    Build-Backend
}
if ($Target -in @('all', 'frontend')) {
    Build-Frontend
}

Write-Host ''
Write-Host 'ビルドが完了しました。' -ForegroundColor Green
