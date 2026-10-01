"""Validate YOLO boxes and create deterministic, disjoint train/val/test splits."""
import argparse
import hashlib
import random
import shutil
from pathlib import Path
import math
import yaml
from PIL import Image

def validate_label(path, classes):
    if not path.exists():
        raise ValueError(f'Missing label: {path}; create an empty file for background images')
    for line in path.read_text().splitlines():
        values = line.split()
        if len(values) != 5:
            raise ValueError(f'Expected class x y w h in {path}')
        cls, x, y, w, h = map(float, values)
        if not all(math.isfinite(v) for v in (cls,x,y,w,h)) or cls != int(cls) or not 0 <= cls < classes:
            raise ValueError(f'Invalid class in {path}')
        if not (0 < w <= 1 and 0 < h <= 1 and 0 <= x-w/2 and x+w/2 <= 1.00001 and 0 <= y-h/2 and y+h/2 <= 1.00001):
            raise ValueError(f'Invalid normalized box in {path}')

def prepare(source, destination, names, seed=42):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Destination must be empty; existing datasets are never overwritten')
    images = sorted(p for p in (source/'images').iterdir() if p.suffix.lower() in {'.jpg','.jpeg','.png','.webp'})
    if len(images) < 3:
        raise ValueError('At least three labeled images are required')
    seen, stems = set(), set()
    for image in images:
        with Image.open(image) as img:
            img.verify()
        validate_label(source/'labels'/f'{image.stem}.txt',len(names))
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        if digest in seen or image.stem in stems:
            raise ValueError(f'Duplicate image/stem risks split leakage: {image}')
        seen.add(digest); stems.add(image.stem)
    random.Random(seed).shuffle(images)
    n_val = max(1, int(len(images)*.1)); n_test = max(1,int(len(images)*.1))
    groups = {'train':images[:-(n_val+n_test)],'val':images[-(n_val+n_test):-n_test],'test':images[-n_test:]}
    for split, files in groups.items():
        for kind in ('images','labels'):
            (destination/kind/split).mkdir(parents=True,exist_ok=True)
        for image in files:
            shutil.copy2(image,destination/'images'/split/image.name)
            shutil.copy2(source/'labels'/f'{image.stem}.txt',destination/'labels'/split/f'{image.stem}.txt')
    (destination/'dataset.yaml').write_text(yaml.safe_dump(dict(path=destination.as_posix(),train='images/train',val='images/val',test='images/test',names=names)))
    return {split:len(files) for split,files in groups.items()}

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True);p.add_argument('--output',required=True)
    p.add_argument('--classes',nargs='+',required=True);p.add_argument('--seed',type=int,default=42)
    a=p.parse_args();print(prepare(a.source,a.output,a.classes,a.seed))
