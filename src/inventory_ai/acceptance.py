"""Воспроизводимая приёмочная проверка и сквозной складской сценарий."""

import json
from pathlib import Path
from typing import Any

from inventory_ai.forecasting import forecast_demand
from inventory_ai.questions import answer_question

ACCEPTANCE_PATH = (
    Path(__file__).resolve().parents[2] / "acceptance_questions.json"
)
ACCEPTANCE_HORIZON_DAYS = 30


def load_acceptance_cases() -> list[dict[str, Any]]:
    """Загрузить версионируемый набор контрольных вопросов."""
    return json.loads(ACCEPTANCE_PATH.read_text(encoding="utf-8"))


def evaluate_acceptance(
    context: dict[str, Any],
) -> dict[str, Any]:
    """Сравнить фактический разбор каждого вопроса с ожиданиями."""
    checks = []
    for case in load_acceptance_cases():
        result = answer_question(case["question"], context)
        parsed = result[0]
        mismatches = {
            field: {"expected": expected, "actual": parsed.get(field)}
            for field, expected in case["expected"].items()
            if parsed.get(field) != expected
        }
        checks.append({
            "id": case["id"],
            "question": case["question"],
            "expected": case["expected"],
            "actual": {
                field: parsed.get(field) for field in case["expected"]
            },
            "passed": not mismatches,
            "mismatches": mismatches,
            "answer": result[2],
        })
    passed = sum(check["passed"] for check in checks)
    return {
        "passed": passed,
        "total": len(checks),
        "all_passed": passed == len(checks),
        "checks": checks,
    }


def build_end_to_end_scenario(history: dict[str, Any]) -> dict[str, Any]:
    """Показать путь от состояния склада до бюджета закупки."""
    forecasts = [
        forecast_demand(history, sku, ACCEPTANCE_HORIZON_DAYS)
        for sku in sorted(history["weekly_consumption"])
    ]
    risks = [
        item["sku"] for item in forecasts
        if item["current_stock"] < item["forecast_demand"]
    ]
    plan = [
        {
            "sku": item["sku"],
            "qty": item["recommended_qty"],
            "unit": item["unit"],
            "cost": item["estimated_cost"],
        }
        for item in forecasts if item["recommended_qty"] > 0
    ]
    return {
        "as_of": history["as_of"],
        "horizon_days": ACCEPTANCE_HORIZON_DAYS,
        "stock_state": [
            {
                "sku": item["sku"],
                "current_stock": item["current_stock"],
                "incoming_qty": item["incoming_qty"],
                "unit": item["unit"],
            }
            for item in forecasts
        ],
        "forecast": [
            {
                "sku": item["sku"],
                "forecast_demand": item["forecast_demand"],
                "unit": item["unit"],
            }
            for item in forecasts
        ],
        "deficit_risk_without_incoming": risks,
        "purchase_plan": plan,
        "budget": round(sum(item["cost"] for item in plan), 2),
        "limitations": [
            "Риск дефицита сравнивает прогноз с текущим остатком без поставок.",
            "В расчёт включены только SKU с историей расхода.",
            "Автоматическое размещение заказа не выполняется.",
        ],
    }
