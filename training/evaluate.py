"""
VisionX AI Analyzer — Model Evaluation Script
Compute: Precision, Recall, mAP50, mAP50-95, F1, Confusion Matrix
"""
import argparse
import json
from pathlib import Path

from ultralytics import YOLO


def evaluate(model_path: str, dataset_yaml: str, imgsz: int = 640, batch: int = 16,
             conf: float = 0.001, iou: float = 0.45, device: str = "cpu"):

    model = YOLO(model_path)
    metrics = model.val(
        data=dataset_yaml,
        imgsz=imgsz,
        batch=batch,
        conf=conf,
        iou=iou,
        device=device,
        plots=True,
        split="test",
    )

    if model.task == "classify":
        results = {"top1": float(metrics.top1), "top5": float(metrics.top5), "note": "Classification has no detection mAP; confusion matrix saved by Ultralytics"}
        (Path(metrics.save_dir)/"eval_metrics.json").write_text(json.dumps(results, indent=2))
        return results

    results = {
        "model": model_path,
        "dataset": dataset_yaml,
        "precision":  round(float(metrics.box.mp), 4),
        "recall":     round(float(metrics.box.mr), 4),
        "mAP50":      round(float(metrics.box.map50), 4),
        "mAP50_95":   round(float(metrics.box.map), 4),
        "f1":         round(float(2 * metrics.box.mp * metrics.box.mr /
                                  (metrics.box.mp + metrics.box.mr + 1e-9)), 4),
        "per_class":  {
            name: {
                "precision": round(float(metrics.box.p[i]), 4),
                "recall":    round(float(metrics.box.r[i]), 4),
                "mAP50":     round(float(metrics.box.ap50[i]), 4),
            }
            for i, class_id in enumerate(metrics.box.ap_class_index)
            for name in [metrics.names[int(class_id)]]
        },
    }

    out_path = Path(model_path).parent / "eval_metrics.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\n=== Evaluation Results ===")
    print(f"Precision : {results['precision']:.4f}")
    print(f"Recall    : {results['recall']:.4f}")
    print(f"mAP50     : {results['mAP50']:.4f}")
    print(f"mAP50-95  : {results['mAP50_95']:.4f}")
    print(f"F1        : {results['f1']:.4f}")
    print(f"\nFull results saved to: {out_path}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate a VisionX model")
    parser.add_argument("--model",   required=True, help="Path to .pt weights file")
    parser.add_argument("--data",    required=True, help="Path to dataset YAML")
    parser.add_argument("--imgsz",   type=int, default=640)
    parser.add_argument("--batch",   type=int, default=16)
    parser.add_argument("--conf",    type=float, default=0.001)
    parser.add_argument("--iou",     type=float, default=0.45)
    parser.add_argument("--device",  default="0" if __import__("torch").cuda.is_available() else "cpu")
    args = parser.parse_args()
    evaluate(args.model, args.data, args.imgsz, args.batch, args.conf, args.iou, args.device)
