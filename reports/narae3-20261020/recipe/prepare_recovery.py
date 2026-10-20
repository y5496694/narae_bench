"""Record the observed posttraining failure and freeze a narrowly corrected retry."""
import ast,difflib,json,shutil,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from runtime import ALIAS,load,dump,sha
profile=load(ROOT/'frozen-training-profile.json')
for name,digest in profile['source_sha256'].items():assert sha(ROOT/name)==digest,name
output=ROOT/'outputs'/ALIAS
status=load(output/'status.json');assert status['stage']=='failed' and status['error']=="argument of type 'float' is not iterable"
events=[json.loads(s) for s in (output/'events.jsonl').read_text(encoding='utf-8').splitlines()]
assert [r['optimizer_step'] for r in events if r['stage']=='training']==list(range(1,42))
assert not (output/'adapter').exists() and not (ROOT/'evaluation/validation/scale-050').exists()
REC=ROOT/'recovery';REC.mkdir(exist_ok=False)
attempt=REC/'attempt-1';attempt.mkdir();shutil.copytree(output,attempt/'output')
shutil.copyfile(ROOT/'logs/train_lora.log',attempt/'train_lora.log')
shutil.copyfile(ROOT/'logs/pipeline-v3.stderr.log',attempt/'pipeline.stderr.log')
shutil.copyfile(ROOT/'outputs/pipeline-error.json',attempt/'pipeline-error.json')
cache_files={str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'cache/features').glob('*.pt'))}
assert len(cache_files)==200
dump(REC/'cache-manifest.json',{'frozen_profile_sha256':sha(ROOT/'frozen-training-profile.json'),'files':cache_files})
source=(ROOT/'scripts/train_lora.py').read_text(encoding='utf-8')
source=source.replace('ROOT=Path(__file__).resolve().parents[1]',"ROOT=Path(__file__).resolve().parents[1]\nimport sys;sys.path.insert(0,str(ROOT/'scripts'))",1)
start=source.index('    def cache_records(');end=source.index('    def read(',start)
source=source[:start]+'''    def cache_records(self,rows,split):
        paths=[];manifest=load(ROOT/'recovery/cache-manifest.json')
        for n,row in enumerate(rows):
            encoded,_=self.encode(row);path=self.cache/(row['id']+'.pt')
            assert sha(path)==manifest['files'][str(path.relative_to(ROOT))]
            record=self.read(path)
            assert record['id']==row['id'] and torch.equal(record['labels'],encoded['labels'])
            assert record['hidden'].shape==(1,encoded['input_ids'].shape[1],2560)
            assert torch.isfinite(record['hidden']).all()
            paths.append(path)
        self.emit('frozen-prefix-cache-verified-and-reused',split=split,records=len(paths))
        return paths
'''+source[end:]
old="if hasattr(module,'scaling') and 'default' in module.scaling:module.scaling['default']=2.0*value"
assert source.count(old)==1
source=source.replace(old,"if isinstance(getattr(module,'scaling',None),dict) and 'default' in module.scaling:module.scaling['default']=2.0*value")
needle="        self.model.save_pretrained(self.output/'initial-adapter',safe_serialization=True)"
assert source.count(needle)==1
source=source.replace(needle,needle+'''
        from safetensors.torch import load_file
        old_initial=load_file(ROOT/'recovery/attempt-1/output/initial-adapter/adapter_model.safetensors')
        new_initial=load_file(self.output/'initial-adapter/adapter_model.safetensors')
        assert old_initial.keys()==new_initial.keys() and len(old_initial)==84
        assert all(torch.equal(old_initial[name],value) for name,value in new_initial.items())
        del old_initial,new_initial
        scalable=[m for m in self.model.modules() if isinstance(getattr(m,'scaling',None),dict) and 'default' in m.scaling]
        assert len(scalable)==42
        for value in [0,.5,1]:
            for module in scalable:module.scaling['default']=2.0*value
            assert all(module.scaling['default']==2.0*value for module in scalable)
        self.emit('recovery-preflight-passed',identical_initial_tensors=84,scalable_lora_modules=42)
''')
needle="        encoded,spans=self.encode(representative);record=self.capture(encoded['input_ids']);record['labels']=encoded['labels']"
assert source.count(needle)==1
source=source.replace(needle,needle+'''
        prior_record=self.read(self.cache/(representative['id']+'.pt'))
        cache_recovery_error=float((record['hidden']-prior_record['hidden']).abs().max())
        assert cache_recovery_error<=2e-4 and torch.equal(record['labels'],prior_record['labels'])
        del prior_record
''')
needle='        assert self.step==total_steps'
assert source.count(needle)==1
source=source.replace(needle,needle+'''
        self.model.save_pretrained(self.output/'adapter',safe_serialization=True)
        dump(self.output/'post-update-checkpoint.json',{'optimizer_steps':self.step,
            'adapter_file_sha256':sha(self.output/'adapter/adapter_model.safetensors'),
            'recovery_amendment_sha256':sha(ROOT/'recovery/amendment.json')})
        self.emit('post-update-checkpoint-saved',optimizer_steps=self.step)
''')
needle="        self.emit('baseline-validation',loss=baseline_val)"
assert source.count(needle)==1
source=source.replace(needle,"        assert abs(baseline_val-"+repr(next(r['loss'] for r in events if r['stage']=='baseline-validation'))+")<=1e-6\n"+needle)
needle="        dump(self.output/'training-report.json',report)"
assert source.count(needle)==1
source=source.replace(needle,'''        report.update(recovery_amendment_sha256=sha(ROOT/'recovery/amendment.json'),
            attempts=2,discarded_first_attempt_updates=41,final_artifact_optimizer_updates=41,
            first_attempt_weights_saved=False,identical_initial_adapter_tensors_verified=84,
            cached_prefix_recovery_max_error=cache_recovery_error,
            original_frozen_trainer_sha256=profile['source_sha256'][r'scripts\\train_lora.py'])
'''+needle)
ast.parse(source);(REC/'train_lora_recovery.py').write_text(source,encoding='utf-8')
diff=''.join(difflib.unified_diff((ROOT/'scripts/train_lora.py').read_text(encoding='utf-8').splitlines(True),source.splitlines(True),fromfile='original frozen trainer',tofile='post-failure recovery trainer'))
(REC/'trainer.diff').write_text(diff,encoding='utf-8')
driver='''"""Continue the original fixed pipeline using the documented corrected training retry."""
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
    assert sha(Path(r'D:\\Codex\\workspaces\\narae_bench/mock/evaluate.py'))==profile['external_controller_source_sha256']
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
'''
ast.parse(driver);(REC/'run_recovery.py').write_text(driver,encoding='utf-8')
amendment={'created_at':datetime.now(timezone.utc).isoformat(),'observed_failure':status,
    'frozen_original_profile_sha256':sha(ROOT/'frozen-training-profile.json'),
    'original_sources_data_selection_and_benchmark_unchanged':True,
    'adapted_native_validation_or_public_results_observed':False,
    'reason':'Qwen attention has float scaling; only PEFT dict scaling may be changed. First 41 updates were lost before save.',
    'recovery':'Fresh identical initial adapter, same seed/data/order/optimizer/41 updates; reuse 200 verified frozen-prefix cache records; rerun equivalence and baseline; save adapter immediately after updates.',
    'discarded_optimizer_updates':41,'planned_final_artifact_updates':41,
    'first_attempt_evidence_sha256':{str(p.relative_to(ROOT)):sha(p) for p in sorted(attempt.rglob('*')) if p.is_file()},
    'recovery_source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in [REC/'train_lora_recovery.py',REC/'run_recovery.py',REC/'cache-manifest.json']}}
dump(REC/'amendment.json',amendment)
(output/'events.jsonl').unlink();(output/'status.json').unlink()
print(json.dumps({'recovery_ready':True,'cached_records':200,'original_sources_unchanged':True}))
