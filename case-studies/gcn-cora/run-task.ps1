<#
Run one Windows-friendly GCN/Cora reproduction profile.

This wrapper discovers Python and Docker, maps the selected profile to its
strict task file, and preserves the CLI exit-code contract. Scientific inputs
and tolerances remain in task-smoke.json/task-full.json, not in this script.
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("smoke", "full")]
    [string]$Mode
)

# Resolve every path from the script location so double-clicking and terminal
# execution behave identically regardless of the caller's current directory.
$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$bundledPython = Join-Path $env:USERPROFILE `
    ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

# Prefer Codex's bundled interpreter; fall back to a user-installed Python.
if (Test-Path -LiteralPath $bundledPython) {
    $pythonExecutable = $bundledPython
} else {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        throw "Python 3.11+ was not found. Install Python, then run this file again."
    }
    $pythonExecutable = $pythonCommand.Source
}

# Check both the Docker client and daemon before starting a long reproduction.
$dockerCommand = Get-Command docker.exe -ErrorAction SilentlyContinue
if ($null -eq $dockerCommand) {
    throw "Docker Desktop was not found. Install Docker Desktop first."
}
# Docker may print a harmless daemon warning on stderr. Temporarily avoid
# promoting native stderr to a PowerShell exception, then trust its exit code.
$previousErrorPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $dockerCommand.Source info 1> $null 2> $null
$dockerExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorPreference
if ($dockerExitCode -ne 0) {
    throw "Docker Desktop is installed but not running. Start it and try again."
}

# The two profiles share code and data; only the registered task changes.
$taskPath = Join-Path $projectRoot "case-studies\gcn-cora\task-$Mode.json"
$runDirectory = Join-Path $projectRoot "runs\gcn-cora-$Mode"
$env:PYTHONPATH = Join-Path $projectRoot "src"

Write-Host "Running GCN Cora $Mode reproduction..." -ForegroundColor Cyan
Write-Host "Task: $taskPath"
Write-Host "Evidence directory: $runDirectory"

Push-Location $projectRoot
try {
    & $pythonExecutable -m reproagent_lite run $taskPath --run-dir $runDirectory
    $reproductionExitCode = $LASTEXITCODE
    # Exit 1 is a setup/runtime error. Any other non-zero value means execution
    # completed but the scientific verdict was FAIL or INCONCLUSIVE.
    if ($reproductionExitCode -eq 1) {
        throw "Reproduction setup failed. Review the specific error printed above."
    }
    if ($reproductionExitCode -ne 0) {
        throw "Reproduction finished without a PASS verdict. Review the report and logs."
    }
} finally {
    Pop-Location
}

$report = Join-Path $runDirectory "report.md"
Write-Host "Completed. Report: $report" -ForegroundColor Green
