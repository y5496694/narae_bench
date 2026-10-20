"""Verify original files and public synthetic report bundles without publishing weights."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
repo=Path(r'D:\Codex\workspaces\narae_bench');bundle=repo/'reports/narae3-20261020'
def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
original=load(repo/'manifest.json');assert len(original['files'])==16
for row in original['files']:assert sha(repo/row['path'])==row['sha256'],row['path']
verified=0;external_manifest=None
for manifest_path in sorted((repo/'reports').rglob('manifest.json')):
    values=load(manifest_path).get('files')
    if not isinstance(values,dict) or not all(isinstance(v,str) and re.fullmatch(r'[0-9a-f]{64}',v) for v in values.values()):continue
    if manifest_path==bundle/'local-runtime/manifest.json':
        external_manifest=values
        local=Path(load(bundle/'local-model.json')['path'])
        for name,digest in values.items():assert sha(local/name)==digest,name
        continue
    for name,digest in values.items():assert sha(manifest_path.parent/name)==digest,str(manifest_path.parent/name)
    verified+=len(values)
manifest=load(bundle/'manifest.json')['files']
actual={p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_file() and p!=bundle/'manifest.json'}
assert actual==set(manifest) and external_manifest is not None
credential=re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-[A-Za-z0-9_-]{20,})\b|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')
total=0
for p in bundle.rglob('*'):
    if not p.is_file():continue
    assert p.suffix in {'.json','.jsonl','.md','.html','.txt','.py','.ps1'} or p.name in {'LICENSE','NOTICE'},p
    assert p.name not in {'train.jsonl','validation.jsonl','test.jsonl','train-trajectories.jsonl','validation-trajectories.jsonl','test-trajectories.jsonl'},p
    assert p.stat().st_size<40*1024*1024,p
    assert not credential.search(p.read_text(encoding='utf-8')),str(p)
    total+=p.stat().st_size
for target in re.findall(r'\]\(([^)]+)\)',(bundle/'README.md').read_text(encoding='utf-8')):
    if not target.startswith(('https:','http:','#')):assert (bundle/target).exists(),target
report=load(bundle/'comparison.json');audit=load(bundle/'evaluation-metadata/verification.json')
assert report['complete'] and report['training']['actual_weight_training'] and audit['verified']
assert not report['model_weights_in_public_bundle'] and not report['raw_training_data_in_public_bundle']
assert report['launcher_check']['verified'] and report['launcher_check']['own_server_stopped']
result={'verified':True,'original_v1_sha_files':16,'all_published_report_sha_files':verified,
        'local_runtime_external_manifest_files_verified':len(external_manifest),'new_bundle_files':len(manifest),
        'new_bundle_bytes_including_manifest':total,'credential_patterns_found':0,'weights_and_raw_training_data_included':False}
(ROOT/'outputs/publication-verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result))
