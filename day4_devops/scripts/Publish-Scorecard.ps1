<#
.SYNOPSIS
  Reads the eval scorecard JSON and writes a human summary to the pipeline log.
  (PowerShell counterpart to the bash scripts — the JD lists both.)
#>
param(
    [Parameter(Mandatory = $true)][string]$ScorecardPath
)

if (-not (Test-Path $ScorecardPath)) {
    Write-Host "##vso[task.logissue type=warning]No scorecard at $ScorecardPath"
    exit 0
}

$card = Get-Content $ScorecardPath -Raw | ConvertFrom-Json

Write-Host "=========== EVAL SCORECARD ==========="
Write-Host ("Cases:               {0}" -f $card.cases)
Write-Host ("Category accuracy:   {0:P0}" -f $card.category_accuracy)
Write-Host ("Citation validity:   {0:P0}" -f $card.citation_validity)
Write-Host ("Groundedness (judge):{0:N2}" -f $card.judge.groundedness)
Write-Host ("Correctness (judge): {0:N2}" -f $card.judge.correctness)
Write-Host ("Helpfulness (judge): {0:N2}" -f $card.judge.helpfulness)
Write-Host ("Latency p50/p95 ms:  {0:N0} / {1:N0}" -f $card.latency_ms.p50, $card.latency_ms.p95)
Write-Host "======================================"

# Surface the headline number in the run title.
Write-Host ("##vso[build.addbuildtag]eval-acc-{0:N0}pct" -f ($card.category_accuracy * 100))
