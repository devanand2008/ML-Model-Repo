"""Generate TransitOpt's 90-day synthetic history and train reusable XGBoost artifacts."""
from pathlib import Path
import argparse
import json
import os
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.transit_forecasting import TransitForecastService
from transit.seed import ROUTE_SPECS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Regenerate deterministic data and retrain all horizons")
    parser.add_argument("--artifacts-dir", type=Path, default=Path(os.getenv("TRANSIT_FORECAST_DIR") or ROOT / "data" / "forecasting"))
    parser.add_argument("--dataset-path", type=Path, default=Path(os.getenv("TRANSIT_DEMAND_DATASET") or ROOT / "data" / "synthetic" / "transit_demand.csv.gz"))
    args = parser.parse_args()
    service = TransitForecastService(ROUTE_SPECS, args.artifacts_dir, dataset_path=args.dataset_path)
    started = time.perf_counter()
    result = service.train(regenerate=True) if args.force else service.ensure_ready()
    print(json.dumps({"elapsed_seconds": round(time.perf_counter() - started, 2), **result}, indent=2))


if __name__ == "__main__":
    main()
