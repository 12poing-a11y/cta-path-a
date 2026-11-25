# R8 grid runner: sequential live runs, each with --out archive/R8/<name>/result.json. No retries, no cherry-picking.
$env:PYTHONUTF8 = "1"
Set-Location "D:\AI\cta-path-a"
$groups = @(
  @{ name = "A70";   args = @("--max-gross", "70") },
  @{ name = "A100";  args = @("--max-gross", "100") },
  @{ name = "B300";  args = @("--equity", "300000") },
  @{ name = "B500";  args = @("--equity", "500000") },
  @{ name = "B1000"; args = @("--equity", "1000000") },
  @{ name = "C1";    args = @("--min-lots", "1") }
)
$log = "archive\R8\grid_run.log"
foreach ($g in $groups) {
  $d = "archive\R8\$($g.name)"
  New-Item -ItemType Directory -Force $d | Out-Null
  $t = Get-Date
  python historical_backtest.py --fill next_open --out "archive/R8/$($g.name)/result.json" @($g.args) *> "$d\run.log"
  $rc = $LASTEXITCODE
  $el = [int]((Get-Date) - $t).TotalSeconds
  Add-Content $log "$($g.name) rc=$rc elapsed=${el}s args=$($g.args -join ' ')"
}
Add-Content $log "ALL_DONE"
