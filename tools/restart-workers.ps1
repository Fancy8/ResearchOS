$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
foreach($service in @('worker','dispatcher')){
    $pidPath=Join-Path $projectRoot "runtime\$service.pid"
    if(Test-Path -LiteralPath $pidPath){
        $taskProcessId=[int](Get-Content -LiteralPath $pidPath)
        $process=Get-CimInstance Win32_Process -Filter "ProcessId=$taskProcessId"
        if($process -and $process.CommandLine -like "*$projectRoot*"){Stop-Process -Id $taskProcessId}
    }
}
& (Join-Path $PSScriptRoot 'start-services.ps1')
