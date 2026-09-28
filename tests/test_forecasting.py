"""Тесты прогнозирования спроса."""

import json
from pathlib import Path
from typing import Any

import pytest

from inventory_ai.forecasting import (
    calculate_confidence,
    calculate_recent_level_ratio,
    calculate_recent_weekly_average,
    forecast_demand,
    round_order_quantity,
)


DATASET_PATH = Path(__file__).resolve().parents[1] / "dataset.json"


@pytest.fixture
def forecast_history() -> dict[str, Any]:
    """Загрузить историю прогнозирования из демонстрационного набора."""
    with DATASET_PATH.open(encoding="utf-8") as dataset_file:
        return json.load(dataset_file)["forecast_history"]


def test_calculate_recent_weekly_average() -> None:
    """Среднее рассчитывается по последним четырём неделям."""
    weekly_history = [
        8.4,
        9.1,
        8.8,
        9.6,
        10.2,
        9.4,
        11.0,
        10.6,
        12.3,
        11.8,
        12.9,
        13.4,
    ]

    result = calculate_recent_weekly_average(weekly_history)

    assert result == pytest.approx(12.6)


def test_calculate_full_history_average() -> None:
    """Размер окна позволяет использовать всю доступную историю."""
    weekly_history = [
        8.4,
        9.1,
        8.8,
        9.6,
        10.2,
        9.4,
        11.0,
        10.6,
        12.3,
        11.8,
        12.9,
        13.4,
    ]

    result = calculate_recent_weekly_average(
        weekly_history,
        window_weeks=12,
    )

    assert result == pytest.approx(10.625)


def test_average_ignores_missing_values() -> None:
    """Пропуск не считается нулевым расходом."""
    weekly_history = [6.0, None, 6.6, 6.2]

    result = calculate_recent_weekly_average(weekly_history)

    assert result == pytest.approx(6.2667, abs=0.0001)


@pytest.mark.parametrize(
    ("weekly_history", "window_weeks", "error_message"),
    [
        ([], 4, "История расхода не должна быть пустой"),
        ([1.0], 0, "Размер окна должен быть больше нуля"),
        (
            [1.0, None, None],
            2,
            "Выбранный период не содержит данных о расходе",
        ),
    ],
)
def test_average_rejects_invalid_input(
    weekly_history: list[float | None],
    window_weeks: int,
    error_message: str,
) -> None:
    """Некорректная история или размер окна вызывают понятную ошибку."""
    with pytest.raises(ValueError, match=error_message):
        calculate_recent_weekly_average(
            weekly_history,
            window_weeks=window_weeks,
        )


def test_level_ratio_detects_sharp_growth() -> None:
    """Коэффициент отражает резкий рост расхода скраба."""
    weekly_history = [
        3.1,
        2.9,
        3.4,
        3.0,
        3.3,
        3.2,
        3.5,
        3.1,
        6.8,
        7.4,
        7.1,
        7.6,
    ]

    result = calculate_recent_level_ratio(weekly_history)

    assert result == pytest.approx(2.2061, abs=0.0001)


def test_level_ratio_detects_gradual_growth() -> None:
    """Коэффициент отражает умеренный рост расхода масла."""
    weekly_history = [
        8.4,
        9.1,
        8.8,
        9.6,
        10.2,
        9.4,
        11.0,
        10.6,
        12.3,
        11.8,
        12.9,
        13.4,
    ]

    result = calculate_recent_level_ratio(weekly_history)

    assert result == pytest.approx(1.2233, abs=0.0001)


def test_level_ratio_requires_two_windows() -> None:
    """Для сравнения нужны два полных временных окна."""
    result = calculate_recent_level_ratio([1.0, 2.0, 3.0, 4.0])

    assert result is None


@pytest.mark.parametrize(
    ("raw_quantity", "pack_size", "min_order_quantity", "expected"),
    [
        (0.0, 5.0, 10.0, 0.0),
        (8.8, 5.0, 10.0, 10.0),
        (11.0, 5.0, 10.0, 15.0),
        (2.0, 1.0, 5.0, 5.0),
        (0.000001, 5.0, 0.0, 5.0),
    ],
)
def test_round_order_quantity_obeys_supplier_rules(
    raw_quantity: float,
    pack_size: float,
    min_order_quantity: float,
    expected: float,
) -> None:
    """Заказ учитывает размер упаковки и минимальную партию."""
    result = round_order_quantity(
        raw_quantity,
        pack_size,
        min_order_quantity,
    )

    assert result == pytest.approx(expected)


def test_confidence_decreases_when_history_has_a_gap() -> None:
    """Пропуск наблюдения снижает уверенность прогноза."""
    complete = [6.0] * 12
    incomplete = [6.0, None, *([6.0] * 10)]

    assert calculate_confidence(incomplete) < calculate_confidence(complete)


@pytest.mark.parametrize(
    (
        "sku",
        "horizon_days",
        "expected_order",
        "expected_cost",
        "expected_stockout",
        "expected_confidence",
    ),
    [
        ("OIL-001", 30, 10.0, 12590.5, "2026-10-13", 0.984),
        ("OIL-001", 90, 120.0, 151086.0, "2026-10-13", 0.984),
        ("SCRB-020", 30, 37.0, 66211.5, "2026-09-25", 0.986),
        ("SCRB-020", 90, 98.0, 175371.0, "2026-09-25", 0.986),
        ("WRAP-030", 30, 0.0, 0.0, "2026-10-18", 0.954),
        ("WRAP-030", 90, 36.0, 87732.0, "2026-10-18", 0.954),
    ],
)
def test_forecast_demand_for_dataset(
    forecast_history: dict[str, Any],
    sku: str,
    horizon_days: int,
    expected_order: float,
    expected_cost: float,
    expected_stockout: str,
    expected_confidence: float,
) -> None:
    """Итоговый прогноз воспроизводим на демонстрационных данных."""
    result = forecast_demand(
        forecast_history,
        sku,
        horizon_days,
        params={},
    )

    required = {
        "avg_daily_consumption", "forecast_demand", "current_stock",
        "incoming_qty", "safety_stock", "reorder_point", "recommended_qty",
        "estimated_cost", "stockout_date", "confidence", "explanation",
    }
    assert required <= result.keys()
    assert result["explanation"]
    assert result["requires_clarification"] is False
    assert result["recommended_qty"] == expected_order
    assert result["estimated_cost"] == pytest.approx(expected_cost)
    assert result["stockout_date"] == expected_stockout
    assert result["confidence"] == pytest.approx(expected_confidence)


def test_forecast_demand_supports_growth_scenario(
    forecast_history: dict[str, Any],
) -> None:
    """Параметр позволяет рассчитать сценарий роста загрузки."""
    result = forecast_demand(
        forecast_history,
        "OIL-001",
        30,
        params={"demand_multiplier": 1.2},
    )

    assert result["weekly_average"] == pytest.approx(15.12)
    assert result["recommended_qty"] == pytest.approx(25.0)
    assert result["estimated_cost"] == pytest.approx(31476.25)


def test_forecast_demand_rejects_unknown_sku(
    forecast_history: dict[str, Any],
) -> None:
    """Неизвестный SKU не приводит к выдуманному прогнозу."""
    with pytest.raises(ValueError, match="отсутствует в каталоге"):
        forecast_demand(
            forecast_history,
            "UNKNOWN-999",
            30,
            params={},
        )


@pytest.mark.parametrize("weekly", [[7.0], [0.0, 0.0, 0.0, 28.0] * 3])
def test_unreliable_forecast_requests_clarification(
    forecast_history: dict[str, Any], weekly: list[float],
) -> None:
    """Короткая или волатильная история требует проверки."""
    forecast_history["weekly_consumption"]["OIL-001"] = weekly
    result = forecast_demand(forecast_history, "OIL-001", 30)
    assert result["confidence"] < 0.75
    assert result["requires_clarification"] is True
    assert "Требуется уточнение" in result["explanation"]
    assert calculate_confidence(weekly) < calculate_confidence([7.0] * 12)


def test_confidence_threshold_boundary(
    forecast_history: dict[str, Any],
) -> None:
    """Равенство порогу разрешено; сравнивается неокруглённая оценка."""
    weekly = forecast_history["weekly_consumption"]["OIL-001"]
    score = calculate_confidence(weekly)
    result = forecast_demand(
        forecast_history, "OIL-001", 30,
        {"confidence_threshold": score},
    )
    assert result["requires_clarification"] is False
    result = forecast_demand(
        forecast_history, "OIL-001", 30,
        {"confidence_threshold": score + 0.00001},
    )
    assert result["requires_clarification"] is True


@pytest.mark.parametrize("threshold", [-0.1, 1.1])
def test_invalid_confidence_threshold(
    forecast_history: dict[str, Any], threshold: float,
) -> None:
    """Порог вне диапазона отклоняется."""
    with pytest.raises(ValueError, match="Порог confidence"):
        forecast_demand(
            forecast_history, "OIL-001", 30,
            {"confidence_threshold": threshold},
        )


def test_explanation_uses_calculation_inputs(
    forecast_history: dict[str, Any],
) -> None:
    """Объяснение показывает остатки, правила поставщика и стоимость."""
    result = forecast_demand(forecast_history, "OIL-001", 30)
    explanation = result["explanation"]
    for fragment in (
        "54.00", "25.20", "50.4", "20", "8.80",
        "Упаковка: 5, минимум: 10", "10 × 1259.05", "12590.50",
    ):
        assert fragment in explanation
