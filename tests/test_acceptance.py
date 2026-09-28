"""Контрольные вопросы и сквозной сценарий приёмки MVP."""

import json
from pathlib import Path
from typing import Any

import pytest

from inventory_ai.acceptance import (
    build_end_to_end_scenario, load_acceptance_cases,
)
from inventory_ai.questions import answer_question

DATA = json.loads(
    (Path(__file__).resolve().parents[1] / "dataset.json").read_text()
)
CASES = load_acceptance_cases()


@pytest.fixture
def context() -> dict[str, Any]:
    """Использовать воспроизводимый локальный режим приёмки."""
    return {
        "forecast_history": json.loads(json.dumps(DATA["forecast_history"])),
        "use_llm": False,
    }


def test_acceptance_has_at_least_twenty_cases() -> None:
    """Формальный контрольный набор содержит минимум 20 сценариев."""
    assert len(CASES) >= 20
    assert len({case["id"] for case in CASES}) == len(CASES)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_control_question(
    context: dict[str, Any], case: dict[str, Any],
) -> None:
    """Каждый контрольный вопрос возвращает согласованный результат."""
    parsed, _, answer = answer_question(case["question"], context)
    for field, expected in case["expected"].items():
        assert parsed.get(field) == expected
    assert answer


def test_end_to_end_acceptance_scenario() -> None:
    """Сквозной расчёт связывает состояние, риск, план и бюджет."""
    scenario = build_end_to_end_scenario(DATA["forecast_history"])
    assert len(scenario["stock_state"]) == 3
    assert len(scenario["forecast"]) == 3
    assert scenario["deficit_risk_without_incoming"] == [
        "OIL-001", "SCRB-020",
    ]
    assert scenario["purchase_plan"] == [
        {"sku": "OIL-001", "qty": 10, "unit": "л", "cost": 12590.5},
        {"sku": "SCRB-020", "qty": 37, "unit": "кг", "cost": 66211.5},
    ]
    assert scenario["budget"] == 78802.0
