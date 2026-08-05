param(
    [string]$ProjectRoot = "",
    [string]$PythonExe = "",
    [string]$DbPath = "data/memory.db",
    [string]$SchemaPath = "storage/schema.sql",
    [ValidateSet("conservative", "balanced", "aggressive")]
    [string]$Preset = "balanced",
    [string]$OutputPath = "data/revision_rule_overrides.auto.json",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}

$resolvedRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path

if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    $venvPython = Join-Path $resolvedRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        $PythonExe = $venvPython
    } else {
        $PythonExe = "python"
    }
}

$logDir = Join-Path $resolvedRoot "logs"
if (-not (Test-Path -LiteralPath $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}
$logPath = Join-Path $logDir "revision_rule_apply.log"

$args = @(
    "tools/revision_rule_apply_overrides.py",
    "--db", $DbPath,
    "--schema", $SchemaPath,
    "--preset", $Preset,
    "--output", $OutputPath
)
if ($DryRun) {
    $args += "--dry-run"
}

Push-Location $resolvedRoot
try {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $logPath -Value "[$timestamp] start revision override job"
    $commandLine = "$PythonExe $($args -join ' ')"
    Add-Content -LiteralPath $logPath -Value "[$timestamp] cmd: $commandLine"
    if ($DryRun) {
        Write-Host "[DryRun] $commandLine"
        Add-Content -LiteralPath $logPath -Value "[$timestamp] dry-run skipped execution"
        exit 0
    }
    & $PythonExe @args 2>&1 | Tee-Object -FilePath $logPath -Append
    $exitCode = $LASTEXITCODE
    $done = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $logPath -Value "[$done] done exit_code=$exitCode"
    if ($exitCode -ne 0) {
        exit $exitCode
    }
} finally {
    Pop-Location
}
