#Requires -Version 7.0
param(
    [ValidateSet('narae1','narae2','qwen4b','best')][string]$Model='narae2',
    [ValidateRange(1024,65535)][int]$Port=18462
)
$ErrorActionPreference='Stop'
$trainingRoot='D:\Codex\training\narae-sft-20261019'
$nativeExe='D:\Codex\tools\llama-b11669-win-cpu\llama-server.exe'
if($Model -eq 'best') {
    $comparison=Get-Content -LiteralPath "$PSScriptRoot\outputs\comparison.json" -Raw | ConvertFrom-Json
    if(-not $comparison.complete){throw 'Comparison is not complete; select an explicit model.'}
    $Model=switch($comparison.highest_structured_score_model){
        '0.6b' {'narae1'}
        '2.4b' {'narae2'}
        'qwen3-4b-instruct-2507' {'qwen4b'}
        default {throw 'No measured model selection found.'}
    }
}
$adapter=$null
if($Model -eq 'qwen4b') {
    $source=Get-Content -LiteralPath 'D:\Codex\models\Qwen3-4B-Instruct-2507-Q4_K_M\verified-source.json' -Raw | ConvertFrom-Json
    $modelFile=$source.file
    $modelHash=$source.sha256
    $alias='Qwen3-4B-Instruct-2507'
    $scope='Upstream Qwen instruction model; no Narae weight fine-tuning.'
} else {
    $tag=if($Model -eq 'narae1'){'0.6b'}else{'2.4b'}
    $alias=if($Model -eq 'narae1'){'Narae-0.6B-LoRA-v1'}else{'EXAONE-Narae-2.4B-LoRA-v1'}
    $bases=Get-Content -LiteralPath "$PSScriptRoot\verification\bases.json" -Raw | ConvertFrom-Json
    $exports=Get-Content -LiteralPath "$trainingRoot\exports\verification.json" -Raw | ConvertFrom-Json
    $modelFile=$bases.$tag.path
    $modelHash=$bases.$tag.sha256
    $adapter=@($exports.verification | Where-Object model -eq $alias)[0]
    if(-not $adapter){throw 'Missing learned adapter record.'}
    if((Get-FileHash -LiteralPath $adapter.file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $adapter.export_sha256){throw 'Learned adapter hash mismatch.'}
    $scope='Actual Narae v1 learned LoRA adapter is loaded.'
}
if((Get-FileHash -LiteralPath $modelFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne $modelHash){throw 'Base model hash mismatch.'}
$env:TEMP='D:\Codex\tmp';$env:TMP=$env:TEMP
New-Item -ItemType Directory -Path "$PSScriptRoot\logs\runtime",$env:TEMP -Force | Out-Null
$logFile=Join-Path "$PSScriptRoot\logs\runtime" ($Model+'-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'.log')
$nativeArgs=@('--model',$modelFile,'--alias',$alias,'--host','127.0.0.1','--port',[string]$Port,
    '--threads','6','--threads-batch','6','--ctx-size','8192','--parallel','1','--batch-size','512','--ubatch-size','128',
    '--cache-ram','0','--no-context-shift','--no-warmup','--no-webui','--seed','719',
    '--chat-template-kwargs','{"enable_thinking":false}')
if($adapter){$nativeArgs+=@('--lora',$adapter.file)}
Write-Host "$alias : http://127.0.0.1:$Port/v1"
Write-Host $scope
Write-Host "Logs: $logFile · Stop with Ctrl+C"
& $nativeExe @nativeArgs 2>&1 | Tee-Object -FilePath $logFile
exit $LASTEXITCODE
