# Route optimization and scenario assumptions

`backend/services/transit_optimizer.py` runs Google OR-Tools CP-SAT. It enumerates
each validated route variant and integral bus allocation, selects exactly one
option per route, and minimizes the weighted cost. Results report `OPTIMAL`,
`FEASIBLE`, `INFEASIBLE`, `UNKNOWN`, or dependency/model failure. A time-limited
`FEASIBLE` result is valid without being claimed globally optimal. No heuristic
or hardcoded recommendation replaces a missing solver.

The reproducible Salem-inspired road graph is illustrative. Every chosen variant
must follow known, contiguous graph segments and serve the existing route's
required stops. Reverse traversal requires an explicit `bidirectional: true`
flag; unspecified road segments follow their recorded endpoint direction.
Parallel alternative corridors are explicit graph segments;
they do not imply authorization or verified real-world road suitability.

## Hard constraints

- Sum of allocations cannot exceed `fleet_size - reserve_fleet`.
- Every essential route retains at least its minimum bus service.
- Every essential stop is served by a selected variant.
- Buses per selected variant must be at least the ceiling of its scenario cycle
  time divided by maximum headway. A stricter route-specific limit also applies.
- Only graph-validated variants and integral allocations are selectable.

Capacity is not treated as unlimited. A shortfall is an explicit unserved-demand
output and penalized objective term. If fleet/headway/essential-service constraints
cannot coexist, the response contains no proposed routes and explains the minimum
fleet requirement or missing essential-stop coverage.

## Units and calculations

Demand input is forecast boarding demand for the configured horizon, not people
detected on CCTV. Seat capacity defaults to 50, configurable globally. Free-flow
round-trip cycle times are supplied by the synthetic route dataset.

```
scenario demand = ceil(forecast boardings x demand multiplier x event multiplier)
scenario cycle minutes = free-flow cycle x (1 + 0.5 x mean segment score / 100)
headway minutes = scenario cycle minutes / allocated buses
capacity boardings = floor(buses x seats x horizon minutes / scenario cycle)
served boardings = min(demand, capacity)
unserved boardings = demand - served
frequency departures/hour = 60 / headway
waiting passenger-minutes = served boardings x headway / 2
delay passenger-minutes = served boardings x (scenario cycle - free-flow cycle) / 2
operating INR = buses x cost per bus-hour x horizon minutes / 60
```

Capacity conservatively permits one boarding load per full cycle; it does not
assume seat turnover along the route. Waiting assumes uniform arrivals and applies
to served passengers. Unserved demand is separately reported; it is not hidden in
the average wait. Neither congestion score nor ordinary object detection supplies
a calibrated physical speed measurement. Costs, waits and delays are estimates.

## Configurable objective

Every term is expressed in INR-equivalent units before applying its dimensionless
weight. CP-SAT receives integer paise coefficients rounded to the nearest paise.

| Term | Default conversion | Default weight |
|---|---|---|
| Unserved boardings | INR 250 per unserved passenger | 1 |
| Waiting | INR 2 per served passenger-minute | 1 |
| Operating cost | INR 700 per bus-hour | 1 |
| Traffic delay | INR 2 per served passenger-minute | 1 |
| Stability | INR 120 per absolute bus allocation change and INR 80 per variant change | 1 |

These are transparent synthetic planning assumptions, not measured local fares,
public-sector budgets, or claimed social valuations. Both weights and conversions
can be supplied in the API configuration. A route may retain unmet demand when
reducing it would violate fleet constraints or cost more under selected weights.

## What-if scenarios and fair comparison

Demand multipliers are applied exactly once to input forecasts. Event multipliers
are none=1.0, moderate=1.10, high=1.25. Traffic current uses stored segment scores;
low multiplies them by 0.45, medium by 0.8, high uses
`min(100, score x 1.35 + 10)`. These factors retain different corridor conditions.

The current allocation and solver allocation are evaluated with identical horizon,
demand, event, traffic, bus capacity and cost assumptions. Comparison values are
calculated from these evaluations, including changes that worsen individual metrics
while improving the selected weighted objective. Current plans that violate a
what-if fleet limit are marked infeasible; their metrics remain a descriptive
comparison and do not authorize activation.

## Integration contracts

`optimize_plan(routes, network, demand_by_route, config)` returns status, selected
`routes`, `totals` (`metrics` alias), baseline evaluation, comparison, constraint
checks, reasons, warnings, objective bound and solver runtime. Route rows include
`route_id`, `buses`, `variant_id`, actual computed headway, capacity and shortfall.

`evaluate_plan(routes, network, demand_by_route, config, allocations=None)` accepts
an allocation dictionary or solver route rows and recalculates whole-plan checks.
`validate_plan` is its alias. No function mutates source network or route inputs.

Operator approval belongs to the API/database workflow. Simulation activation
must require approval of all changed recommendations belonging to the run and
activate the complete plan in one transaction. Revalidate the whole plan from its
stored configuration and network/demand snapshot before committing it. Applying
individual bus additions before corresponding releases could violate fleet limits.

Solver behavior follows the [official CP-SAT status documentation](https://developers.google.com/optimization/cp/cp_solver).
