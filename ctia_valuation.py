"""CTIA v5.1 grading + research valuation helpers.

CTIA defines the grading criteria/matrix. It does NOT define monetary
multipliers. The valuation equation used by this project is:

    estimated_value = market_baseline * research_grade_factor

Research grade factors should be calibrated from real sold/transaction data.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any, Iterable, Mapping, Optional


PRIMARY_GRADE_ORDER = ["AA", "A+", "A", "B+", "B", "C+", "C", "D+", "D", "E"]

# CTIA v5.1 Table 3.1-1 represented as lookup rules.
CTIA_PRIMARY_GRADE_MATRIX: dict[str, dict[str, Any]] = {
    "AA": {"cosmetic": ["A"], "functional": [1], "battery": [1], "customer_lock": [1], "enterprise_lock": [1], "operator_lock": [1, 2], "rf": [6]},
    "A+": {"cosmetic": ["A"], "functional": [1], "battery": [1], "customer_lock": [1], "enterprise_lock": [1], "operator_lock": [1, 2], "rf": [1, 2, 4, 6]},
    "A": {"cosmetic": ["A"], "functional": [1, 2], "battery": [1], "customer_lock": [1], "enterprise_lock": [1], "operator_lock": [1, 2], "rf": [1, 2, 4, 6]},
    "B+": {"cosmetic": ["B"], "functional": [1, 2], "battery": [1, 2], "customer_lock": [1], "enterprise_lock": [1], "operator_lock": [1, 2], "rf": [1, 2, 4, 6]},
    "B": {"cosmetic": ["B"], "functional": [1, 2, 3], "battery": [1, 2], "customer_lock": [1], "enterprise_lock": [1], "operator_lock": [1, 2], "rf": [1, 2, 4, 6]},
    "C+": {"cosmetic": ["C"], "functional": [1, 2], "battery": [1, 2, 3], "customer_lock": [1], "enterprise_lock": [1], "operator_lock": [1, 2, 3], "rf": [1, 2, 4, 6]},
    "C": {"cosmetic": ["C"], "functional": [1, 2, 3], "battery": [1, 2, 3], "customer_lock": [1], "enterprise_lock": [1], "operator_lock": [1, 2, 3], "rf": [1, 2, 4, 6]},
    "D+": {"cosmetic": ["D"], "functional": [1, 2], "battery": [1, 2, 3], "customer_lock": [1], "enterprise_lock": [1], "operator_lock": [1, 2, 3], "rf": "any"},
    "D": {"cosmetic": ["D"], "functional": [1, 2, 3, 4, 5, 6], "battery": [3], "customer_lock": [1], "enterprise_lock": [1], "operator_lock": [1, 2, 3], "rf": "any"},
    "E": {"cosmetic": ["E"], "functional": "any", "battery": [3], "customer_lock": "any", "enterprise_lock": "any", "operator_lock": "any", "rf": "any"},
}

# DEMO ONLY. These are project/research assumptions, NOT CTIA values.
DEFAULT_RESEARCH_GRADE_FACTORS = {
    "AA": 1.00, "A+": 0.97, "A": 0.93, "B+": 0.88, "B": 0.82,
    "C+": 0.74, "C": 0.68, "D+": 0.56, "D": 0.45, "E": 0.25,
}


@dataclass(frozen=True)
class CTIAResult:
    cosmetic_grade: str
    functional_class: int
    battery_type: Optional[int]
    customer_lock: Optional[int]
    enterprise_lock: Optional[int]
    operator_lock: Optional[int]
    rf_status: Optional[int]
    primary_grade: Optional[str]


def battery_type(health_percent: Optional[float]) -> Optional[int]:
    """CTIA v5.1 Table 2.8-4."""
    if health_percent is None:
        return None
    h = float(health_percent)
    if h >= 80:
        return 1
    if h >= 70:
        return 2
    return 3


def functional_class(power_on: Optional[bool], display_failure: str = "unverified", other_failure: str = "unverified") -> int:
    """CTIA v5.1 Table 2.8-3."""
    if power_on is None:
        return 9
    if power_on is False:
        return 8
    d = (display_failure or "unverified").strip().lower()
    o = (other_failure or "unverified").strip().lower()
    if d == "inoperable":
        return 7
    mapping = {
        ("none", "none"): 1,
        ("minor", "none"): 2,
        ("minor", "minor"): 3,
        ("minor", "major"): 4,
        ("major", "minor"): 5,
        ("major", "major"): 6,
    }
    return mapping.get((d, o), 9)


def _allowed(value: Optional[int], rule: Any) -> bool:
    if rule == "any":
        return True
    if value is None:
        return False
    return value in rule


def primary_grade(
    cosmetic_grade: str,
    functional: int,
    battery: Optional[int],
    customer_lock: Optional[int],
    enterprise_lock: Optional[int],
    operator_lock: Optional[int],
    rf_status: Optional[int],
) -> Optional[str]:
    """Apply CTIA v5.1 Table 3.1-1, highest matching grade first."""
    c = (cosmetic_grade or "").upper().strip()
    for grade in PRIMARY_GRADE_ORDER:
        rule = CTIA_PRIMARY_GRADE_MATRIX[grade]
        if c not in rule["cosmetic"]:
            continue
        if not _allowed(functional, rule["functional"]):
            continue
        if not _allowed(battery, rule["battery"]):
            continue
        if not _allowed(customer_lock, rule["customer_lock"]):
            continue
        if not _allowed(enterprise_lock, rule["enterprise_lock"]):
            continue
        if not _allowed(operator_lock, rule["operator_lock"]):
            continue
        if not _allowed(rf_status, rule["rf"]):
            continue
        return grade
    return None


def grade_device(
    cosmetic_grade: str,
    power_on: Optional[bool],
    display_failure: str,
    other_failure: str,
    battery_health: Optional[float],
    customer_lock: Optional[int] = 1,
    enterprise_lock: Optional[int] = 1,
    operator_lock: Optional[int] = 1,
    rf_status: Optional[int] = 1,
) -> CTIAResult:
    f = functional_class(power_on, display_failure, other_failure)
    b = battery_type(battery_health)
    g = primary_grade(cosmetic_grade, f, b, customer_lock, enterprise_lock, operator_lock, rf_status)
    return CTIAResult(cosmetic_grade.upper(), f, b, customer_lock, enterprise_lock, operator_lock, rf_status, g)


def estimate_value(market_baseline: float, grade: str, grade_factors: Optional[Mapping[str, float]] = None) -> dict[str, Any]:
    """Research equation: V = V_market * k_grade. k_grade is NOT defined by CTIA."""
    factors = dict(grade_factors or DEFAULT_RESEARCH_GRADE_FACTORS)
    factor = factors.get(grade)
    if factor is None:
        return {"estimated_value": None, "market_baseline": float(market_baseline), "grade": grade, "grade_factor": None}
    return {
        "estimated_value": round(float(market_baseline) * float(factor), 2),
        "market_baseline": round(float(market_baseline), 2),
        "grade": grade,
        "grade_factor": float(factor),
    }


def estimate_range(low_market: float, high_market: float, grade: str, grade_factors: Optional[Mapping[str, float]] = None) -> dict[str, Any]:
    factors = dict(grade_factors or DEFAULT_RESEARCH_GRADE_FACTORS)
    factor = factors.get(grade)
    if factor is None:
        return {"estimated_low": None, "estimated_high": None, "grade_factor": None}
    return {
        "estimated_low": round(float(low_market) * float(factor), 2),
        "estimated_high": round(float(high_market) * float(factor), 2),
        "grade_factor": float(factor),
    }


def calculate_grade_factors(records: Iterable[Mapping[str, Any]], reference_grade: str = "A") -> dict[str, float]:
    """Derive k_g = median(sale price | g) / median(sale price | reference grade)."""
    grouped: dict[str, list[float]] = {}
    for row in records:
        grade = str(row["grade"]).upper().strip()
        price = float(row["sale_price"])
        if price > 0:
            grouped.setdefault(grade, []).append(price)
    if reference_grade not in grouped:
        raise ValueError(f"No transactions for reference grade {reference_grade}.")
    ref = median(grouped[reference_grade])
    return {g: round(median(prices) / ref, 4) for g, prices in grouped.items()}


def full_valuation(
    market_baseline: float,
    cosmetic_grade: str,
    power_on: Optional[bool],
    display_failure: str,
    other_failure: str,
    battery_health: Optional[float],
    customer_lock: Optional[int] = 1,
    enterprise_lock: Optional[int] = 1,
    operator_lock: Optional[int] = 1,
    rf_status: Optional[int] = 1,
    grade_factors: Optional[Mapping[str, float]] = None,
) -> dict[str, Any]:
    result = grade_device(cosmetic_grade, power_on, display_failure, other_failure, battery_health,
                          customer_lock, enterprise_lock, operator_lock, rf_status)
    value = estimate_value(market_baseline, result.primary_grade, grade_factors) if result.primary_grade else {
        "estimated_value": None, "market_baseline": float(market_baseline), "grade": None, "grade_factor": None
    }
    return {**result.__dict__, **value}
