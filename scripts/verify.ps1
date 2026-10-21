#!/usr/bin/env pwsh
# Thin PowerShell wrapper for scripts/verify.py (Windows PowerShell 5.1+ / pwsh 7+).
#
# Picks the backend virtualenv interpreter when present, falling back to the
# python/python3 on PATH.
#
#   ./scripts/verify.ps1 --skip-slow
#   ./scripts/verify.ps1 --only backend-pytest,contract-audit
[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $VerifyArgs
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

$Candidates = @(
    (Join-Path $Root "backend\.venv\Scripts\python.exe"),
    (Join-Path $Root ".venv\Scripts\python.exe")
)
$Python = $null
foreach ($Candidate in $Candidates) {
    if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
        $Python = $Candidate
        break
    }
}
if (-not $Python) {
    foreach ($Name in @("python", "python3")) {
        $Command = Get-Command $Name -ErrorAction SilentlyContinue
        if ($Command) {
            $Python = $Command.Source
            break
        }
    }
}
if (-not $Python) {
    Write-Error "verify.ps1: Python 3.11+ not found"
    exit 2
}

& $Python (Join-Path $Root "scripts\verify.py") @VerifyArgs
exit $LASTEXITCODE
