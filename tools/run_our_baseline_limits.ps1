$ErrorActionPreference = "Continue"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$outDir = Join-Path $root "notes"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$jsonl = Join-Path $outDir "our_latest_baseline_limits.jsonl"
$log = Join-Path $outDir "our_latest_baseline_limits.log"
$done = Join-Path $outDir "our_latest_baseline_limits.DONE"
$limitsPath = Join-Path $outDir "baseline_600_time_limits.csv"

Remove-Item -Force -ErrorAction SilentlyContinue $jsonl, $log, $done

$limits = Import-Csv $limitsPath | Sort-Object { [int](($_.instance -replace '^prob_', '')) }

"START $(Get-Date -Format o) count=$($limits.Count)" | Tee-Object -FilePath $log -Append | Out-Null

$idx = 0
foreach ($row in $limits) {
    $idx += 1
    $name = $row.instance
    $limit = [double]$row.limit_ceil_s
    $instPath = Join-Path $root ("instances\train\{0}.json" -f $name)

    "RUN $idx/$($limits.Count) $name limit=${limit}s $(Get-Date -Format o)" |
        Tee-Object -FilePath $log -Append | Out-Null

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $output = & python tools\run_solver_once.py $instPath --solver our --timelimit $limit 2>&1
    $code = $LASTEXITCODE
    $sw.Stop()

    $json = $output | Where-Object { $_ -match '^\{' } | Select-Object -Last 1
    if ($null -eq $json) {
        $fallback = @{
            instance = $name
            solver = "our"
            timelimit = $limit
            ok = $false
            feasible = $false
            elapsed = [math]::Round($sw.Elapsed.TotalSeconds, 3)
            exit_code = $code
            error = "no json result"
        } | ConvertTo-Json -Compress
        $json = $fallback
    }

    Add-Content -Path $jsonl -Value $json
    "DONE $idx/$($limits.Count) $name exit=$code wall=$([math]::Round($sw.Elapsed.TotalSeconds, 3))s result=$json" |
        Tee-Object -FilePath $log -Append | Out-Null
}

"FINISH $(Get-Date -Format o)" | Tee-Object -FilePath $log -Append | Out-Null
"DONE" | Set-Content -Path $done -Encoding ascii
