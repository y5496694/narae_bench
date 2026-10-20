"""Export learned tensors and verify exact F32 GGUF conversion, including MLP layers."""
import re,subprocess,sys
from pathlib import Path
import numpy as np
from safetensors.numpy import load_file
from runtime import ROOT,ALIAS,load,dump,sha
sys.path.insert(0,r'D:\Codex\tools\llama.cpp/gguf-py')
from gguf import GGUFReader
training=load(ROOT/'outputs'/ALIAS/'training-report.json')
assert training['actual_weight_training'] and training['optimizer_steps']==41
source=ROOT/'outputs'/ALIAS/'adapter/adapter_model.safetensors'
target=ROOT/'exports'/f'{ALIAS}-f32.gguf'
converter=Path(r'D:\Codex\tools\llama.cpp/convert_lora_to_gguf.py')
with (ROOT/'logs/convert.log').open('wb') as log:
    subprocess.run([sys.executable,'-X','utf8',str(converter),'--base',training['base_model']['path'],'--outtype','f32',
        '--outfile',str(target),str(source.parent)],stdout=log,stderr=log,check=True)
reader=GGUFReader(target)
assert reader.fields['general.architecture'].contents()=='qwen3'
assert reader.fields['adapter.lora.alpha'].contents()==16.0
mapping={'q_proj':'attn_q','k_proj':'attn_k','v_proj':'attn_v','o_proj':'attn_output',
         'gate_proj':'ffn_gate','up_proj':'ffn_up','down_proj':'ffn_down'}
expected={}
for name,value in load_file(source).items():
    layer=re.search(r'\.layers\.(\d+)\.',name).group(1)
    projection,side=re.search(r'\.('+'|'.join(mapping)+r')\.lora_([AB])\.',name).groups()
    key=f'blk.{layer}.{mapping[projection]}.weight.lora_{side.lower()}'
    assert key not in expected;expected[key]=value
actual={t.name:t.data for t in reader.tensors}
assert expected.keys()==actual.keys() and len(actual)==84
for key in expected:assert np.array_equal(expected[key],actual[key]),key
verification={'model':ALIAS,'file':str(target),'tensors':84,'all_f32_tensors_bitwise_equal':True,
    'source_sha256':sha(source),'export_sha256':sha(target),'alpha':16,'rank':8,
    'converter_commit':'412a363c655b479279d3050d0d1c67a5733697b4','converter_source_sha256':sha(converter),
    'scope':'Tensor conversion verified; NF4 training and Q4_K_M native inference are distinct quantizations.'}
assert verification['source_sha256']==training['adapter_file_sha256']
dump(ROOT/'exports/verification.json',verification)
print(verification)
