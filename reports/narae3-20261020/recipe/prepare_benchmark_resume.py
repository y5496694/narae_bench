"""Document the observed pre-benchmark NameError without repeating completed tests."""
import ast,json,shutil,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from runtime import load,dump,sha
profile=load(ROOT/'frozen-training-profile.json')
for name,digest in profile['source_sha256'].items():assert sha(ROOT/name)==digest,name
heldout=load(ROOT/'evaluation/heldout/results.json');assert heldout['complete'] and len(heldout['results'])==24
assert not (ROOT/'evaluation/run').exists()
failure=(ROOT/'logs/evaluate_narae3.log').read_text(encoding='utf-8')
assert "NameError: name 'Path' is not defined" in failure
log=ROOT/'evaluation/logs/benchmark.log';assert log.stat().st_size==0
dest=ROOT/'recovery/benchmark-startup-failure';dest.mkdir(exist_ok=False)
for name in ['logs/evaluate_narae3.log','logs/recovery-pipeline.stderr.log','outputs/recovery-pipeline-error.json','evaluation/status.json']:
    shutil.copyfile(ROOT/name,dest/Path(name).name)
shutil.copyfile(log,dest/'empty-benchmark.log');log.unlink()
source=ROOT/'recovery/resume_benchmark.py';ast.parse(source.read_text(encoding='utf-8'))
files=['evaluation/heldout/results.json','evaluation/heldout/transcript.jsonl','evaluation/serving/narae3-evaluation.json',
       'outputs/selection.json','exports/verification.json','recovery/amendment.json']
files += [str(p.relative_to(ROOT)) for p in sorted(dest.iterdir())]
dump(ROOT/'recovery/benchmark-resume-amendment.json',{'created_at':datetime.now(timezone.utc).isoformat(),
    'reason':'Original main() failed on missing Path import before spawning the first public worker.',
    'completed_heldout_cases_preserved':24,'public_cases_executed_before_resume':0,
    'training_selection_and_benchmark_contracts_unchanged':True,
    'recovery':'Start a fresh identical verified native server; call original frozen evaluate_narae3.py --worker directly; no repeated held-out or training work.',
    'resume_source_sha256':sha(source),'preserved_artifacts_sha256':{name:sha(ROOT/name) for name in files}})
print(json.dumps({'ready':True,'preserved_heldout_cases':24,'public_cases_started':0}))
