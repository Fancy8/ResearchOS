param([string]$AuditEnvironmentDirectory='runtime/audit-venv')
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$env:TEMP=Join-Path $projectRoot 'runtime\tmp'
$env:TMP=$env:TEMP
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PIP_CACHE_DIR=Join-Path $projectRoot 'runtime\cache\pip-audit'
$python=Join-Path $projectRoot 'runtime\venv\Scripts\python.exe'
$succeeded=$false
$runId=[Guid]::NewGuid().ToString('N')
$statusPath=Join-Path $projectRoot 'artifacts\python-advisory-run.json'
@{passed=$false;state='running';run_id=$runId} | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding UTF8
Push-Location $projectRoot
try{
    $candidate=if([IO.Path]::IsPathRooted($AuditEnvironmentDirectory)){$AuditEnvironmentDirectory}else{Join-Path $projectRoot $AuditEnvironmentDirectory}
    $auditRoot=& $python -c "import pathlib,sys; root=pathlib.Path(sys.argv[1]).resolve(); target=pathlib.Path(sys.argv[2]).resolve(); assert target!=root and target.is_relative_to(root), 'Audit environment must stay inside project'; print(target)" $projectRoot $candidate
    if($LASTEXITCODE -ne 0){throw 'Audit environment path is outside the project'}
    $auditPython=Join-Path $auditRoot 'Scripts\python.exe'
    & $python tools/dependencies.py validate
    if($LASTEXITCODE -ne 0){throw 'Approved dependency manifest is invalid'}
    & $python tools/check_python_dependencies.py
    if($LASTEXITCODE -ne 0){throw 'Project package inventory has drifted'}
    foreach($group in @('bootstrap','audit')){
        & $python tools/dependencies.py download --group $group
        if($LASTEXITCODE -ne 0){throw 'Audit/installer wheel verification failed'}
    }
    if(-not (Test-Path -LiteralPath $auditPython)){
        & $python -m venv $auditRoot
        if($LASTEXITCODE -ne 0){throw 'Audit environment creation failed'}
    }
    foreach($lockFile in @('backend/bootstrap-requirements.lock.txt','tools/audit-requirements.lock.txt')){
        & $auditPython -m pip install --disable-pip-version-check --no-index --find-links runtime/wheels/cp312-win_amd64 --only-binary=:all: --require-hashes --cache-dir runtime/cache/pip-audit -r $lockFile
        if($LASTEXITCODE -ne 0){throw 'Hash-checked audit environment installation failed'}
    }
    & $auditPython -m pip check
    if($LASTEXITCODE -ne 0){throw 'Audit environment dependencies conflict'}
    & $auditPython tools/dependencies.py check --group audit
    if($LASTEXITCODE -ne 0){throw 'Audit environment has undeclared or mismatched packages'}
    $failed=$false
    foreach($taskCase in @(@{Name='runtime';Python=$python},@{Name='tooling';Python=$auditPython})){
        $taskName=$taskCase.Name
        $inputFile="artifacts/python-$taskName-audit-$runId-input.txt"
        $reportFile="artifacts/python-$taskName-audit.json"
        $summaryFile="artifacts/python-$taskName-audit-$runId-summary.json"
        & $taskCase.Python tools/dependencies.py export --output $inputFile
        if($LASTEXITCODE -ne 0){throw 'Complete audit input inventory failed'}
        # Unique raw output prevents a stale clean report satisfying a failed run.
        $runReport="artifacts/python-$taskName-audit-$runId.json"
        @{passed=$false;state='running';run_id=$runId} | ConvertTo-Json | Set-Content -LiteralPath $summaryFile -Encoding UTF8
        & $python tools/run_python_audit.py --python $auditPython --input $inputFile --report $runReport
        $toolExitCode=$LASTEXITCODE
        if(Test-Path -LiteralPath $runReport){Copy-Item -LiteralPath $runReport -Destination $reportFile}
        & $auditPython tools/dependencies.py audit-report --input $inputFile --report $runReport --tool-exit $toolExitCode --output $summaryFile
        $validationExit=$LASTEXITCODE
        if($validationExit -ne 0){$failed=$true}
        if($validationExit -eq 2){
            @{passed=$false;error_code='AUDIT_REPORT_VERIFICATION_FAILED';tool_exit_code=$toolExitCode;run_id=$runId} | ConvertTo-Json | Set-Content -LiteralPath $summaryFile -Encoding UTF8
        }
    }
    if($failed){throw 'Advisory audit failed: finding, skipped coverage, invalid report or service failure'}
    $succeeded=$true
    Write-Output 'Complete Python runtime and audit-tool advisory snapshots passed; other release gates remain open.'
}finally{
    @{passed=$succeeded;state=$(if($succeeded){'passed'}else{'failed'});run_id=$runId;finished_at=(Get-Date).ToUniversalTime().ToString('o');summaries=@("artifacts/python-runtime-audit-$runId-summary.json","artifacts/python-tooling-audit-$runId-summary.json")} | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding UTF8
    Pop-Location
}
