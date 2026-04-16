param(
    [string]$ProjectRoot = "",
    [string]$TaskName = "MACHI-MK5-RevisionRuleOverride",
    [string]$DailyTime = "03:30",
    [int]$RepeatMinutes = 0,
    [ValidateSet("conservative", "balanced", "aggressive")]
    [string]$Preset = "balanced",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$resolvedRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$runnerScript = Join-Path $resolvedRoot "tools\run_revision_rule_override_job.ps1"

if (-not (Test-Path -LiteralPath $runnerScript)) {
    throw "Runner script not found: $runnerScript"
}

$taskCommand = "powershell.exe"
$taskArg = "-NoProfile -ExecutionPolicy Bypass -File `"$runnerScript`" -ProjectRoot `"$resolvedRoot`" -Preset $Preset"

if ($RepeatMinutes -gt 0) {
    $scheduleArgs = @(
        "/Create",
        "/F",
        "/SC", "MINUTE",
        "/MO", "$RepeatMinutes",
        "/TN", $TaskName,
        "/TR", "$taskCommand $taskArg"
    )
} else {
    $scheduleArgs = @(
        "/Create",
        "/F",
        "/SC", "DAILY",
        "/ST", $DailyTime,
        "/TN", $TaskName,
        "/TR", "$taskCommand $taskArg"
    )
}

$preview = "schtasks " + ($scheduleArgs -join " ")
Write-Host "[Preview] $preview"

if ($DryRun) {
    Write-Host "[DryRun] task registration skipped."
    exit 0
}

& schtasks @scheduleArgs
if ($LASTEXITCODE -ne 0) {
    throw "Task registration failed with exit code $LASTEXITCODE"
}

Write-Host "Task registered: $TaskName"
Write-Host "Run now: schtasks /Run /TN `"$TaskName`""
