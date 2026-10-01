"""Prepare cropped-container classification data, stratified by class."""
import argparse
import hashlib
import random
import shutil
from pathlib import Path
from PIL import Image

def prepare(source, output, seed=42):
    source, output = Path(source), Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output must be empty')
    plans, seen = {}, set()
    for label in ('good','damaged'):
        files = sorted(p for p in (source/label).glob('*') if p.suffix.lower() in {'.jpg','.jpeg','.png','.webp'})
        if len(files) < 3:
            raise ValueError(f'At least 3 cropped images per class required: {label}')
        for path in files:
            with Image.open(path) as image:
                image.verify()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest in seen:
                raise ValueError(f'Duplicate image: {path}')
            seen.add(digest)
        random.Random(seed).shuffle(files)
        n=max(1,len(files)//10)
        plans[label]={'train':files[:-2*n],'val':files[-2*n:-n],'test':files[-n:]}
    for label,splits in plans.items():
        for split,files in splits.items():
            folder=output/split/label;folder.mkdir(parents=True,exist_ok=True)
            for path in files:
                shutil.copy2(path,folder/path.name)
    return {label:{split:len(files) for split,files in splits.items()} for label,splits in plans.items()}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True);p.add_argument('--output',required=True);p.add_argument('--seed',type=int,default=42)
    a=p.parse_args();print(prepare(a.source,a.output,a.seed))
