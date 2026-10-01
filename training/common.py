import argparse
from pathlib import Path
from ultralytics import YOLO
from prepare_dataset import validate_label
import yaml

ROOT = Path(__file__).resolve().parents[1]

def train(kind):
    p=argparse.ArgumentParser(description=f'Train VisionX {kind} model')
    classification=kind=='container_condition'
    p.add_argument('--data',default=str(ROOT/'datasets'/kind/('' if classification else 'dataset.yaml')))
    p.add_argument('--weights',default='yolo26n-cls.pt' if classification else 'yolo26n.pt')
    p.add_argument('--epochs',type=int,default=100);p.add_argument('--imgsz',type=int,default=640)
    p.add_argument('--batch',type=int,default=8);p.add_argument('--device',default='cpu')
    a=p.parse_args()
    if classification:
        for split in ('train','val','test'):
            for label in ('good','damaged'):
                folder=Path(a.data)/split/label
                if not folder.exists() or not any(f for f in folder.iterdir() if f.suffix.lower() in {'.jpg','.png','.jpeg','.webp'}):
                    p.error(f'Missing classification crop images: {folder}')
    else:
        data=yaml.safe_load(Path(a.data).read_text())
        root=Path(data.get('path',Path(a.data).parent))
        if not root.is_absolute():root=(Path(a.data).parent/root).resolve()
        data['path']=root.as_posix()
        Path(a.data).write_text(yaml.safe_dump(data))
        for split in ('train','val','test'):
            images=[f for f in (root/data[split]).glob('*') if f.suffix.lower() in {'.jpg','.png','.jpeg','.webp'}]
            if not images:p.error(f'Empty {split} dataset')
            for image in images:
                validate_label(root/'labels'/split/f'{image.stem}.txt',len(data['names']))
    model=YOLO(a.weights)
    if model.task != ('classify' if classification else 'detect'):
        p.error('Weights task does not match dataset')
    options=dict(fliplr=.5,degrees=5,scale=.3)
    if not classification:options['mosaic']=1.0
    result=model.train(data=a.data,epochs=a.epochs,imgsz=a.imgsz,batch=a.batch,device=a.device,
                       project=str(ROOT/'models'/kind),name='training',**options)
    print(f'Best weights: {result.save_dir}/weights/best.pt. Upload these in Model Center.')
