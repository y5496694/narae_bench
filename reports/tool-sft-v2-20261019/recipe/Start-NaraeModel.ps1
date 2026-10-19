#Requires -Version 7.0
param(
    [ValidateSet('narae1','narae2','qwen4b','best')][string]$Model='narae2',
    [ValidateRange(1024,65535)][int]$Port=18462
)
$ErrorActionPreference='Stop'
$runRoot=Split-Path -Parent $PSScriptRoot
$nativeExe='D:\Codex\tools\llama-b11669-win-cpu\llama-server.exe'
if($Model -eq 'best') {
    $comparison=Get-Content -LiteralPath "$runRoot\outputs\comparison.json" -Raw | ConvertFrom-Json
    if(-not $comparison.complete){throw 'Comparison has not completed; select an explicit model.'}
    $Model=$comparison.highest_score_model
}
$adapter=$null
if($Model -eq 'qwen4b') {
    $source=Get-Content -LiteralPath 'D:\Codex\models\Qwen3-4B-Instruct-2507-Q4_K_M\verified-source.json' -Raw | ConvertFrom-Json
    $modelFile=$source.file;$modelHash=$source.sha256;$alias='Qwen3-4B-Instruct-2507'
    $scope='Upstream instruction model; no Narae weight training.'
} else {
    $size=if($Model -eq 'narae1'){'0.6b'}else{'2.4b'}
    $alias=if($Model -eq 'narae1'){'Narae-0.6B-Tool-LoRA-v2'}else{'EXAONE-Narae-2.4B-Tool-LoRA-v2'}
    $bases=Get-Content -LiteralPath 'D:\Codex\benchmarks\narae-compare-v21-20261019\verification\bases.json' -Raw | ConvertFrom-Json
    $modelFile=$bases.$size.path;$modelHash=$bases.$size.sha256
    $exports=Get-Content -LiteralPath "$PSScriptRoot\verification.json" -Raw | ConvertFrom-Json
    $adapter=@($exports.verification | Where-Object model -eq $alias)[0]
    if(-not $adapter -or -not $adapter.all_f32_tensors_bitwise_equal){throw 'Missing verified learned v2 adapter.'}
    if((Get-FileHash -LiteralPath $adapter.file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $adapter.export_sha256){throw 'Learned adapter hash mismatch.'}
    $scope='Actual v2 multi-turn SFT LoRA; no prompt-profile substitution.'
}
if((Get-FileHash -LiteralPath $nativeExe -Algorithm SHA256).Hash.ToLowerInvariant() -ne '6a4635aeb35656153d4bfeeddf761d24ed84aada9c9108d580737cbed465141b'){throw 'Inference executable hash mismatch.'}
if((Get-FileHash -LiteralPath $modelFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne $modelHash){throw 'Base model hash mismatch.'}
$env:TEMP="$runRoot\tmp";$env:TMP=$env:TEMP
New-Item -ItemType Directory -Path "$runRoot\logs\runtime",$env:TEMP -Force | Out-Null
$logFile=Join-Path "$runRoot\logs\runtime" ($Model+'-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'.log')
$nativeArgs=@('--model',$modelFile,'--alias',$alias,'--host','127.0.0.1','--port',[string]$Port,
    '--threads','6','--threads-batch','6','--ctx-size','8192','--parallel','1','--batch-size','512','--ubatch-size','128',
    '--cache-ram','0','--no-context-shift','--no-warmup','--no-webui','--seed','719','--chat-template-kwargs','{"enable_thinking":false}')
if($adapter){$nativeArgs+=@('--lora',$adapter.file)}
Write-Host "$alias : http://127.0.0.1:$Port/v1"
Write-Host $scope
Write-Host "Logs: $logFile ; stop with Ctrl+C"
& $nativeExe @nativeArgs 2>&1 | Tee-Object -FilePath $logFile
exit $LASTEXITCODE
