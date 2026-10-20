"""Preserve completed held-out work and start the unchanged frozen public worker."""
import os,subprocess,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
for key,folder in {'TEMP':'tmp','TMP':'tmp','PYTHONPYCACHEPREFIX':'cache/pycache','HF_HOME':'cache/huggingface',
 'HF_HUB_CACHE':'cache/huggingface/hub','HF_MODULES_CACHE':'cache/modules','TORCH_HOME':'cache/torch',
 'TORCHINDUCTOR_CACHE_DIR':'cache/inductor','TORCH_EXTENSIONS_DIR':'cache/extensions'}.items():os.environ[key]=str(ROOT/folder)
from runtime import ALIAS,Server,load,dump,sha
profile=load(ROOT/'frozen-training-profile.json');amendment=load(ROOT/'recovery/benchmark-resume-amendment.json')
for name,digest in profile['source_sha256'].items():assert sha(ROOT/name)==digest,name
for name,digest in amendment['preserved_artifacts_sha256'].items():assert sha(ROOT/name)==digest,name
assert sha(__file__)==amendment['resume_source_sha256']
assert not (ROOT/'evaluation/run').exists()
heldout=load(ROOT/'evaluation/heldout/results.json');assert heldout['complete'] and len(heldout['results'])==24
selection=load(ROOT/'outputs/selection.json');strength=selection['evaluation_candidate']['strength'];assert strength>0
server=Server('narae3-public-resume',strength)
try:
    assert server.manifest==load(ROOT/'evaluation/serving/narae3-evaluation.json')
    path=ROOT/'evaluation/logs/benchmark.log'
    with path.open('xb') as log:
        # The original worker is intact; only main() had the missing Path import.
        child=subprocess.Popen([sys.executable,'-X','utf8',str(ROOT/'scripts/evaluate_narae3.py'),'--worker'],
            stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        while child.poll() is None:
            text=path.read_text(encoding='utf-8')
            dump(ROOT/'evaluation/status.json',{'stage':'benchmark','completed':text.count('"case_completed":'),'planned':36})
            time.sleep(2)
        if child.returncode:raise RuntimeError('Frozen public worker failed; preserve artifacts and inspect benchmark.log')
    summary=load(ROOT/'evaluation/run/summary.json')
    assert summary['all_cases_completed'] and summary['not_run']==0
    dump(ROOT/'evaluation/status.json',{'stage':'complete','score':summary['strict_e2e_score']})
    print({'model':ALIAS,'strength':strength,'score':summary['strict_e2e_score'],'heldout_passed':heldout['passed']},flush=True)
except BaseException as error:
    dump(ROOT/'outputs/benchmark-resume-error.json',{'error':str(error),'traceback':traceback.format_exc()});raise
finally:server.close()
