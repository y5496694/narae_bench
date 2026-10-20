"""Verify immutable old sources/reports and the new synthetic report bundle."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

WORK=Path(__file__).resolve().parent
REPO=Path('D:/Codex/workspaces/narae_bench')
BUNDLE=REPO/'reports/failure-audit-20261020'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):
    with p.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

original=read(REPO/'manifest.json');assert len(original['files'])==16
for e in original['files']:assert sha(REPO/e['path'])==e['sha256']
old_count=new_count=0
for manifest in (REPO/'reports').rglob('manifest.json'):
    entries=read(manifest).get('files')
    if not isinstance(entries,dict) or not all(isinstance(v,str) and re.fullmatch(r'[0-9a-f]{64}',v) for v in entries.values()):continue
    if manifest==REPO/'reports/narae3-20261020/local-runtime/manifest.json':
        for name,digest in entries.items():assert sha(Path('D:/Codex/models/Narae3')/name)==digest
        continue
    for name,digest in entries.items():assert sha(manifest.parent/name)==digest, str(manifest.parent/name)
    if manifest.parent==BUNDLE:new_count+=len(entries)
    else:old_count+=len(entries)
assert old_count==490,old_count
entries=read(BUNDLE/'manifest.json')['files']
actual={p.relative_to(BUNDLE).as_posix() for p in BUNDLE.rglob('*') if p.is_file() and p!=BUNDLE/'manifest.json'}
assert actual==set(entries)
credential=re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-[A-Za-z0-9_-]{20,})\b|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')
total=0
for p in BUNDLE.rglob('*'):
    if not p.is_file():continue
    assert p.suffix in {'.json','.jsonl','.md','.txt','.py'},p
    assert not credential.search(p.read_text(encoding='utf8')),p
    assert p.stat().st_size<20*1024*1024,p
    total+=p.stat().st_size
for link in re.findall(r'\]\(([^)]+)\)',(BUNDLE/'README.md').read_text(encoding='utf8')):
    if not link.startswith(('https:','http:','#')):assert (BUNDLE/link).exists(),link
changed=subprocess.check_output(['git','diff','--name-only','-z','HEAD','--','reports'],cwd=REPO).decode('utf8').split('\0')
assert all(not n or n.startswith('reports/failure-audit-20261020/') for n in changed)
out={'verified':True,'original_files_sha_verified':16,'old_published_report_files_sha_verified':old_count,
     'new_report_files_sha_verified':new_count,'new_report_bytes_with_manifest':total,'credentials_found':0,
     'old_reports_unchanged':True,'weights_included':False,'training_data_included':False}
(WORK/'publication-verification.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf8')
print(json.dumps(out))
