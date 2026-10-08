"""Explicitly labeled local GPS simulation for a registered demo bus.

Run with --steps 1 to publish one position, or leave the default to publish
the six-point Salem demo loop. No position is generated at server startup.
"""
import argparse
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from config import settings

DEMO_POINTS = [
    (11.6757, 78.1402), (11.6739, 78.1409), (11.6721, 78.1420),
    (11.6697, 78.1431), (11.6673, 78.1446), (11.6649, 78.1460),
]


def main():
    parser = argparse.ArgumentParser(description="Publish clearly marked synthetic bus GPS via the live API")
    parser.add_argument("--bus", default="BUS005")
    parser.add_argument("--steps", type=int, default=6)
    parser.add_argument("--interval", type=float, default=10)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    if not 1 <= args.steps <= 1000 or not 1 <= args.interval <= 120:
        parser.error("steps must be 1–1000 and interval 1–120 seconds")
    with httpx.Client(base_url=args.base_url, auth=(settings.admin_username, settings.admin_password), timeout=12) as client:
        session = client.post(f"/api/buses/{args.bus}/session",json={
            "direction":"outbound","active":True,"source":"demo_simulation"})
        session.raise_for_status()
        for index in range(args.steps):
            latitude, longitude = DEMO_POINTS[index % len(DEMO_POINTS)]
            result = client.post(f"/api/buses/{args.bus}/location", json={
                "latitude": latitude, "longitude": longitude, "accuracy_m": None,
                "speed_kmh": 18, "source": "demo_simulation"})
            result.raise_for_status()
            print(f"SIMULATION {index + 1}/{args.steps}: {args.bus} at {latitude:.5f}, {longitude:.5f}", flush=True)
            if index + 1 < args.steps:
                time.sleep(args.interval)


if __name__ == "__main__":
    main()
