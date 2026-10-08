"""Exercise TransitOpt's connected local APIs and export a reproducible demo run.

The default creates recommendations for review. --activate explicitly approves and
activates this run's entire changed plan in simulation, never a real dispatch.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def request(client: httpx.Client, method: str, path: str, **kwargs):
    response = client.request(method, path, **kwargs)
    if response.is_error:
        raise RuntimeError(f"{method} {path}: HTTP {response.status_code}: {response.text[:500]}")
    return response.json()


def pick_sample(samples: list[dict], media_type: str) -> dict:
    extensions = (".jpg", ".jpeg", ".png", ".webp") if media_type == "image" else (".mp4", ".avi", ".mov", ".mkv")
    for sample in samples:
        kind = str(sample.get("type", sample.get("input_type", sample.get("media_type", "")))).lower()
        name = str(sample.get("filename", sample.get("name", sample.get("id", "")))).lower()
        if media_type in kind or any(ext in name for ext in extensions) or media_type in name:
            return sample
    raise RuntimeError(f"No bundled {media_type} sample was reported by /api/vision/samples")


def analyze_sample(client: httpx.Client, sample: dict, camera_id: str) -> dict:
    result = request(client, "POST", f"/api/vision/samples/{sample['id']}/analyze",
                     params={"camera_id": camera_id, "confidence": 0.5})
    job_id = result.get("job_id")
    if not job_id:
        return result
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        job = request(client, "GET", f"/api/vision/jobs/{job_id}")
        if job["status"] in {"complete", "completed"}:
            return job.get("result", job)
        if job["status"] in {"failed", "cancelled", "canceled"}:
            raise RuntimeError(f"Video job {job_id} {job['status']}: {job.get('error', '')}")
        time.sleep(0.25)
    raise RuntimeError(f"Video job {job_id} did not complete within four minutes")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "demo_exports")
    parser.add_argument("--activate", action="store_true", help="Approve and activate the complete run in simulation")
    parser.add_argument("--skip-video", action="store_true", help="Run the faster image/traffic/forecast/optimizer flow")
    parser.add_argument("--camera-id", default="CAM02")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    load_dotenv(ROOT / ".env", override=False)
    password = os.environ.get("ADMIN_PASSWORD")
    auth = (os.environ.get("ADMIN_USERNAME", "admin"), password) if password else None
    summary = {}
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=90, auth=auth) as client:
        summary["health"] = request(client, "GET", "/api/health")
        summary["system"] = request(client, "GET", "/api/system/status")
        samples = request(client, "GET", "/api/vision/samples").get("samples", [])
        image = analyze_sample(client, pick_sample(samples, "image"), args.camera_id)
        summary["image"] = {key: image.get(key) for key in ("analysis_id", "counts", "observation", "model_info")}
        if not args.skip_video:
            video = analyze_sample(client, pick_sample(samples, "video"), args.camera_id)
            summary["video"] = {key: video.get(key) for key in ("analysis_id", "processed_frames", "counts", "observation")}
        summary["forecast"] = request(client, "POST", "/api/demand/forecast",
                                       json={"route_id": "R02", "horizon_minutes": 60})
        settings = {"name": "Connected API demonstration", "fleet_size": 28,
                    "reserve_fleet": 4, "horizon_minutes": 60, "max_headway_minutes": 30,
                    "demand_multiplier": 1.0, "traffic_level": "current",
                    "event_intensity": "none", "solver_time_limit_seconds": 5}
        plan = request(client, "POST", "/api/optimization/run", json=settings)
        summary["optimization"] = plan
        if not plan.get("feasible"):
            raise RuntimeError("Default optimizer plan is infeasible: " + "; ".join(plan.get("warnings", [])))
        run_id = plan.get("run_id", plan.get("id"))
        if args.activate:
            summary["approval"] = request(client, "POST", f"/api/optimization/results/{run_id}/approve",
                                           json={"note": "Explicit --activate local demonstration"})
            summary["activation"] = request(client, "POST", f"/api/optimization/results/{run_id}/activate-simulation")
        scenario = request(client, "POST", "/api/simulator/run",
                           json={**settings, "name": "Demand plus 20 percent", "demand_multiplier": 1.2})
        summary["plus_20_percent"] = scenario
        scenario_id = scenario.get("scenario_id", scenario.get("id"))
        for format_name in ("json", "csv"):
            response = client.get(f"/api/exports/scenarios/{scenario_id}", params={"format": format_name})
            response.raise_for_status()
            (args.output_dir / f"scenario-{scenario_id}.{format_name}").write_bytes(response.content)
    output = args.output_dir / "demo-summary.json"
    output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "solver_status": plan["solver_status"],
                      "run_id": run_id, "activated_in_simulation": args.activate,
                      "scenario_id": scenario_id, "baseline_demand": plan["totals"]["forecast_demand"],
                      "plus_20_percent_demand": scenario["totals"]["forecast_demand"]}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (httpx.HTTPError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc
