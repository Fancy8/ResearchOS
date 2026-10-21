param([switch]$Development)
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$env:TEMP=Join-Path $projectRoot 'runtime\tmp'
$env:TMP=$env:TEMP
$env:NEXT_TELEMETRY_DISABLED='1'
$env:npm_config_cache=Join-Path $projectRoot 'runtime\cache\npm'
$env:PLAYWRIGHT_BROWSERS_PATH=Join-Path $projectRoot 'runtime\browsers'
$python=Join-Path $projectRoot 'runtime\venv\Scripts\python.exe'
Push-Location $projectRoot
try {
    & $python tools/init_database.py
    if($LASTEXITCODE -ne 0){throw 'Database initialization failed'}
    & $python -m alembic -c backend/alembic.ini upgrade head
    if($LASTEXITCODE -ne 0){throw 'Migration failed'}
    & $python -m alembic -c backend/ledger-alembic.ini current --check-heads
    if($LASTEXITCODE -ne 0){throw 'Initialize the independent journal with tools/setup_ledger.py'}
    & $python tools/ledger.py status
    if($LASTEXITCODE -ne 0){throw 'Review and activate the independent deletion inventory before starting'}
    $apiReady=$false
    try { $result=Invoke-RestMethod 'http://127.0.0.1:58000/api/health' -TimeoutSec 2; $apiReady=$result.status -eq 'ready' -and $result.service -eq 'ResearchOS' } catch {}
    if(-not $apiReady){
        $process=Start-Process -FilePath $python -ArgumentList '-u','backend/run.py' -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $projectRoot 'runtime\api.stdout.log') -RedirectStandardError (Join-Path $projectRoot 'runtime\api.stderr.log')
        $process.Id | Set-Content -LiteralPath (Join-Path $projectRoot 'runtime\api.pid')
    }
    $webReady=$false
    try { $response=Invoke-WebRequest 'http://127.0.0.1:3000/login' -TimeoutSec 2 -UseBasicParsing; $webReady=$response.Content -match 'ResearchOS' } catch {}
    if(-not $webReady){
        $next=Join-Path $projectRoot 'frontend\node_modules\next\dist\bin\next'
        $mode=if($Development){'dev'}else{'start'}
        $process=Start-Process -FilePath (Get-Command node.exe).Source -ArgumentList $next,$mode,'--hostname','127.0.0.1' -WorkingDirectory (Join-Path $projectRoot 'frontend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $projectRoot 'runtime\web.stdout.log') -RedirectStandardError (Join-Path $projectRoot 'runtime\web.stderr.log')
        $process.Id | Set-Content -LiteralPath (Join-Path $projectRoot 'runtime\web.pid')
    }
    $deadline=(Get-Date).AddSeconds(30)
    do{
        $apiReady=$false
        $webReady=$false
        try { $result=Invoke-RestMethod 'http://127.0.0.1:58000/api/health' -TimeoutSec 2; $apiReady=$result.status -eq 'ready' -and $result.service -eq 'ResearchOS' } catch {}
        try { $response=Invoke-WebRequest 'http://127.0.0.1:3000/login' -TimeoutSec 2 -UseBasicParsing; $webReady=$response.Content -match 'ResearchOS' } catch {}
        if($apiReady -and $webReady){break}
        Start-Sleep -Milliseconds 300
    }while((Get-Date) -lt $deadline)
    if(-not ($apiReady -and $webReady)){throw 'ResearchOS startup did not become ready; inspect project-local runtime logs'}
    Write-Output 'ResearchOS verified local endpoints: http://localhost:3000/login and http://127.0.0.1:58000/api/docs'
} finally { Pop-Location }
