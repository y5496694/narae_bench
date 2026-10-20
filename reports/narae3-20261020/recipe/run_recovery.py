"""Continue the original fixed pipeline using the documented corrected training retry."""
import os,subprocess,sys,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
for key,folder in {'TEMP':'tmp','TMP':'tmp','PYTHONPYCACHEPREFIX':'cache/pycache','HF_HOME':'cache/huggingface',
 'HF_HUB_CACHE':'cache/huggingface/hub','HF_MODULES_CACHE':'cache/modules','TORCH_HOME':'cache/torch',
 'TORCHINDUCTOR_CACHE_DIR':'cache/inductor','TORCH_EXTENSIONS_DIR':'cache/extensions'}.items():os.environ[key]=str(ROOT/folder)
from runtime import load,dump,sha
profile=load(ROOT/'frozen-training-profile.json');amendment=load(ROOT/'recovery/amendment.json')
def command(name,*args):
    for path,digest in profile['source_sha256'].items():assert sha(ROOT/path)==digest,path
    for path,digest in amendment['recovery_source_sha256'].items():assert sha(ROOT/path)==digest,path
    assert sha(Path(r'D:\Codex\workspaces\narae_bench/mock/evaluate.py'))==profile['external_controller_source_sha256']
    path=ROOT/('recovery/train_lora_recovery.py' if name=='train_lora_recovery' else 'scripts/'+name+'.py')
    with (ROOT/'logs'/f'{name}.log').open('xb') as output:
        result=subprocess.run([sys.executable,'-X','utf8',str(path),*args],stdout=output,stderr=output,
            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:raise RuntimeError('Stage failed: '+name)
try:
    command('train_lora_recovery');command('export_adapter')
    for tag,scale in [('scale-050','0.5'),('scale-100','1')]:
        command('validate_native','--tag',tag,'--scale',scale)
        (ROOT/'logs/validate_native.log').replace(ROOT/'logs'/('validate-'+tag+'.log'))
        command('general_probe','--tag',tag,'--scale',scale)
        (ROOT/'logs/general_probe.log').replace(ROOT/'logs'/('general-'+tag+'.log'))
    command('select_model');command('evaluate_narae3')
    print('Recovered Narae3 training, validation and benchmark complete',flush=True)
except BaseException as error:
    dump(ROOT/'outputs/recovery-pipeline-error.json',{'error':str(error),'traceback':traceback.format_exc()});raise
