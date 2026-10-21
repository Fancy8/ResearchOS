$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
foreach($service in @('api','web','backup-scheduler')){
    $pidPath=Join-Path $projectRoot "runtime\$service.pid"
    if(Test-Path -LiteralPath $pidPath){
        $taskProcessId=[int](Get-Content -LiteralPath $pidPath)
        $process=Get-CimInstance Win32_Process -Filter "ProcessId=$taskProcessId"
        if($process -and $process.CommandLine -like "*$projectRoot*"){
            Stop-Process -Id $taskProcessId
        }
    }
}
$controller=Join-Path $projectRoot 'runtime\postgresql\pgsql\bin\pg_ctl.exe'
& $controller -D (Join-Path $projectRoot 'runtime\pgdata') -m fast stop
