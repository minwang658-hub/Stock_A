param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
Set-Location $repoRoot

$SystemPython = "C:/Users/michwang/AppData/Local/Programs/Python/Python312/python.exe"

function Test-PythonApiRuntime {
    param(
        [string]$PythonExe
    )

    if (-not $PythonExe -or -not (Test-Path $PythonExe)) {
        return $false
    }

    $check = & $PythonExe -c "import fastapi, uvicorn, pandas, tushare; print('ok')" 2>$null
    return $LASTEXITCODE -eq 0
}

function Get-ApiPython {
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-PythonApiRuntime -PythonExe $venvPython) {
        return $venvPython
    }
    if (Test-PythonApiRuntime -PythonExe $SystemPython) {
        return $SystemPython
    }
    return "python"
}

function Test-ApiRunning {
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 2
        return [bool]($resp.ok -eq $true)
    }
    catch {
        return $false
    }
}

function Start-ApiIfNeeded {
    if (Test-ApiRunning) {
        Write-Host "API already running at http://127.0.0.1:8765"
        return
    }

    $pythonExe = Get-ApiPython

    $apiScript = Join-Path $repoRoot "scripts\local_stock_api.py"
    Start-Process -FilePath $pythonExe -ArgumentList $apiScript -WorkingDirectory $repoRoot | Out-Null
    Write-Host "API start requested: $pythonExe $apiScript"
}

function Open-Dashboard {
    $reportsDir = Join-Path $repoRoot "reports"
    $htmlFiles = Get-ChildItem -Path $reportsDir -File -Filter "*.html" | Sort-Object LastWriteTime -Descending
    $candidate = $htmlFiles |
        Where-Object { $_.Name -like "*可视化分析*" } |
        Select-Object -First 1

    if ($null -eq $candidate) {
        $candidate = $htmlFiles | Select-Object -First 1
    }

    if ($null -eq $candidate) {
        throw "No dashboard html found under reports/*.html"
    }

    Start-Process -FilePath $candidate.FullName | Out-Null
    Write-Host "Opened dashboard: $($candidate.FullName)"
}

Start-ApiIfNeeded

if (-not $NoBrowser) {
    Open-Dashboard
}

Write-Host "Done."
