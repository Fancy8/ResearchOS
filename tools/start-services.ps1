$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$env:TEMP=Join-Path $projectRoot 'runtime\tmp'
$env:TMP=$env:TEMP
$python=Join-Path $projectRoot 'runtime\venv\Scripts\python.exe'
$data=Join-Path $projectRoot 'runtime\objectstore'
$redisData=Join-Path $projectRoot 'runtime\redis-data'
New-Item -ItemType Directory -Force -Path $data,$redisData | Out-Null
$env:AWS_ACCESS_KEY_ID='researchos-local'
$env:AWS_SECRET_ACCESS_KEY='researchos-local-only'
$env:S3_BUCKET='researchos-private'
$taskPreviousDebug=$env:DEBUG
# SeaweedFS interprets inherited DEBUG as a Boolean; scope its value to this launcher.
$env:DEBUG='false'
try{
    $test=New-Object Net.Sockets.TcpClient
    $test.Connect('127.0.0.1',56379)
    $test.Dispose()
}catch{
    $server=Get-ChildItem -LiteralPath (Join-Path $projectRoot 'runtime\redis') -Filter 'redis-server.exe' -Recurse | Select-Object -First 1 -ExpandProperty FullName
    $process=Start-Process -FilePath $server -ArgumentList '--bind','127.0.0.1','--port','56379','--dir','.','--appendonly','yes' -WorkingDirectory $redisData -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $projectRoot 'runtime\redis.stdout.log') -RedirectStandardError (Join-Path $projectRoot 'runtime\redis.stderr.log')
    $process.Id | Set-Content -LiteralPath (Join-Path $projectRoot 'runtime\redis.pid')
}
try{
    $test=New-Object Net.Sockets.TcpClient
    $test.Connect('127.0.0.1',55000)
    $test.Dispose()
}catch{
    $server=Join-Path $projectRoot 'runtime\seaweedfs\weed.exe'
    $process=Start-Process -FilePath $server -ArgumentList 'mini','-dir=.','-ip=127.0.0.1','-ip.bind=127.0.0.1','-s3.port=55000','-s3.port.iceberg=0','-s3.port.lance=0','-master.port=59333','-master.port.grpc=55333','-filer.port=58888','-filer.port.grpc=55888','-volume.port=59340','-volume.port.grpc=55340','-admin.ui=false','-webdav=false','-master.telemetry=false' -WorkingDirectory $data -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $projectRoot 'runtime\storage.stdout.log') -RedirectStandardError (Join-Path $projectRoot 'runtime\storage.stderr.log')
    $process.Id | Set-Content -LiteralPath (Join-Path $projectRoot 'runtime\storage.pid')
}
foreach($service in @('worker','dispatcher')){
    $pidPath=Join-Path $projectRoot "runtime\$service.pid"
    $live=$false
    if(Test-Path -LiteralPath $pidPath){
        $taskProcessId=[int](Get-Content -LiteralPath $pidPath)
        $process=Get-CimInstance Win32_Process -Filter "ProcessId=$taskProcessId"
        $live=$process -and $process.CommandLine -like "*$projectRoot*"
    }
    if(-not $live){
        $arguments=if($service -eq 'worker'){@('-m','celery','-A','app.workers.celery_app','worker','--pool=solo','--loglevel=WARNING')}else{@('-m','app.workers.dispatcher')}
        $process=Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $projectRoot "runtime\$service.stdout.log") -RedirectStandardError (Join-Path $projectRoot "runtime\$service.stderr.log")
        $process.Id | Set-Content -LiteralPath $pidPath
    }
}
Write-Output 'Project services started: persistent S3, Redis, Celery solo worker and dispatcher (local development).'
$env:DEBUG=$taskPreviousDebug
& (Join-Path $PSScriptRoot 'start-backups.ps1')
