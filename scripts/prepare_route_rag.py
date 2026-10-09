"""Download pinned local RAG generator weights; no API key or remote code."""
import argparse
import json
import os
from pathlib import Path
from huggingface_hub import snapshot_download

ROOT=Path(__file__).resolve().parents[1]
MODEL='google/flan-t5-small'
REVISION='0fc9ddf78a1e988dac52e2dac162b0ede4fd74ab'

def prepare(destination: Path) -> None:
    print('Preparing local route RAG model...',flush=True)
    snapshot_download(MODEL,revision=REVISION,local_dir=destination,
        allow_patterns=['config.json','generation_config.json','model.safetensors','special_tokens_map.json',
                        'spiece.model','tokenizer.json','tokenizer_config.json','README.md'])
    (destination/'transitopt-model.json').write_text(json.dumps({'model':MODEL,'revision':REVISION,
        'license':'Apache-2.0','purpose':'Constrained generation from retrieved route evidence'},indent=2),encoding='utf-8')
    print('Local model ready:',destination,flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    default=Path(os.getenv('WEIGHTS_DIR') or ROOT/'weights')/'route-rag'/'flan-t5-small'
    parser.add_argument('--destination',type=Path,default=default)
    prepare(parser.parse_args().destination)
