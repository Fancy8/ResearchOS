$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
New-Item -ItemType Directory -Force -Path (Join-Path $projectRoot 'runtime\tmp'),(Join-Path $projectRoot 'runtime\cache'),(Join-Path $projectRoot 'artifacts') | Out-Null
$env:TEMP=Join-Path $projectRoot 'runtime\tmp'
$env:TMP=$env:TEMP
$env:npm_config_cache=Join-Path $projectRoot 'runtime\cache\npm'
$env:PLAYWRIGHT_BROWSERS_PATH=Join-Path $projectRoot 'runtime\browsers'
$env:NEXT_TELEMETRY_DISABLED='1'
Push-Location $projectRoot
try{
    & (Join-Path $PSScriptRoot 'install-python-dependencies.ps1')
    $python=Join-Path $projectRoot 'runtime\venv\Scripts\python.exe'
    & $python tools/setup_postgres.py
    if($LASTEXITCODE -ne 0){throw 'PostgreSQL setup failed'}
    & $python tools/setup_services.py
    if($LASTEXITCODE -ne 0){throw 'Local service setup failed'}
    & $python tools/init_database.py
    if($LASTEXITCODE -ne 0){throw 'Database initialization failed'}
    & $python -m alembic -c backend/alembic.ini upgrade head
    if($LASTEXITCODE -ne 0){throw 'Database migrations failed'}
    & $python tools/setup_ledger.py
    if($LASTEXITCODE -ne 0){throw 'Deletion journal provisioning failed'}
    & $python tools/ledger.py status
    if($LASTEXITCODE -ne 0){
        & $python tools/ledger.py init-empty --maintenance-ack
        if($LASTEXITCODE -ne 0){throw 'Review the legacy deletion inventory with tools/ledger.py before starting'}
    }
    & npm --prefix frontend ci
    if($LASTEXITCODE -ne 0){throw 'Frontend dependency installation failed'}
    & npm --prefix frontend run build
    if($LASTEXITCODE -ne 0){throw 'Frontend build failed'}
    & (Join-Path $PSScriptRoot 'start-services.ps1')
    & (Join-Path $PSScriptRoot 'start.ps1')
}finally{Pop-Location}
