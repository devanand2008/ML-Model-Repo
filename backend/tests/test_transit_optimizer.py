"""Constraint and scenario behavior tests run the genuine OR-Tools solver."""
import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.transit_optimizer import evaluate_plan, optimize_plan


@pytest.fixture
def network():
    return {"stops": [{"id": "S1", "essential": True}, {"id": "S2", "essential": True},
                      {"id": "S3", "essential": False}],
            "segments": [{"id": "A", "from_stop": "S1", "to_stop": "S2", "congestion_score": 90},
                         {"id": "B", "from_stop": "S1", "to_stop": "S2", "congestion_score": 10},
                         {"id": "C", "from_stop": "S2", "to_stop": "S3", "congestion_score": 20}]}


@pytest.fixture
def routes():
    return [{"id": "R01", "current_buses": 2, "current_variant_id": "existing", "min_buses": 1,
             "essential": True, "required_stop_ids": ["S1", "S2"],
             "variants": [{"id": "existing", "stop_ids": ["S1", "S2"], "segment_ids": ["A"], "cycle_minutes": 40},
                          {"id": "alternative", "stop_ids": ["S1", "S2"], "segment_ids": ["B"], "cycle_minutes": 42}]},
            {"id": "R02", "current_buses": 2, "current_variant_id": "existing", "min_buses": 1,
             "essential": True,
             "variants": [{"id": "existing", "stop_ids": ["S2", "S3"], "segment_ids": ["C"], "cycle_minutes": 36}]}]


def test_solver_respects_fleet_reserve_capacity_and_essential_stops(routes, network):
    result = optimize_plan(routes, network, {"R01": 280, "R02": 160}, {"fleet_size": 8, "reserve_fleet": 2})
    assert result["solver_status"] == "OPTIMAL"
    assert result["feasible"]
    assert result["totals"]["allocated_buses"] <= 6
    assert result["totals"]["reserve_fleet"] == 2
    assert all(row["headway_minutes"] <= 30 for row in result["routes"])
    for row in result["routes"]:
        assert row["served_demand"] <= row["capacity"]
        assert row["served_demand"] + row["unserved_demand"] == row["demand"]
    assert all(item["satisfied"] for item in result["constraints"])
    assert result["objective_value_inr"] <= result["baseline"]["totals"]["objective_cost_inr"]
    assert all(row["reason"] for row in result["routes"])


def test_infeasible_headway_returns_no_fabricated_recommendation(routes, network):
    result = optimize_plan(routes, network, {"R01": 200, "R02": 100},
                           {"fleet_size": 3, "reserve_fleet": 1, "max_headway_minutes": 15})
    assert result["solver_status"] == "INFEASIBLE"
    assert not result["feasible"]
    assert result["routes"] == [] and result["objective_value_inr"] is None
    assert any("operational buses" in warning for warning in result["warnings"])


def test_invalid_graph_and_required_stop_alternatives_are_excluded(routes, network):
    routes[0]["variants"].append({"id": "teleport", "stop_ids": ["S1", "S2"],
                                   "segment_ids": ["C"], "cycle_minutes": 1})
    routes[0]["variants"].append({"id": "skip", "stop_ids": ["S2", "S3"],
                                   "segment_ids": ["C"], "cycle_minutes": 1})
    result = optimize_plan(routes, network, {"R01": 250, "R02": 120}, {"fleet_size": 8, "reserve_fleet": 1})
    assert result["feasible"]
    assert {row["variant_id"] for row in result["routes"]}.isdisjoint({"teleport", "skip"})
    assert any("does not connect" in warning for warning in result["warnings"])
    assert any("required route stop" in warning for warning in result["warnings"])
    invalid = evaluate_plan(routes, network, {"R01": 250, "R02": 120},
                            {"fleet_size": 8, "reserve_fleet": 1}, {"R01": {"buses": 2, "variant_id": "teleport"}})
    assert not invalid["feasible"]
    assert invalid["totals"]["forecast_demand"] == 370


def test_congestion_changes_route_variant_using_solver(routes, network):
    result = optimize_plan(routes, network, {"R01": 190, "R02": 80}, {"fleet_size": 8, "reserve_fleet": 2})
    assert result["routes"][0]["variant_id"] == "alternative"
    changed_network = deepcopy(network)
    changed_network["segments"][0]["congestion_score"] = 0
    changed_network["segments"][1]["congestion_score"] = 100
    changed = optimize_plan(routes, changed_network, {"R01": 190, "R02": 80}, {"fleet_size": 8, "reserve_fleet": 2})
    assert changed["routes"][0]["variant_id"] == "existing"


def test_reversed_road_requires_explicit_bidirectional_permission(routes, network):
    network["segments"][0]["from_stop"], network["segments"][0]["to_stop"] = "S2", "S1"
    network["segments"][1]["from_stop"], network["segments"][1]["to_stop"] = "S2", "S1"
    rejected = optimize_plan(routes, network, {"R01": 100, "R02": 50}, {"fleet_size": 8, "reserve_fleet": 1})
    assert not rejected["feasible"]
    for segment in network["segments"][:2]:
        segment["bidirectional"] = True
    accepted = optimize_plan(routes, network, {"R01": 100, "R02": 50}, {"fleet_size": 8, "reserve_fleet": 1})
    assert accepted["feasible"]


def test_demand_event_and_traffic_applied_to_both_comparison_plans(routes, network):
    config = {"fleet_size": 10, "reserve_fleet": 2, "demand_multiplier": 1.2,
              "event_intensity": "moderate", "traffic_level": "low"}
    result = optimize_plan(routes, network, {"R01": 100, "R02": 50}, config)
    assert result["feasible"]
    assert result["totals"]["forecast_demand"] == 198
    assert result["baseline"]["totals"]["forecast_demand"] == 198
    baseline_high = evaluate_plan(routes, network, {"R01": 100, "R02": 50},
                                  {**config, "traffic_level": "high"})
    assert baseline_high["totals"]["average_delay_minutes"] > result["baseline"]["totals"]["average_delay_minutes"]
    assert result["comparison"]["average_wait_minutes"]["baseline"] == result["baseline"]["totals"]["average_wait_minutes"]


def test_activation_validation_rejects_partial_overallocation(routes, network):
    config = {"fleet_size": 6, "reserve_fleet": 2}
    assert evaluate_plan(routes, network, {"R01": 150, "R02": 100}, config)["feasible"]
    invalid = evaluate_plan(routes, network, {"R01": 150, "R02": 100}, config,
                            {"R01": {"buses": 4, "variant_id": "alternative"}})
    assert not invalid["feasible"]
    assert not next(c for c in invalid["constraints"] if c["name"] == "Operational fleet and reserve")["satisfied"]


def test_missing_essential_stop_is_infeasible(routes, network):
    network["stops"].append({"id": "S4", "essential": True})
    result = optimize_plan(routes, network, {"R01": 100, "R02": 50}, {"fleet_size": 8, "reserve_fleet": 1})
    assert result["solver_status"] == "INFEASIBLE"
    assert any("Essential stop S4" in warning for warning in result["warnings"])


@pytest.mark.parametrize("config", [{"reserve_fleet": 30}, {"fleet_size": 3.2},
                                   {"demand_multiplier": float("nan")},
                                   {"weights": {"unknown": 1}}, {"solver_time_limit_seconds": 0}])
def test_invalid_configuration_is_explicit(routes, network, config):
    with pytest.raises(ValueError):
        optimize_plan(routes, network, {"R01": 100, "R02": 50}, config)
