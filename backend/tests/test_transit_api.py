"""Meaningful connected API, real detector and whole-plan approval tests."""
import os
import sys
import tempfile
import time
from pathlib import Path

_test_root=Path(tempfile.mkdtemp(prefix="transit-api-test-"))
os.environ.setdefault("DATABASE_URL","sqlite+aiosqlite:///"+(_test_root/"test.db").as_posix())
os.environ.setdefault("AUTH_ENABLED","false")
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from main import app
from security import attempts


@pytest.fixture
def client():
    attempts.clear()
    with TestClient(app) as c:
        yield c


def test_network_database_and_dashboard_consistent(client):
    network=client.get("/api/network").json()
    assert len(network["routes"])==8
    assert len(network["stops"])==12
    assert network["coordinate_system"]=="illustrative_canvas"
    dashboard=client.get("/api/dashboard/summary").json()
    assert dashboard["kpis"]["allocated_buses"]==sum(r["current_buses"] for r in network["routes"])
    assert dashboard["kpis"]["allocated_buses"]+dashboard["kpis"]["reserve_buses"]<=dashboard["kpis"]["available_buses"]
    import math
    assert dashboard["kpis"]["forecast_passenger_demand"]==sum(math.ceil(f["predicted_passengers"]*dashboard["scenario_factor"]) for f in dashboard["forecast"]["forecasts"])
    assert client.get("/api/dashboard/analytics").json()["stored_demand_rows"]>=90*48*8
    assert all(c["source"] in {"SYNTHETIC_DEMO_DATA","REAL_MODEL_DETECTION"} for c in network["corridors"])


def test_real_image_normalization_traffic_and_crowd_forecast(client):
    response=client.post("/api/vision/samples/bus-image/analyze?camera_id=CAM02")
    assert response.status_code==200,response.text
    result=response.json()
    assert result["counts"]["person"]>0
    assert len(result["detections"])==sum(result["counts"].values())
    assert all(d["source_id"] and d["bbox_format"]=="xywh_pixels" for d in result["detections"])
    observation=result["observation"]
    assert observation["source"]=="REAL_MODEL_DETECTION"
    assert observation["average_speed_kmh"] is None
    assert observation["queue_length"] is None
    assert observation["crowd_is_ridership"] is False
    assert client.get("/api/vision/results/"+observation["id"]).status_code==200
    corridor=next(c for c in client.get("/api/traffic/corridors").json()["corridors"] if c["id"]=="C02")
    assert corridor["source"]=="REAL_MODEL_DETECTION"
    forecast=client.post("/api/demand/forecast",json={"route_id":"R02","horizon_minutes":60}).json()
    assert forecast["crowd_signal_used"] is True
    assert forecast["predicted_passengers"]>=0
    assert forecast["id"] in [f["id"] for f in client.get("/api/demand/forecasts").json()["forecasts"]]
    historical=client.post("/api/demand/forecast",json={"route_id":"R02","horizon_minutes":60,
        "forecast_at":forecast["history"][-3]["timestamp"]}).json()
    assert historical["crowd_signal_used"] is False


def test_validated_inputs_and_roi(client):
    assert client.post("/api/vision/analyze-image",files={"file":("bad.exe",b"x")}).status_code==400
    assert client.post("/api/vision/analyze-image",files={"file":("bad.png",b"x")}).status_code==400
    assert client.patch("/api/cameras/CAM02",json={"roi":[.8,.8,.5,.5]}).status_code==422
    configured=client.patch("/api/cameras/CAM02",json={"roi":[0,0,.5,1]})
    assert configured.status_code==200
    assert configured.json()["roi"]==[0,0,.5,1]
    assert client.post("/api/demand/forecast",json={"route_id":"R02","stop_id":"S12"}).status_code==422
    assert client.post("/api/demand/forecast",json={"route_id":"R02","horizon_minutes":45}).status_code==422
    assert client.patch("/api/settings",json={"fleet_size":2,"reserve_fleet":1}).status_code==409
    assert client.post("/api/vision/analyze-stream").status_code==422
    client.patch("/api/cameras/CAM02",json={"roi":None})


def test_optimizer_approval_activation_and_exports_are_persisted(client):
    before=client.get("/api/routes").json()["routes"]
    response=client.post("/api/optimization/run",json={"fleet_size":28,"reserve_fleet":4,"demand_multiplier":1.2})
    assert response.status_code==200,response.text
    result=response.json()
    assert result["feasible"]
    assert result["solver_status"] in {"OPTIMAL","FEASIBLE"}
    assert sum(r["buses"] for r in result["routes"])<=24
    assert result["recommendations"]
    assert client.get("/api/routes").json()["routes"]==before
    assert client.post(f'/api/optimization/results/{result["id"]}/activate-simulation').status_code==409
    approved=client.post(f'/api/optimization/results/{result["id"]}/approve')
    assert approved.status_code==200,approved.text
    assert approved.json()["plan_approved"] is True
    assert all(r["status"]=="approved" for r in approved.json()["recommendations"])
    activated=client.post(f'/api/optimization/results/{result["id"]}/activate-simulation')
    assert activated.status_code==200,activated.text
    assert activated.json()["simulation_only"] is True
    actual={r["id"]:r["current_buses"] for r in client.get("/api/routes").json()["routes"]}
    assert actual=={r["route_id"]:r["buses"] for r in result["routes"]}
    scenario=client.get(f'/api/simulator/results/{result["scenario_id"]}').json()
    assert scenario["activated"] is True
    assert client.post(f'/api/optimization/results/{result["id"]}/activate-simulation').status_code==409
    assert client.get(f'/api/exports/scenarios/{result["scenario_id"]}?format=json').status_code==200
    assert "optimized" in client.get(f'/api/exports/scenarios/{result["scenario_id"]}?format=csv').text
    assert "activate_simulation" in client.get("/api/exports/operator-actions?format=json").text


def test_infeasible_plan_is_stored_without_recommendations(client):
    result=client.post("/api/simulator/run",json={"fleet_size":5,"reserve_fleet":4}).json()
    assert result["feasible"] is False
    assert result["warnings"]
    assert result["recommendations"]==[]
    assert client.get("/api/optimization/results/"+result["id"]).json()["feasible"] is False
    assert client.post(f'/api/optimization/results/{result["id"]}/activate-simulation').status_code==409


def test_real_video_job_and_controls(client):
    response=client.post("/api/vision/samples/bus-video/analyze?camera_id=CAM02")
    assert response.status_code==200,response.text
    job_id=response.json()["job_id"]
    paused=client.post(f"/api/vision/jobs/{job_id}/pause")
    assert paused.status_code==200
    assert client.get(f"/api/vision/jobs/{job_id}").json()["status"]=="paused"
    assert client.post(f"/api/vision/jobs/{job_id}/resume").status_code==200
    for _ in range(200):
        job=client.get(f"/api/vision/jobs/{job_id}").json()
        if job["status"] in {"complete","failed"}:
            break
        time.sleep(.05)
    assert job["status"]=="complete",job
    assert job["result"]["processed_frames"]==15
    assert job["result"]["observation"]["source"]=="REAL_MODEL_DETECTION"
    assert job["result"]["video_encoding"]=="H.264"
    assert job["result"]["browser_playback"] is True
    assert client.get(job["result"]["download_url"]).status_code==200
    second=client.post("/api/vision/samples/bus-video/analyze?camera_id=CAM02").json()
    assert client.post(f'/api/vision/jobs/{second["job_id"]}/cancel').status_code==200
    for _ in range(200):
        job=client.get(f'/api/vision/jobs/{second["job_id"]}').json()
        if job["status"]=="cancelled":
            break
        time.sleep(.02)
    assert job["status"]=="cancelled"


def test_capacity_activation_geometry_and_stale_runs(client):
    first=client.post("/api/optimization/run",json={"bus_capacity":40,"traffic_level":"high","demand_multiplier":1.2}).json()
    second=client.post("/api/optimization/run",json={"bus_capacity":40,"traffic_level":"high"}).json()
    assert first["feasible"] and second["feasible"]
    assert client.post(f'/api/optimization/results/{first["id"]}/approve').status_code==200
    assert client.post(f'/api/optimization/results/{second["id"]}/approve').status_code==200
    assert client.post(f'/api/optimization/results/{first["id"]}/activate-simulation').status_code==200
    network=client.get("/api/network").json()
    assert all(r["bus_capacity"]==40 and r["capacity"]==40 for r in network["routes"])
    for route in network["routes"]:
        active=next(v for v in route["variants"] if v["id"]==route["current_variant_id"])
        assert route["geometry"]==active["geometry"]
        assert route["cycle_minutes"]==active["cycle_minutes"]
    stale=client.post(f'/api/optimization/results/{second["id"]}/activate-simulation')
    assert stale.status_code==409 and "changed" in stale.json()["detail"]
    dashboard=client.get("/api/dashboard/summary").json()
    assert dashboard["kpis"]["capacity_shortfall"]==dashboard["plan"]["totals"]["capacity_shortfall"]
    assert all(f["horizon_minutes"]==dashboard["settings"]["horizon_minutes"] for f in dashboard["forecast"]["forecasts"])
    import math
    assert dashboard["scenario_factor"]==1.2
    assert dashboard["settings"]["traffic_level"]=="high"
    assert dashboard["kpis"]["forecast_passenger_demand"]==sum(math.ceil(f["predicted_passengers"]*1.2) for f in dashboard["forecast"]["forecasts"])
    assert dashboard["kpis"]["forecast_passenger_demand"]==dashboard["plan"]["totals"]["forecast_demand"]
    # Read the existing async database directly to verify actual vehicle capacity records.
    import asyncio
    from database import AsyncSessionLocal
    from transit.models import TransitVehicle
    from sqlalchemy import select
    async def vehicle_capacities():
        async with AsyncSessionLocal() as db:
            return list((await db.execute(select(TransitVehicle.capacity).where(TransitVehicle.available==True))).scalars())
    assert set(asyncio.run(vehicle_capacities()))=={40}
    unchanged=client.post("/api/optimization/run",json={"bus_capacity":40,"traffic_level":"high","demand_multiplier":1.2}).json()
    assert unchanged["feasible"] and unchanged["recommendations"]==[]
    assert unchanged["plan_approved"] is False
    assert client.post(f'/api/optimization/results/{unchanged["id"]}/activate-simulation').status_code==409
    approval=client.post(f'/api/optimization/results/{unchanged["id"]}/approve').json()
    assert approval["plan_approved"] is True
    assert client.post(f'/api/optimization/results/{unchanged["id"]}/activate-simulation').status_code==200
    client.patch("/api/settings",json={"bus_capacity":50})
