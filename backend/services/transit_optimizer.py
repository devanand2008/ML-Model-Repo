"""Actual OR-Tools CP-SAT fleet allocation over validated synthetic route variants.

Pure dictionary contracts let the API persist input snapshots and re-evaluate a
whole plan before operator-approved simulation activation. No real dispatch occurs.
"""
from __future__ import annotations

import math
from copy import deepcopy
from typing import Any


DEFAULT_CONFIG = {
    "fleet_size": 28, "reserve_fleet": 4, "bus_capacity": 50,
    "max_headway_minutes": 30.0, "horizon_minutes": 60,
    "demand_multiplier": 1.0, "event_intensity": "none",
    "traffic_level": "current", "solver_time_limit_seconds": 5.0,
    "operating_cost_per_bus_hour_inr": 700.0,
    "unserved_penalty_inr_per_passenger": 250.0,
    "waiting_value_inr_per_passenger_minute": 2.0,
    "delay_value_inr_per_passenger_minute": 2.0,
    "allocation_change_penalty_inr_per_bus": 120.0,
    "variant_change_penalty_inr": 80.0,
    "weights": {"unserved": 1.0, "waiting": 1.0, "operating_cost": 1.0,
                "traffic_delay": 1.0, "stability": 1.0},
}

ASSUMPTIONS = [
    "Synthetic Salem-inspired network; variants and road segments are illustrative, not official routes.",
    "Input demand is route-level boarding demand for the configured horizon; scenario and event multipliers are applied once.",
    "Round-trip cycle = free-flow cycle x (1 + 0.5 x average segment congestion / 100); congestion is a synthetic or vision-derived score, not measured speed.",
    "Capacity = floor(buses x seats x horizon minutes / round-trip cycle); one boarding load per complete cycle, without assuming seat reuse.",
    "Uniform passenger arrivals: served passenger waiting time is half the headway; unserved demand is reported separately.",
    "Passenger delay uses half of round-trip congestion delay. All time, coverage and cost values are scenario estimates.",
    "Objective terms use configurable INR-equivalent penalties, rounded to paise for integer CP-SAT coefficients.",
    "Hard constraints enforce operational fleet, reserve, required stops, essential services and maximum headway; capacity shortfalls remain explicit.",
    "Activation is simulation-only and requires operator approval of the complete changed plan.",
]


def _number(value: Any, name: str, low: float = 0, high: float = 1e8) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return number


def normalize_config(config: dict | None = None) -> dict:
    """Validate solver inputs even when called outside Pydantic API schemas."""
    supplied = config or {}
    result = deepcopy(DEFAULT_CONFIG)
    result.update({key: value for key, value in supplied.items() if key != "weights"})
    result["weights"].update(supplied.get("weights") or {})
    for name, low, high in [("fleet_size", 1, 200), ("reserve_fleet", 0, 200),
                            ("bus_capacity", 1, 150), ("horizon_minutes", 15, 240)]:
        value = _number(result[name], name, low, high)
        if value != int(value):
            raise ValueError(f"{name} must be an integer")
        result[name] = int(value)
    if result["reserve_fleet"] > result["fleet_size"]:
        raise ValueError("reserve_fleet cannot exceed fleet_size")
    for name, low, high in [("max_headway_minutes", 1, 120),
                            ("demand_multiplier", 0, 3),
                            ("solver_time_limit_seconds", 0.01, 60)]:
        result[name] = _number(result[name], name, low, high)
    for name in ("operating_cost_per_bus_hour_inr", "unserved_penalty_inr_per_passenger",
                 "waiting_value_inr_per_passenger_minute", "delay_value_inr_per_passenger_minute",
                 "allocation_change_penalty_inr_per_bus", "variant_change_penalty_inr"):
        result[name] = _number(result[name], name, 0, 100000)
    if result["event_intensity"] not in {"none", "moderate", "high"}:
        raise ValueError("event_intensity must be none, moderate or high")
    if result["traffic_level"] not in {"current", "low", "medium", "high"}:
        raise ValueError("traffic_level must be current, low, medium or high")
    unknown = set(result["weights"]) - set(DEFAULT_CONFIG["weights"])
    if unknown:
        raise ValueError(f"Unknown objective weights: {', '.join(sorted(unknown))}")
    result["weights"] = {key: _number(value, f"weight {key}", 0, 100)
                         for key, value in result["weights"].items()}
    if not any(result["weights"].values()):
        raise ValueError("At least one objective weight must be positive")
    return result


def _items(value: list | dict | None) -> list[dict]:
    if isinstance(value, dict):
        return [{"id": key, **item} for key, item in value.items()]
    return value or []


def _prepared(routes: list[dict], network: dict, demand_by_route: dict, config: dict):
    if not routes:
        raise ValueError("At least one route is required")
    if len({str(r["id"]) for r in routes}) != len(routes):
        raise ValueError("Route IDs must be unique")
    stops = {str(stop["id"]): stop for stop in _items(network.get("stops"))}
    nodes = set(stops) | {str(node["id"]) for node in _items(network.get("nodes"))}
    segments = {str(segment["id"]): segment for segment in _items(network.get("segments"))}
    if not stops or not segments:
        raise ValueError("Network requires stops and road segments for route validation")
    essentials = {stop_id for stop_id, stop in stops.items() if stop.get("essential", False)}
    essentials.update(str(s) for s in network.get("essential_stop_ids", []))
    unknown_stops = essentials - set(stops)
    if unknown_stops:
        raise ValueError(f"Unknown essential stops: {', '.join(sorted(unknown_stops))}")
    demands, variants, rejected = {}, {}, []
    event_factor = {"none": 1.0, "moderate": 1.10, "high": 1.25}[config["event_intensity"]]
    for route in routes:
        rid = str(route["id"])
        raw_demand = _number(demand_by_route.get(rid, 0), f"{rid} demand", 0, 1000000)
        demands[rid] = math.ceil(raw_demand * config["demand_multiplier"] * event_factor)
        choices = _items(route.get("variants"))
        current_id = str(route.get("current_variant_id", "existing"))
        current = next((v for v in choices if str(v["id"]) == current_id), None)
        required = set(str(s) for s in route.get("required_stop_ids", (current or {}).get("stop_ids", [])))
        valid = []
        seen_ids = set()
        for variant in choices:
            vid = str(variant["id"])
            try:
                if vid in seen_ids:
                    raise ValueError("duplicate variant ID")
                seen_ids.add(vid)
                served = [str(s) for s in variant.get("stop_ids", [])]
                path = [str(s) for s in variant.get("node_ids", served)]
                segment_ids = [str(s) for s in variant.get("segment_ids", [])]
                if len(path) < 2 or len(segment_ids) != len(path) - 1:
                    raise ValueError("path must contain a road segment between every adjacent node")
                if any(node not in nodes for node in path) or any(stop not in stops for stop in served):
                    raise ValueError("path references an unknown node or stop")
                if not required.issubset(served):
                    raise ValueError("variant omits a required route stop")
                position = 0
                for stop in served:
                    try:
                        position = path.index(stop, position) + 1
                    except ValueError as exc:
                        raise ValueError("served stops must appear in path order") from exc
                scores = []
                for left, right, sid in zip(path, path[1:], segment_ids):
                    segment = segments.get(sid)
                    if segment is None:
                        raise ValueError(f"unknown segment {sid}")
                    start = str(segment.get("from_stop", segment.get("from_node", "")))
                    end = str(segment.get("to_stop", segment.get("to_node", "")))
                    connects = (start == left and end == right) or (
                        segment.get("bidirectional", False) and start == right and end == left)
                    if not connects:
                        raise ValueError(f"segment {sid} does not connect {left} to {right}")
                    score = _number(segment.get("congestion_score", 0), f"segment {sid} congestion", 0, 100)
                    level = config["traffic_level"]
                    if level == "low":
                        score *= 0.45
                    elif level == "medium":
                        score *= 0.8
                    elif level == "high":
                        score = min(100, score * 1.35 + 10)
                    scores.append(score)
                free_cycle = _number(variant.get("cycle_minutes"), f"{rid}/{vid} cycle_minutes", 1, 1000)
                congestion = sum(scores) / len(scores)
                valid.append({**variant, "id": vid, "stop_ids": served, "node_ids": path,
                              "segment_ids": segment_ids, "free_cycle_minutes": free_cycle,
                              "cycle_minutes": free_cycle * (1 + 0.5 * congestion / 100),
                              "congestion_score": congestion})
            except ValueError as exc:
                rejected.append(f"{rid}/{vid}: {exc}")
        variants[rid] = valid
    return variants, demands, essentials, rejected


def _option(route: dict, variant: dict, buses: int, demand: int, config: dict) -> dict:
    cycle = variant["cycle_minutes"]
    headway = cycle / buses if buses else None
    capacity = math.floor(buses * config["bus_capacity"] * config["horizon_minutes"] / cycle + 1e-9)
    served = min(demand, capacity)
    unserved = demand - served
    wait = headway / 2 if buses else 0.0
    delay = (cycle - variant["free_cycle_minutes"]) / 2
    operating = buses * config["operating_cost_per_bus_hour_inr"] * config["horizon_minutes"] / 60
    changed = abs(buses - int(route.get("current_buses", 0)))
    variant_changed = str(variant["id"]) != str(route.get("current_variant_id", "existing"))
    terms = {
        "unserved": unserved * config["unserved_penalty_inr_per_passenger"],
        "waiting": served * wait * config["waiting_value_inr_per_passenger_minute"],
        "operating_cost": operating,
        "traffic_delay": served * delay * config["delay_value_inr_per_passenger_minute"],
        "stability": changed * config["allocation_change_penalty_inr_per_bus"] +
                     int(variant_changed) * config["variant_change_penalty_inr"],
    }
    weighted = {key: value * config["weights"][key] for key, value in terms.items()}
    objective_paise = round(sum(weighted.values()) * 100)
    return {
        "route_id": str(route["id"]), "buses": buses, "allocated_buses": buses,
        "variant_id": variant["id"], "variant_name": variant.get("name", variant["id"]),
        "stop_ids": variant["stop_ids"] if buses else [], "segment_ids": variant["segment_ids"] if buses else [],
        "demand": demand, "capacity": capacity, "served_demand": served,
        "unserved_demand": unserved, "capacity_shortfall": unserved,
        "coverage_pct": 100.0 * served / demand if demand else 100.0,
        "headway_minutes": headway, "frequency_per_hour": 60 / headway if headway else 0.0,
        "average_wait_minutes": wait if buses else None,
        "passenger_wait_minutes": served * wait,
        "passenger_delay_minutes": served * delay,
        "traffic_delay_minutes": delay, "cycle_minutes": cycle,
        "free_cycle_minutes": variant["free_cycle_minutes"], "congestion_score": variant["congestion_score"],
        "operating_cost_inr": operating, "allocation_change": changed,
        "objective_terms_inr": weighted, "objective_cost_inr": objective_paise / 100,
        "objective_paise": objective_paise,
    }


def _service_min(route: dict, variant: dict, config: dict) -> int:
    minimum = _number(route.get("min_buses", 1), f"{route['id']} minimum buses", 0, 200)
    if minimum != int(minimum):
        raise ValueError("min_buses must be an integer")
    essential_min = 1 if route.get("essential", True) else 0
    headway_min = math.ceil(variant["cycle_minutes"] / _max_headway(route, config) - 1e-9)
    return max(int(minimum), essential_min, headway_min)


def _max_headway(route: dict, config: dict) -> float:
    return min(config["max_headway_minutes"],
               _number(route.get("max_headway_minutes", config["max_headway_minutes"]),
                       f"{route['id']} maximum headway", 1, 120))


def _evaluation(routes: list[dict], rows: list[dict], essentials: set, config: dict,
                warnings: list[str], demands: dict) -> dict:
    allocated = sum(row["buses"] for row in rows)
    demand = sum(demands.values())
    served = sum(row["served_demand"] for row in rows)
    operational = config["fleet_size"] - config["reserve_fleet"]
    covered = {sid for row in rows if row["buses"] for sid in row["stop_ids"]}
    by_id = {row["route_id"]: row for row in rows}
    constraints = [{"name": "Operational fleet and reserve", "satisfied": allocated <= operational,
                    "detail": f"{allocated} allocated <= {operational} operational; {config['reserve_fleet']} reserved"},
                   {"name": "Essential stops served", "satisfied": essentials.issubset(covered),
                    "detail": "All essential stops served" if essentials.issubset(covered) else
                              "Unserved essential stops: " + ", ".join(sorted(essentials - covered))}]
    for route in routes:
        rid = str(route["id"])
        row = by_id.get(rid)
        minimum = max(int(route.get("min_buses", 1)), 1 if route.get("essential", True) else 0)
        constraints.append({"name": f"{rid} minimum service", "satisfied": bool(row and row["buses"] >= minimum),
                            "detail": f"Requires at least {minimum} bus(es)"})
        constraints.append({"name": f"{rid} maximum headway",
                            "satisfied": bool(row and row["headway_minutes"] is not None and
                                              row["headway_minutes"] <= _max_headway(route, config) + 1e-7),
                            "detail": f"Maximum {_max_headway(route, config):g} minutes"})
    constraints.append({"name": "Validated road variants", "satisfied": len(rows) == len(routes),
                        "detail": "Each selected path uses contiguous known road segments and required stops"})
    totals = {
        "fleet_size": config["fleet_size"], "reserve_fleet": config["reserve_fleet"],
        "operational_fleet": operational, "allocated_buses": allocated,
        "unused_operational_buses": operational - allocated,
        "forecast_demand": demand, "served_demand": served,
        "capacity": sum(row["capacity"] for row in rows), "unserved_demand": demand - served,
        "capacity_shortfall": demand - served,
        "demand_coverage_pct": 100 * served / demand if demand else 100.0,
        "average_wait_minutes": sum(row["passenger_wait_minutes"] for row in rows) / served if served else None,
        "average_delay_minutes": sum(row["passenger_delay_minutes"] for row in rows) / served if served else None,
        "operating_cost_inr": sum(row["operating_cost_inr"] for row in rows),
        "fleet_utilization_pct": 100 * allocated / operational if operational else 0.0,
        "allocation_changes": sum(row["allocation_change"] for row in rows),
        "objective_cost_inr": sum(row["objective_paise"] for row in rows) / 100,
        "passenger_wait_minutes": sum(row["passenger_wait_minutes"] for row in rows),
        "passenger_delay_minutes": sum(row["passenger_delay_minutes"] for row in rows),
    }
    for row in rows:
        for key, value in list(row.items()):
            if isinstance(value, float):
                row[key] = round(value, 4)
        row.pop("objective_paise", None)
    totals = {key: round(value, 4) if isinstance(value, float) else value for key, value in totals.items()}
    return {"routes": rows, "totals": totals, "metrics": totals,
            "feasible": all(item["satisfied"] for item in constraints),
            "constraints": constraints, "warnings": warnings,
            "assumptions": ASSUMPTIONS, "data_source": "SYNTHETIC SCENARIO EVALUATION"}


def evaluate_plan(routes: list[dict], network: dict, demand_by_route: dict,
                  config: dict | None = None, allocations: dict | list | None = None) -> dict:
    """Calculate identical baseline/optimized metrics and validate the entire plan.

    allocations maps route IDs to {buses, variant_id}, or is solver result.rows.
    Missing allocations default to current service. Invalid paths are never accepted.
    """
    normalized = normalize_config(config)
    variants, demands, essentials, rejected = _prepared(routes, network, demand_by_route, normalized)
    if isinstance(allocations, list):
        allocations = {str(row["route_id"]): row for row in allocations}
    allocations = allocations or {}
    unknown = set(allocations) - {str(route["id"]) for route in routes}
    if unknown:
        raise ValueError(f"Unknown allocation routes: {', '.join(sorted(unknown))}")
    rows, warnings = [], ["Excluded invalid variant: " + item for item in rejected]
    for route in routes:
        rid = str(route["id"])
        selected = allocations.get(rid, {})
        buses = _number(selected.get("buses", selected.get("allocated_buses", route.get("current_buses", 0))),
                        f"{rid} buses", 0, 200)
        if buses != int(buses):
            raise ValueError(f"{rid} buses must be an integer")
        vid = str(selected.get("variant_id", route.get("current_variant_id", "existing")))
        variant = next((item for item in variants[rid] if item["id"] == vid), None)
        if variant is None:
            warnings.append(f"{rid}: selected variant {vid} is invalid or unavailable")
            continue
        rows.append(_option(route, variant, int(buses), demands[rid], normalized))
    return _evaluation(routes, rows, essentials, normalized, warnings, demands)


validate_plan = evaluate_plan


def _comparison(baseline: dict, optimized: dict) -> dict:
    comparisons = {}
    for name, lower_is_better in [("capacity_shortfall", True), ("average_wait_minutes", True),
                                  ("average_delay_minutes", True), ("operating_cost_inr", True),
                                  ("demand_coverage_pct", False), ("fleet_utilization_pct", False),
                                  ("objective_cost_inr", True)]:
        before, after = baseline["totals"][name], optimized["totals"][name]
        delta = after - before if before is not None and after is not None else None
        improvement = ((-delta if lower_is_better else delta) / before * 100
                       if delta is not None and before else None)
        comparisons[name] = {"baseline": before, "optimized": after,
                             "delta": round(delta, 4) if delta is not None else None,
                             "improvement_pct": round(improvement, 4) if improvement is not None else None}
    return comparisons


def optimize_plan(routes: list[dict], network: dict, demand_by_route: dict,
                  config: dict | None = None) -> dict:
    """Solve a real finite-choice CP-SAT model; never substitute invented results."""
    normalized = normalize_config(config)
    variants, demands, essentials, rejected = _prepared(routes, network, demand_by_route, normalized)
    baseline = evaluate_plan(routes, network, demand_by_route, normalized)
    operational = normalized["fleet_size"] - normalized["reserve_fleet"]
    warnings = ["Excluded invalid variant: " + item for item in rejected]
    common = {"baseline": baseline, "config": normalized, "assumptions": ASSUMPTIONS,
              "warnings": warnings, "data_source": "OPTIMIZATION RESULT",
              "solver": "Google OR-Tools CP-SAT", "routes": [], "comparison": {},
              "time_limit_seconds": normalized["solver_time_limit_seconds"]}
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        return {**common, "feasible": False, "solver_status": "UNAVAILABLE",
                "warnings": warnings + ["OR-Tools is not installed; install backend requirements."],
                "totals": {}, "metrics": {}, "constraints": [], "wall_time_seconds": 0}
    model = cp_model.CpModel()
    options, variables = {}, {}
    minimum_required = 0
    for route in routes:
        rid = str(route["id"])
        options[rid], variables[rid] = [], []
        minimums = [_service_min(route, variant, normalized) for variant in variants[rid]]
        if not minimums:
            warnings.append(f"{rid}: no validated route variant can serve its required stops")
        else:
            minimum_required += min(minimums)
        for variant, minimum in zip(variants[rid], minimums):
            for buses in range(minimum, operational + 1):
                row = _option(route, variant, buses, demands[rid], normalized)
                choice = model.new_bool_var(f"{rid}_{variant['id']}_{buses}")
                options[rid].append(row)
                variables[rid].append(choice)
        model.add(sum(variables[rid]) == 1)
    model.add(sum(row["buses"] * choice for rid in options
                  for row, choice in zip(options[rid], variables[rid])) <= operational)
    for stop_id in essentials:
        choices = [choice for rid in options for row, choice in zip(options[rid], variables[rid])
                   if stop_id in row["stop_ids"] and row["buses"] > 0]
        model.add(sum(choices) >= 1)
        if not choices:
            warnings.append(f"Essential stop {stop_id} has no valid service option")
    model.minimize(sum(row["objective_paise"] * choice for rid in options
                       for row, choice in zip(options[rid], variables[rid])))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = normalized["solver_time_limit_seconds"]
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 42
    status = solver.solve(model)
    status_name = solver.status_name(status)
    common.update(solver_status=status_name, wall_time_seconds=round(solver.wall_time, 4),
                  minimum_required_buses=minimum_required)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if minimum_required > operational:
            warnings.append(f"Maximum headway requires at least {minimum_required} buses; only {operational} operational buses remain after reserving {normalized['reserve_fleet']}.")
        if status == cp_model.UNKNOWN:
            warnings.append("Solver reached its limit without a feasible plan; increase the time limit or revise constraints.")
        elif status == cp_model.INFEASIBLE:
            warnings.append("No plan satisfies fleet, reserve, maximum headway and essential-stop constraints; revise fleet or service requirements.")
        else:
            warnings.append("Solver model is invalid: " + model.validate())
        return {**common, "feasible": False, "routes": [], "totals": {}, "metrics": {},
                "constraints": [], "objective_value_inr": None}
    selected = [deepcopy(row) for rid in options for row, choice in zip(options[rid], variables[rid])
                if solver.value(choice)]
    evaluation = _evaluation(routes, selected, essentials, normalized, warnings, demands)
    if not evaluation["feasible"]:
        return {**common, "feasible": False, "solver_status": "VALIDATION_FAILED",
                "routes": [], "totals": {}, "metrics": {}, "constraints": evaluation["constraints"],
                "warnings": warnings + ["Whole-plan verification failed; no recommendation may be activated."]}
    baseline_rows = {row["route_id"]: row for row in baseline["routes"]}
    for row in evaluation["routes"]:
        original = baseline_rows.get(row["route_id"])
        reasons = []
        if original:
            row["previous_buses"] = original["buses"]
            row["previous_variant_id"] = original["variant_id"]
            if row["buses"] > original["buses"]:
                reasons.append(f"Add {row['buses'] - original['buses']} bus(es) to improve modeled demand coverage and headway")
            elif row["buses"] < original["buses"]:
                reasons.append(f"Release {original['buses'] - row['buses']} bus(es) while retaining required service")
            if row["variant_id"] != original["variant_id"]:
                reasons.append("Use a validated alternative to lower the weighted delay, waiting and shortfall objective")
            row["changed"] = row["buses"] != original["buses"] or row["variant_id"] != original["variant_id"]
        else:
            row["changed"] = True
            reasons.append("Replace unavailable baseline with a validated service variant")
        if row["unserved_demand"]:
            reasons.append(f"{row['unserved_demand']} forecast boardings remain unserved under the fleet constraints")
        row["reason"] = "; ".join(reasons) if reasons else "Retain current allocation; it fits the constrained weighted plan"
    return {**common, **evaluation, "data_source": "OPTIMIZATION RESULT",
            "optimized": evaluation, "comparison": _comparison(baseline, evaluation),
            "objective_value_inr": round(solver.objective_value / 100, 4),
            "objective_bound_inr": round(solver.best_objective_bound / 100, 4)}
