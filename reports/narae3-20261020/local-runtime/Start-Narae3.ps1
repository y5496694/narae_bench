#Requires -Version 7.0
param([ValidateRange(1024,65535)][int]$Port=18462)
$ErrorActionPreference='Stop'
$m=Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'model.json') | ConvertFrom-Json
foreach($entry in @(@($m.base.file,$m.base.sha256),@($m.adapter.file,$m.adapter.sha256),@($m.native_executable,$m.executable_sha256))) {
    if((Get-FileHash -LiteralPath $entry[0] -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry[1]){throw 'Narae3 runtime file hash mismatch.'}
}
$runtimeRoot=Join-Path $PSScriptRoot 'runtime'
New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
$env:TEMP=$runtimeRoot;$env:TMP=$runtimeRoot
$strength=([double]$m.adapter.strength).ToString([System.Globalization.CultureInfo]::InvariantCulture)
$adapterDirectory=[System.IO.Path]::GetDirectoryName($m.adapter.file)
$scaledAdapter='{0}:{1}' -f [System.IO.Path]::GetFileName($m.adapter.file),$strength
$nativeArgs=@('--model',$m.base.file,'--alias',$m.served_model_id,'--lora-scaled',$scaledAdapter,
    '--host','127.0.0.1','--port',[string]$Port,'--threads','6','--threads-batch','6','--ctx-size','8192','--parallel','1',
    '--batch-size','512','--ubatch-size','128','--cache-ram','0','--no-context-shift','--no-warmup','--no-webui',
    '--seed','719','--chat-template-kwargs','{"enable_thinking":false}')
Write-Host ('Narae3 : http://127.0.0.1:{0}/v1 ; model={1}' -f $Port,$m.served_model_id)
Write-Host ('Actual learned LoRA strength {0}; mock score {1}/100; experimental={2}' -f $strength,$m.mock_benchmark_score,$m.experimental)
$logFile=Join-Path $runtimeRoot ('server-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'.log')
Push-Location -LiteralPath $adapterDirectory
try { & $m.native_executable @nativeArgs 2>&1 | Tee-Object -FilePath $logFile }
finally { Pop-Location }
exit $LASTEXITCODE
