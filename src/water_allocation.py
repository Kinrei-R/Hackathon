"""
Safe water allocation for dengue prevention.
Pure functions, deterministic, no network access.
"""

from __future__ import annotations

import math
from typing import Optional


def _safe_float(value, default=0.0):
    try:
        value = float(value)
        if not math.isfinite(value):
            return default
        return value
    except (TypeError, ValueError):
        return default


def _normalise(values):
    """
    Scale values into [0, 1].
    If all values are equal, return 1 for each.
    """
    values = list(values)

    if not values:
        return []

    lo = min(values)
    hi = max(values)

    if hi == lo:
        return [1.0] * len(values)

    return [(v - lo) / (hi - lo) for v in values]


def _distribute_with_caps(total, weights, caps):
    """
    Weighted water-filling allocation.

    Constraints:
      allocation_i <= demand_i
      sum(allocation_i) <= total water available

    Excess allocation from capped wards is redistributed
    proportionally among wards that still have unmet demand.
    """

    n = len(weights)

    allocation = [0.0] * n
    remaining = max(0.0, float(total))

    active = [
        i for i in range(n)
        if caps[i] > 0 and weights[i] > 0
    ]

    while remaining > 1e-9 and active:

        weight_sum = sum(weights[i] for i in active)

        if weight_sum <= 0:
            break

        saturated = []

        # Identify wards whose weighted share would exceed demand.
        for i in active:

            proposed = remaining * weights[i] / weight_sum

            room = caps[i] - allocation[i]

            if proposed >= room - 1e-9:
                saturated.append(i)

        if not saturated:

            # No ward reaches its demand cap.
            for i in active:
                allocation[i] += (
                    remaining * weights[i] / weight_sum
                )

            remaining = 0.0
            break

        # Fill capped wards, then redistribute remaining water.
        for i in saturated:

            room = max(0.0, caps[i] - allocation[i])

            allocation[i] += room
            remaining -= room

        remaining = max(0.0, remaining)

        active = [
            i for i in active
            if allocation[i] < caps[i] - 1e-9
        ]

    return allocation, remaining


def allocate_safe_water(
    wards,
    forecast_df,
    total_water_liters,
    days=3,
    liters_per_person_per_day=20,
    populations=None,
):
    """
    Allocate safe water among wards based on risk.

    Population mode:
        populations = {"WARD_ID": population, ...}

        Demand = population * liters/person/day * days.
        Allocation is capped by ward demand.

    Proxy mode:
        If population data is missing, allocate water according
        to risk weights without pretending demand is known.

    Risk score combines:
        - Forecast dengue cases
        - Population density
        - Waterlogging risk
        - Poor sanitation

    Returns a JSON-serializable dict.
    """

    total_water_liters = _safe_float(total_water_liters)
    days = _safe_float(days)
    liters_per_person_per_day = _safe_float(
        liters_per_person_per_day
    )

    if total_water_liters < 0:
        raise ValueError("Total water cannot be negative.")

    if days <= 0:
        raise ValueError("Days must be greater than zero.")

    if liters_per_person_per_day <= 0:
        raise ValueError(
            "Liters per person per day must be greater than zero."
        )

    ward_ids = sorted(wards.keys())

    if not ward_ids:
        return {
            "mode": "empty",
            "wards": [],
            "summary": {
                "available_liters": total_water_liters,
                "allocated_liters": 0,
                "unallocated_liters": total_water_liters,
            },
        }

    populations = populations or {}

    # Population mode is active only when all ward populations
    # are explicitly provided and valid.
    population_mode = (
        bool(populations)
        and all(
            ward_id in populations
            and _safe_float(populations[ward_id], -1) >= 0
            for ward_id in ward_ids
        )
    )

    # ---------------------------------------------------------
    # 1. Extract risk variables
    # ---------------------------------------------------------

    cases = []
    densities = []
    waterlogging = []
    sanitation = []

    for ward_id in ward_ids:

        ward = wards[ward_id]

        forecast = forecast_df.loc[ward_id]

        predicted_cases = _safe_float(
            forecast.get("expected", 0)
        )

        density = _safe_float(
            ward.get("density", 0)
        )

        wl = _safe_float(
            ward.get("wl", 0)
        )

        san = _safe_float(
            ward.get("san", 1)
        )

        # Keep scores in valid ranges.
        wl = min(1.0, max(0.0, wl))
        san = min(1.0, max(0.0, san))

        cases.append(max(0.0, predicted_cases))
        densities.append(max(0.0, density))
        waterlogging.append(wl)
        sanitation.append(san)

    # ---------------------------------------------------------
    # 2. Normalize factors
    # ---------------------------------------------------------

    cases_norm = _normalise(cases)
    density_norm = _normalise(densities)

    # ---------------------------------------------------------
    # 3. Calculate ward risk scores
    # ---------------------------------------------------------

    risk_scores = []

    for i in range(len(ward_ids)):

        # Forecast component:
        # baseline 0.4 prevents zero-case forecasts from
        # completely eliminating environmental risk.
        forecast_factor = (
            0.4 + 0.6 * cases_norm[i]
        )

        density_factor = (
            0.5 + 0.5 * density_norm[i]
        )

        waterlogging_factor = (
            1.0 + waterlogging[i]
        )

        sanitation_factor = (
            2.0 - sanitation[i]
        )

        risk = (
            forecast_factor
            * density_factor
            * waterlogging_factor
            * sanitation_factor
        )

        risk_scores.append(max(0.0, risk))

    # ---------------------------------------------------------
    # 4. Determine demand / allocation weights
    # ---------------------------------------------------------

    if population_mode:

        demands = [
            _safe_float(populations[w])
            * liters_per_person_per_day
            * days
            for w in ward_ids
        ]

        weights = [
            demands[i] * risk_scores[i]
            for i in range(len(ward_ids))
        ]

        allocations, unallocated = _distribute_with_caps(
            total_water_liters,
            weights,
            demands,
        )

        mode = "population_based"

    else:

        # No population data available.
        # Allocation is risk-weighted and is NOT demand-capped.
        weights = risk_scores[:]

        weight_sum = sum(weights)

        if weight_sum <= 0:
            weights = [1.0] * len(ward_ids)
            weight_sum = float(len(ward_ids))

        allocations = [
            total_water_liters * w / weight_sum
            for w in weights
        ]

        unallocated = 0.0

        demands = [None] * len(ward_ids)

        mode = "risk_proxy"

    # ---------------------------------------------------------
    # 5. Build ward-level result
    # ---------------------------------------------------------

    rows = []

    for i, ward_id in enumerate(ward_ids):

        allocated = allocations[i]

        if population_mode:

            demand = demands[i]

            shortage = max(0.0, demand - allocated)

            coverage = (
                100.0 * allocated / demand
                if demand > 0
                else 100.0
            )

        else:

            demand = None
            shortage = None
            coverage = None

        rows.append({
            "ward_id": ward_id,
            "city": wards[ward_id]["city"],
            "predicted_cases": round(cases[i], 3),
            "density": densities[i],
            "waterlogging": waterlogging[i],
            "sanitation": sanitation[i],
            "risk_score": round(risk_scores[i], 6),
            "risk_rank": None,
            "population": (
                _safe_float(populations[ward_id])
                if population_mode
                else None
            ),
            "demand_liters": (
                round(demand, 2)
                if demand is not None
                else None
            ),
            "allocated_liters": round(allocated, 2),
            "shortage_liters": (
                round(shortage, 2)
                if shortage is not None
                else None
            ),
            "coverage_pct": (
                round(coverage, 2)
                if coverage is not None
                else None
            ),
        })

    # Highest risk first.
    rows.sort(
        key=lambda r: (
            -r["risk_score"],
            r["ward_id"]
        )
    )

    for rank, row in enumerate(rows, 1):
        row["risk_rank"] = rank

    # ---------------------------------------------------------
    # 6. Summary
    # ---------------------------------------------------------

    allocated_total = sum(
        r["allocated_liters"] for r in rows
    )

    if population_mode:

        demand_total = sum(
            r["demand_liters"] for r in rows
        )

        shortage_total = sum(
            r["shortage_liters"] for r in rows
        )

        coverage_total = (
            100 * allocated_total / demand_total
            if demand_total > 0
            else 100
        )

    else:

        demand_total = None
        shortage_total = None
        coverage_total = None

    return {
        "mode": mode,
        "assumptions": {
            "days": days,
            "liters_per_person_per_day": (
                liters_per_person_per_day
            ),
            "population_data_available": population_mode,
            "risk_formula": (
                "(0.4 + 0.6*forecast_norm) "
                "* (0.5 + 0.5*density_norm) "
                "* (1+waterlogging) "
                "* (2-sanitation)"
            ),
        },
        "summary": {
            "available_liters": round(
                total_water_liters, 2
            ),
            "total_demand_liters": (
                round(demand_total, 2)
                if demand_total is not None
                else None
            ),
            "allocated_liters": round(
                allocated_total, 2
            ),
            "unallocated_liters": round(
                max(0.0, unallocated), 2
            ),
            "shortage_liters": (
                round(shortage_total, 2)
                if shortage_total is not None
                else None
            ),
            "coverage_pct": (
                round(coverage_total, 2)
                if coverage_total is not None
                else None
            ),
            "wards": len(rows),
        },
        "wards": rows,
    }
