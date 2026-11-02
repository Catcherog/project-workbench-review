"""Hash existing training snapshots; never download or load a model."""
from pathlib import Path
import hashlib,json,time
TASK=Path(__file__).resolve().parents[1];ROOT=TASK.parents[1]
old=ROOT/'SFT训练/R6-FIX1_20261021_01'
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(16*1024*1024),b''):h.update(b)
    return h.hexdigest()
reports=[]
for model,manifest in [('official-bf16','official_download_manifest.json'),('mlx-4bit','quantized_base_manifest.json')]:
    src=old/'provenance'/manifest;meta=json.loads(src.read_text());checks=[];start=time.monotonic()
    for x in meta['files']:
        path=old/'models'/model/x['file'];observed=sha(path) if path.is_file() else None
        checks.append({'name':x['file'],'bytes':path.stat().st_size if path.exists() else None,'sha256':observed,'matches':observed==x['sha256']})
    reports.append({'snapshot':model,'source_manifest_sha256':sha(src),'repo':meta.get('repo',meta.get('source_model')),
        'revision':meta.get('revision',meta.get('source_revision')),'all_match':all(x['matches'] for x in checks),'checks':checks,'seconds':time.monotonic()-start})
    print(model,'verified',all(x['matches'] for x in checks),flush=True)
report={'snapshots':reports,'downloaded_bytes':0,'model_loads':0,
    'runtime_gguf_to_original_hf_revision_verified':False,
    'mapping_limit':'Original Q8 GGUF source identifies upstream Qwen/Qwen3.8-27B and its own quantized digest, but no immutable upstream HF revision. Existing Safetensors revision is verified independently, not proven bit-equivalent to the Q8 source.',
    'production_model_replaced':False}
(TASK/'evidence/weight-readback.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
