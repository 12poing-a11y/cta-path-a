# R8 runner: sequential live runs, each with --out archive/R8/<name>/result.json. No retries, no cherry-picking.
# usage: powershell -File archive\R8\_run_groups.ps1 E100k E300k ...
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Names)
$env:PYTHONUTF8 = "1"
Set-Location "D:\AI\cta-path-a"
$defs = @{
  "E100k"  = @("--equity", "100000");
  "E300k"  = @("--equity", "300000");
  "E500k"  = @("--equity", "500000");
  "E1000k" = @("--equity", "1000000");
  "F1"     = @("--equity", "1000000", "--filter-unit-risk");
  "F2"     = @("--equity", "1000000", "--filter-atr-spike");
  "F1F2"   = @("--equity", "1000000", "--filter-unit-risk", "--filter-atr-spike")
}
$log = "archive\R8\grid_run.log"
foreach ($n in $Names) {
  if (-not $defs.ContainsKey($n)) { Add-Content $log "$n UNKNOWN_GROUP"; continue }
  $d = "archive\R8\$n"
  New-Item -ItemType Directory -Force $d | Out-Null
  $t = Get-Date
  python historical_backtest.py --fill next_open --out "archive/R8/$n/result.json" @($defs[$n]) *> "$d\run.log"
  $rc = $LASTEXITCODE
  $el = [int]((Get-Date) - $t).TotalSeconds
  Add-Content $log "$n rc=$rc elapsed=${el}s args=$($defs[$n] -join ' ')"
}
Add-Content $log "DONE $($Names -join ',')"
