param([string]$EnvironmentDirectory='runtime/venv')
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
New-Item -ItemType Directory -Force -Path (Join-Path $projectRoot 'runtime\tmp'),(Join-Path $projectRoot 'runtime\cache\pip'),(Join-Path $projectRoot 'artifacts') | Out-Null
$env:TEMP=Join-Path $projectRoot 'runtime\tmp'
$env:TMP=$env:TEMP
$env:PYTHONDONTWRITEBYTECODE='1'
$candidate=if([IO.Path]::IsPathRooted($EnvironmentDirectory)){$EnvironmentDirectory}else{Join-Path $projectRoot $EnvironmentDirectory}
$environmentRoot=& python -c "import pathlib,sys; root=pathlib.Path(sys.argv[1]).resolve(); target=pathlib.Path(sys.argv[2]).resolve(); assert target!=root and target.is_relative_to(root), 'Environment must stay inside project'; print(target)" $projectRoot $candidate
if($LASTEXITCODE -ne 0){throw 'Python environment path is outside the project'}
$python=Join-Path $environmentRoot 'Scripts\python.exe'
Push-Location $projectRoot
try{
    if(-not (Test-Path -LiteralPath $python)){
        & python -m venv $environmentRoot
        if($LASTEXITCODE -ne 0){throw 'Project Python environment creation failed'}
    }
    & $python -c "import struct,sys; assert sys.platform=='win32' and sys.version_info[:2]==(3,12) and struct.calcsize('P')==8, 'Approved wheel lock requires CPython 3.12 Windows x64'"
    if($LASTEXITCODE -ne 0){throw 'Python platform has no approved dependency lock'}
    & $python -m pip install --disable-pip-version-check --only-binary=:all: --require-hashes --index-url https://pypi.org/simple --cache-dir runtime/cache/pip -r backend/bootstrap-requirements.lock.txt
    if($LASTEXITCODE -ne 0){throw 'Pinned Python installer bootstrap failed'}
    & $python tools/dependencies.py validate
    if($LASTEXITCODE -ne 0){throw 'Dependency approval manifest does not match reviewed locks'}
    & $python tools/dependencies.py download --group application
    if($LASTEXITCODE -ne 0){throw 'Approved Python wheel delivery failed'}
    & $python -m pip install --disable-pip-version-check --no-index --find-links runtime/wheels/cp312-win_amd64 --only-binary=:all: --require-hashes --cache-dir runtime/cache/pip -r backend/requirements.lock.txt
    if($LASTEXITCODE -ne 0){throw 'Hash-checked Python dependency installation failed'}
    & $python -m pip check
    if($LASTEXITCODE -ne 0){throw 'Python dependency metadata conflicts'}
    & $python tools/check_python_dependencies.py
    if($LASTEXITCODE -ne 0){throw 'Python runtime/bootstrap inventory does not match'}
}finally{Pop-Location}
