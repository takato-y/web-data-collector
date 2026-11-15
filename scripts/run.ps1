# Runs the collector (TypeScript) and then the analysis (Python) in sequence.
# Intended to be started from Windows Task Scheduler.
#   Usage : powershell -NoProfile -ExecutionPolicy RemoteSigned -File scripts\run.ps1 [-Config path]
#   RemoteSigned refuses unsigned scripts downloaded from the Internet. If this folder came from a
#   downloaded zip, review the files and run "Unblock-File" on them once (see docs/06).
#   Exit  : 0=success / 1=partial failure / 2=config error / 3=previous run still active
# The webhook URL must be given in the environment variable WEBHOOK_URL (never in this file).
# This file is ASCII only on purpose (Windows PowerShell 5.1 reads non-BOM files as the ANSI code page).
param(
    [string]$Config = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if ($Config -eq "") { $Config = Join-Path $Root "config.yaml" }
$Config = (Resolve-Path $Config).Path
$LogDir = if ($env:RUN_LOG_DIR) { $env:RUN_LOG_DIR } else { Join-Path $Root "logs" }
$Python = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { Join-Path $Root ".venv\Scripts\python.exe" }
$Node = if ($env:NODE_BIN) { $env:NODE_BIN } else { "node" }
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir ("run_{0}.log" -f (Get-Date -Format "yyyyMMdd"))

function Write-Log([string]$Message) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Output $line
    Add-Content -Path $Log -Value $line -Encoding UTF8
}

# Do not run twice at the same time (the history DB must not be written by both parts at once).
$lockPath = Join-Path $LogDir ".run.lock"
try {
    $lock = [System.IO.File]::Open($lockPath, "OpenOrCreate", "ReadWrite", "None")
} catch {
    Write-Log "Previous run is still active. Skipped."
    exit 3
}

# Child processes print UTF-8 (Japanese messages). Read their output as UTF-8.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

# Runs one step, copies its output to the console and the log, and returns its exit code.
function Invoke-Step([string]$Exe, [string[]]$StepArgs) {
    $ErrorActionPreference = "Continue"
    & $Exe @StepArgs 2>&1 | ForEach-Object {
        $text = "$_"
        Write-Host $text
        Add-Content -Path $Log -Value $text -Encoding UTF8
    }
    return $LASTEXITCODE
}

try {
    Set-Location $Root
    Write-Log ("===== start (config: {0}) =====" -f (Split-Path -Leaf $Config))
    $collectCode = [int](Invoke-Step $Node @("collector\dist\src\cli.js", "collect", "-c", $Config))
    if ($collectCode -eq 2) {
        Write-Log "Config error. Stopped."
        exit 2
    }
    # Even after a partial collection failure, analyse what was collected.
    $analysisCode = [int](Invoke-Step $Python @("-m", "webcollector", "run", "-c", $Config))
    $code = [Math]::Max($collectCode, $analysisCode)
    Write-Log ("===== end (collect={0}, analysis={1}) =====" -f $collectCode, $analysisCode)
    exit $code
} finally {
    $lock.Close()
}
