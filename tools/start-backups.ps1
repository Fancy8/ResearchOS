$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python=Join-Path $projectRoot 'runtime\venv\Scripts\python.exe'
Push-Location (Join-Path $projectRoot 'backend')
try{
    $enabled=& $python (Join-Path $PSScriptRoot 'backup.py') enabled
    if($LASTEXITCODE -ne 0){throw 'Backup schedule configuration invalid'}
    if($enabled -ne '1'){Write-Output 'Daily backup scheduler disabled by configuration'; return}
    & $python (Join-Path $PSScriptRoot 'backup.py') check
    if($LASTEXITCODE -ne 0){throw 'Configure backup reader/key before enabling the daily scheduler'}
    $pidPath=Join-Path $projectRoot 'runtime\backup-scheduler.pid'
    if(Test-Path -LiteralPath $pidPath){
        $taskBackupProcessId=[int](Get-Content -LiteralPath $pidPath)
        $process=Get-CimInstance Win32_Process -Filter "ProcessId=$taskBackupProcessId"
        if($process -and $process.CommandLine -like '*app.recovery.scheduler*' -and $process.CommandLine -like "*$projectRoot*"){return}
    }
    $process=Start-Process -FilePath $python -ArgumentList '-m','app.recovery.scheduler' -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $projectRoot 'runtime\backup-scheduler.stdout.log') -RedirectStandardError (Join-Path $projectRoot 'runtime\backup-scheduler.stderr.log')
    $process.Id | Set-Content -LiteralPath $pidPath
    Write-Output 'Daily backup operator started separately from application workers'
}finally{Pop-Location}
