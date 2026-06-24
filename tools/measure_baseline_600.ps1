$ErrorActionPreference = "Continue"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$outDir = Join-Path $root "notes"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$jsonl = Join-Path $outDir "baseline_600_times.jsonl"
$log = Join-Path $outDir "baseline_600_times.log"
$done = Join-Path $outDir "baseline_600_times.DONE"

Remove-Item -Force -ErrorAction SilentlyContinue $jsonl, $log, $done

$instances = Get-ChildItem (Join-Path $root "instances\train") -Filter "prob_*.json" |
    Sort-Object { [int](($_.BaseName -replace '^prob_', '')) }

"START $(Get-Date -Format o) count=$($instances.Count)" | Tee-Object -FilePath $log -Append | Out-Null

$idx = 0
foreach ($inst in $instances) {
    $idx += 1
    $name = $inst.BaseName
    "RUN $idx/$($instances.Count) $name $(Get-Date -Format o)" | Tee-Object -FilePath $log -Append | Out-Null

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $output = & python tools\run_solver_once.py $inst.FullName --solver baseline --timelimit 600 2>&1
    $code = $LASTEXITCODE
    $sw.Stop()

    $json = $output | Where-Object { $_ -match '^\{' } | Select-Object -Last 1
    if ($null -eq $json) {
        $fallback = @{
            instance = $name
            solver = "baseline"
            timelimit = 600
            ok = $false
            feasible = $false
            elapsed = [math]::Round($sw.Elapsed.TotalSeconds, 3)
            exit_code = $code
            error = "no json result"
        } | ConvertTo-Json -Compress
        $json = $fallback
    }

    Add-Content -Path $jsonl -Value $json
    "DONE $idx/$($instances.Count) $name exit=$code wall=$([math]::Round($sw.Elapsed.TotalSeconds, 3))s result=$json" |
        Tee-Object -FilePath $log -Append | Out-Null
}

"FINISH $(Get-Date -Format o)" | Tee-Object -FilePath $log -Append | Out-Null
"DONE" | Set-Content -Path $done -Encoding ascii
