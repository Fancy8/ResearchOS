param([switch]$SkipBrowser)
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$env:TEMP=Join-Path $projectRoot 'runtime\tmp'
$env:TMP=$env:TEMP
$env:NEXT_TELEMETRY_DISABLED='1'
$env:npm_config_cache=Join-Path $projectRoot 'runtime\cache\npm'
$env:PLAYWRIGHT_BROWSERS_PATH=Join-Path $projectRoot 'runtime\browsers'
$python=Join-Path $projectRoot 'runtime\venv\Scripts\python.exe'
Push-Location $projectRoot
try{
    & $python -m ruff check backend/app backend/tests backend/ledger_migrations tools/ledger.py tools/setup_ledger.py tools/broker_status.py tools/check_python_dependencies.py tools/dependencies.py tools/run_python_audit.py tools/tests
    if($LASTEXITCODE -ne 0){throw 'Python lint failed'}
    & $python tools/dependencies.py validate
    if($LASTEXITCODE -ne 0){throw 'Dependency approval manifest is invalid'}
    & $python -m pytest tools/tests -q --tb=short --junitxml=artifacts/dependency-tools.xml
    if($LASTEXITCODE -ne 0){throw 'Dependency integrity/advisory validation failed'}
    & $python tools/check_python_dependencies.py
    if($LASTEXITCODE -ne 0){throw 'Python runtime/bootstrap pins do not match'}
    & $python tools/export_contracts.py --check
    if($LASTEXITCODE -ne 0){throw 'OpenAPI/TypeScript contracts have drifted'}
    & $python -m alembic -c backend/alembic.ini check
    if($LASTEXITCODE -ne 0){throw 'Migration metadata has drifted'}
    & $python -m alembic -c backend/ledger-alembic.ini current --check-heads
    if($LASTEXITCODE -ne 0){throw 'Independent deletion journal migration is not current'}
    & $python tools/ledger.py status
    if($LASTEXITCODE -ne 0){throw 'Independent deletion journal inventory is not ready'}
    & $python tools/broker_status.py
    if($LASTEXITCODE -ne 0){throw 'Broker metadata is unavailable'}
    Push-Location backend
    try{
        & $python -m pytest -q --tb=short --junitxml=../artifacts/backend-all.xml
        if($LASTEXITCODE -ne 0){throw 'PostgreSQL/API tests failed'}
    }finally{Pop-Location}
    & npm --prefix frontend run typecheck
    if($LASTEXITCODE -ne 0){throw 'Frontend types failed'}
    & npm --prefix frontend run test:math-security
    if($LASTEXITCODE -ne 0){throw 'Formula rendering security regression failed'}
    & npm --prefix frontend run build
    if($LASTEXITCODE -ne 0){throw 'Frontend production build failed'}
    if(-not $SkipBrowser){
        & (Join-Path $PSScriptRoot 'restart-workers.ps1')
        & (Join-Path $PSScriptRoot 'restart-app.ps1')
        Push-Location frontend
        try{
            & npm run test:e2e
            if($LASTEXITCODE -ne 0){throw 'Browser acceptance failed'}
        }finally{Pop-Location}
    }
    Write-Output 'Selected local verification gates passed. This does not certify the remaining release gates.'
}finally{Pop-Location}
