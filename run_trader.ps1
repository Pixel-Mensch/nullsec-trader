param(
    [ValidateSet("replay", "live")]
    [string]$Mode = "live",
    [switch]$SnapshotOnly,
    [double]$CargoM3,
    [Int64]$BudgetISK
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Python wurde nicht gefunden. Bitte Python 3.10+ installieren."
    exit 1
}

python -m pip show requests *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installiere Abhaengigkeit requests..."
    python -m pip install --user requests
}

$env:NULLSEC_REPLAY_ENABLED = if ($Mode -eq "replay") { "1" } else { "0" }

$cfgPath = Join-Path $PSScriptRoot "config.json"
$cfg = Get-Content -Raw -Encoding UTF8 $cfgPath | ConvertFrom-Json
$defaultCargo = [double]$cfg.defaults.cargo_m3
$defaultBudget = [Int64]$cfg.defaults.budget_isk
if ($PSBoundParameters.ContainsKey("CargoM3")) {
    $defaultCargo = [double]$CargoM3
}
if ($PSBoundParameters.ContainsKey("BudgetISK")) {
    $defaultBudget = [Int64]$BudgetISK
}

try {
    if ($SnapshotOnly) {
        python main.py --snapshot-only
    } else {
        python main.py --cargo-m3 $defaultCargo --budget-isk $defaultBudget
    }
} finally {
    Remove-Item Env:\NULLSEC_REPLAY_ENABLED -ErrorAction SilentlyContinue
}
