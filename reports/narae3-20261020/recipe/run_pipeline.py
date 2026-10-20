"""Finish download/baseline, train actual Narae3, validate, select and benchmark."""
import os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for key in ['TEMP','TMP']:os.environ[key]=str(ROOT/'tmp')
os.environ['PYTHONPYCACHEPREFIX']=str(ROOT/'cache/pycache')
for key,folder in {'HF_HOME':'cache/huggingface','HF_HUB_CACHE':'cache/huggingface/hub','HF_MODULES_CACHE':'cache/modules',
    'TORCH_HOME':'cache/torch','TORCHINDUCTOR_CACHE_DIR':'cache/inductor','TORCH_EXTENSIONS_DIR':'cache/extensions'}.items():
    os.environ[key]=str(ROOT/folder)
import ast,json,socket,subprocess,sys,time,traceback
from runtime import load,dump,sha

def main():
    while not (ROOT/'models/source.json').exists() or not (ROOT/'evaluation/validation/base/results.json').exists() or not (ROOT/'evaluation/general/base/results.json').exists():
        time.sleep(5)
    baseline=load(ROOT/'evaluation/validation/base/results.json');assert baseline['complete']
    while True:
        try:
            connection=socket.create_connection(('127.0.0.1',18464),timeout=.5);connection.close();time.sleep(2)
        except OSError:break
    sources=[str(p.relative_to(ROOT)) for p in sorted((ROOT/'scripts').glob('*.py'))]
    sources += [str(p.relative_to(ROOT)) for p in sorted((ROOT/'data').glob('*')) if p.is_file()]
    sources += ['models/source.json','evaluation/controller.py','evaluation/selection-plan.json','evaluation/snapshot.json']
    for path in (ROOT/'scripts').glob('*.py'):ast.parse(path.read_text(encoding='utf-8'))
    profile={'name':'Narae3-Qwen3-4B-LoRA-v1','base_model':load(ROOT/'models/source.json'),'seed':719,'epochs':1,
        'train_records':164,'assistant_turns':362,'optimizer_steps':41,'learning_rate':5e-5,'rank':8,'alpha':16,
        'adaptation':'Final6decoderblocks,all7linearprojections;NF4base,F32LoRA;full-trajectory assistant-only loss',
        'benchmark_used_for_training_or_selection':False,'source_sha256':{name:sha(ROOT/name) for name in sources},
        'external_controller_source_sha256':sha(Path(r'D:\Codex\workspaces\narae_bench/mock/evaluate.py')),
        'baseline_validation_completed_before_training':True}
    assert profile['external_controller_source_sha256']==sha(ROOT/'evaluation/controller.py')
    assert not (ROOT/'frozen-training-profile.json').exists()
    dump(ROOT/'frozen-training-profile.json',profile)
    def command(name,*args):
        for path,digest in profile['source_sha256'].items():assert sha(ROOT/path)==digest,path
        assert sha(Path(r'D:\Codex\workspaces\narae_bench/mock/evaluate.py'))==profile['external_controller_source_sha256']
        with (ROOT/'logs'/f'{name}.log').open('wb') as output:
            completed=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts'/f'{name}.py'),*args],stdout=output,stderr=output,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        if completed.returncode:raise RuntimeError(f'Stage failed: {name}')
    command('train_lora')
    command('export_adapter')
    command('validate_native','--tag','scale-050','--scale','0.5')
    # Keep validation logs for each strength; do not overwrite the previous stage.
    (ROOT/'logs/validate_native.log').replace(ROOT/'logs/validate-scale-050.log')
    command('general_probe','--tag','scale-050','--scale','0.5')
    (ROOT/'logs/general_probe.log').replace(ROOT/'logs/general-scale-050.log')
    command('validate_native','--tag','scale-100','--scale','1')
    (ROOT/'logs/validate_native.log').replace(ROOT/'logs/validate-scale-100.log')
    command('general_probe','--tag','scale-100','--scale','1')
    (ROOT/'logs/general_probe.log').replace(ROOT/'logs/general-scale-100.log')
    command('select_model')
    command('evaluate_narae3')
    print('Narae3 actual SFT, validation selection and frozen benchmark finished',flush=True)
if __name__=='__main__':
    try:main()
    except BaseException as error:
        dump(ROOT/'outputs/pipeline-error.json',{'error':str(error),'traceback':traceback.format_exc()});raise
