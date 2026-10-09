"""Build stock YOLO/RAG weights and reproducible forecast assets into a cloud image."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))


def prepare(seed: Path) -> None:
    from ultralytics import YOLO
    from ultralytics.utils.downloads import attempt_download_asset
    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
    from prepare_route_rag import prepare as prepare_rag
    from services.transit_forecasting import TransitForecastService
    from transit.seed import ROUTE_SPECS

    weights=seed/'weights'
    weights.mkdir(parents=True,exist_ok=True)
    hashes={}
    for filename in ('yolo26n.pt','yolo26n-pose.pt'):
        path=Path(attempt_download_asset(weights/filename,release='v8.4.0'))
        if not path.is_file():
            raise RuntimeError(f'Official model download failed: {filename}')
        YOLO(path)  # Validate the checkpoint now, before deployment.
        hashes[filename]=hashlib.sha256(path.read_bytes()).hexdigest()

    rag=weights/'route-rag'/'flan-t5-small'
    prepare_rag(rag)
    AutoTokenizer.from_pretrained(rag,local_files_only=True,trust_remote_code=False)
    AutoModelForSeq2SeqLM.from_pretrained(rag,local_files_only=True,
                                       trust_remote_code=False,use_safetensors=True)
    forecast=TransitForecastService(ROUTE_SPECS,seed/'forecasting',
                                   dataset_path=seed/'synthetic'/'transit_demand.csv.gz')
    forecast.ensure_ready()
    (seed/'cloud-models.json').write_text(json.dumps({
        'detection_release':'ultralytics/assets v8.4.0','detection_sha256':hashes,
        'rag':'google/flan-t5-small','demand_source':'SYNTHETIC_DEMO_DATA',
        'forecast_signature':forecast.signature,
    },indent=2),encoding='utf-8')
    print('Cloud model seed assets ready.',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed-dir',type=Path,required=True)
    prepare(parser.parse_args().seed_dir)
