"""Прогнозирование спроса и расчёт рекомендуемой закупки."""

import math
from datetime import date, timedelta
from statistics import pstdev
from typing import Any

from inventory_ai.catalog import get_product_by_sku


DAYS_PER_WEEK = 7
DEFAULT_WINDOW_WEEKS = 4
DEFAULT_EXPECTED_HISTORY_WEEKS = 12
DEFAULT_DEMAND_MULTIPLIER = 1.0
DEFAULT_CONFIDENCE_THRESHOLD = 0.75


def calculate_recent_weekly_average(
    weekly_history: list[float | None],
    window_weeks: int = DEFAULT_WINDOW_WEEKS,
) -> float:
    """Рассчитать средний расход за последние недели."""
    if not weekly_history:
        raise ValueError("История расхода не должна быть пустой")

    if window_weeks <= 0:
        raise ValueError("Размер окна должен быть больше нуля")

    recent_history = [
        value
        for value in weekly_history[-window_weeks:]
        if value is not None
    ]
    if not recent_history:
        raise ValueError(
            "Выбранный период не содержит данных о расходе"
        )

    if any(value < 0 for value in recent_history):
        raise ValueError(
            "История расхода не может содержать отрицательные значения"
        )

    return sum(recent_history) / len(recent_history)


def calculate_recent_level_ratio(
    weekly_history: list[float | None],
    window_weeks: int = DEFAULT_WINDOW_WEEKS,
) -> float | None:
    """Сравнить средний расход двух последних соседних периодов."""
    if window_weeks <= 0:
        raise ValueError("Размер окна должен быть больше нуля")

    required_weeks = window_weeks * 2
    if len(weekly_history) < required_weeks:
        return None

    previous_history = weekly_history[
        -required_weeks:-window_weeks
    ]
    recent_history = weekly_history[-window_weeks:]
    if not any(value is not None for value in previous_history):
        return None

    if not any(value is not None for value in recent_history):
        return None

    previous_average = calculate_recent_weekly_average(
        previous_history,
        window_weeks=window_weeks,
    )
    recent_average = calculate_recent_weekly_average(
        recent_history,
        window_weeks=window_weeks,
    )

    if previous_average == 0:
        return 1.0 if recent_average == 0 else float("inf")

    return recent_average / previous_average


def round_order_quantity(
    raw_quantity: float,
    pack_size: float,
    min_order_quantity: float,
) -> float:
    """Округлить заказ до упаковки и минимальной партии."""
    if raw_quantity < 0:
        raise ValueError("Потребность в закупке не может быть отрицательной")

    if pack_size <= 0:
        raise ValueError("Размер упаковки должен быть больше нуля")

    if min_order_quantity < 0:
        raise ValueError("Минимальная партия не может быть отрицательной")

    if raw_quantity == 0:
        return 0.0

    quantity_to_round = max(raw_quantity, min_order_quantity)
    packs_required = quantity_to_round / pack_size
    nearest_whole_pack = round(packs_required)
    if math.isclose(packs_required, nearest_whole_pack):
        packs = nearest_whole_pack
    else:
        packs = math.ceil(packs_required)

    return packs * pack_size


def calculate_stockout_date(
    as_of: date,
    current_stock: float,
    daily_average: float,
) -> str | None:
    """Оценить дату исчерпания текущего остатка без поставок в пути."""
    if current_stock < 0:
        raise ValueError("Текущий остаток не может быть отрицательным")

    if daily_average < 0:
        raise ValueError(
            "Средний дневной расход не может быть отрицательным"
        )

    if daily_average == 0:
        return None

    days_until_stockout = math.ceil(current_stock / daily_average)

    return (as_of + timedelta(days=days_until_stockout)).isoformat()


def calculate_confidence(
    weekly_history: list[float | None],
    window_weeks: int = DEFAULT_WINDOW_WEEKS,
    expected_history_weeks: int = DEFAULT_EXPECTED_HISTORY_WEEKS,
) -> float:
    """Оценить полноту, длину и стабильность истории от 0 до 1."""
    if not weekly_history:
        return 0.0

    if window_weeks <= 0 or expected_history_weeks <= 0:
        raise ValueError("Размеры периодов должны быть больше нуля")

    observed = [value for value in weekly_history if value is not None]
    if any(value < 0 for value in observed):
        raise ValueError(
            "История расхода не может содержать отрицательные значения"
        )

    if not observed:
        return 0.0

    length_score = min(len(weekly_history) / expected_history_weeks, 1.0)
    completeness_score = len(observed) / len(weekly_history)
    recent = [
        value
        for value in weekly_history[-window_weeks:]
        if value is not None
    ]

    if len(recent) < 2:
        stability_score = 0.0
    else:
        recent_average = sum(recent) / len(recent)
        if recent_average == 0:
            stability_score = 1.0
        else:
            coefficient_of_variation = pstdev(recent) / recent_average
            stability_score = max(0.0, 1.0 - coefficient_of_variation)

    return (
        length_score
        + completeness_score
        + stability_score
    ) / 3


def forecast_demand(
    history: dict[str, Any],
    sku: str,
    horizon_days: int,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Построить прогноз и рекомендацию закупки для одного SKU."""
    product = get_product_by_sku(sku)
    if product is None:
        raise ValueError(f"SKU {sku!r} отсутствует в каталоге")

    weekly_by_sku = history.get("weekly_consumption", {})
    if sku not in weekly_by_sku:
        raise ValueError(f"Для SKU {sku!r} отсутствует история расхода")

    current_stock_by_sku = history.get("current_stock", {})
    if sku not in current_stock_by_sku:
        raise ValueError(f"Для SKU {sku!r} отсутствует текущий остаток")

    if horizon_days <= 0:
        raise ValueError("Горизонт прогноза должен быть больше нуля")

    settings = params or {}
    window_weeks = settings.get(
        "window_weeks",
        DEFAULT_WINDOW_WEEKS,
    )
    demand_multiplier = settings.get(
        "demand_multiplier",
        DEFAULT_DEMAND_MULTIPLIER,
    )
    if demand_multiplier <= 0:
        raise ValueError("Множитель спроса должен быть больше нуля")

    weekly_history = weekly_by_sku[sku]
    weekly_average = calculate_recent_weekly_average(
        weekly_history,
        window_weeks=window_weeks,
    ) * demand_multiplier
    daily_average = weekly_average / DAYS_PER_WEEK
    forecast_quantity = daily_average * horizon_days

    safety_stock_days = settings.get(
        "safety_stock_days",
        product["safety_stock_days"],
    )
    lead_time_days = settings.get(
        "lead_time_days",
        product["lead_time_days"],
    )
    current_stock = settings.get(
        "current_stock",
        current_stock_by_sku[sku],
    )
    incoming_quantity = settings.get(
        "incoming_quantity",
        history.get("incoming_qty", {}).get(sku, 0.0),
    )
    quantities = {
        "Количество дней страхового запаса": safety_stock_days,
        "Срок поставки": lead_time_days,
        "Текущий остаток": current_stock,
        "Количество в пути": incoming_quantity,
    }
    for name, value in quantities.items():
        if value < 0:
            raise ValueError(f"{name} не может быть отрицательным")

    safety_stock = daily_average * safety_stock_days
    reorder_point = daily_average * lead_time_days + safety_stock
    raw_order_quantity = max(
        0.0,
        forecast_quantity
        + safety_stock
        - current_stock
        - incoming_quantity,
    )
    pack_size = settings.get("pack_size", product["pack_size"])
    min_order_quantity = settings.get(
        "min_order_quantity", product["min_order_qty"]
    )
    recommended_order_quantity = round_order_quantity(
        raw_order_quantity, pack_size, min_order_quantity
    )
    unit_price = settings.get("unit_price", product["price"])
    if unit_price < 0:
        raise ValueError("Цена не может быть отрицательной")

    estimated_cost = recommended_order_quantity * unit_price

    try:
        as_of = date.fromisoformat(history["as_of"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(
            "Поле as_of должно содержать дату в формате YYYY-MM-DD"
        ) from error

    confidence = calculate_confidence(
        weekly_history,
        window_weeks=window_weeks,
        expected_history_weeks=settings.get(
            "expected_history_weeks",
            DEFAULT_EXPECTED_HISTORY_WEEKS,
        ),
    )
    level_ratio = calculate_recent_level_ratio(
        weekly_history,
        window_weeks=window_weeks,
    )

    confidence_threshold = settings.get(
        "confidence_threshold", DEFAULT_CONFIDENCE_THRESHOLD
    )
    if not 0 <= confidence_threshold <= 1:
        raise ValueError("Порог confidence должен быть от 0 до 1")

    requires_clarification = confidence < confidence_threshold
    unit = product["unit"]
    recent = weekly_history[-window_weeks:]
    observed_count = sum(value is not None for value in recent)
    explanation = (
        f"Окно: последние {len(recent)} недель; "
        f"известных наблюдений: {observed_count}. "
        f"Средний недельный расход с множителем {demand_multiplier:g}: "
        f"{weekly_average:.4f} {unit}. "
        f"Дневной расход: {weekly_average:.4f} / {DAYS_PER_WEEK} "
        f"= {daily_average:.4f} {unit}. "
        f"Прогноз на {horizon_days} дней: {forecast_quantity:.2f} {unit}. "
        f"Страховой запас на {safety_stock_days} дней: "
        f"{safety_stock:.2f} {unit}. "
        f"Точка заказа при сроке поставки {lead_time_days} дней: "
        f"{reorder_point:.2f} {unit}. "
        f"Закупка до округления: max(0, {forecast_quantity:.2f} "
        f"+ {safety_stock:.2f} - {current_stock:g} "
        f"- {incoming_quantity:g}) = {raw_order_quantity:.2f} {unit}. "
        f"Упаковка: {pack_size:g}, минимум: {min_order_quantity:g}; "
        f"рекомендовано: {recommended_order_quantity:g} {unit}. "
        f"Стоимость: {recommended_order_quantity:g} × {unit_price:g} "
        f"= {estimated_cost:.2f}. "
        f"Дата исчерпания считается от {as_of.isoformat()} "
        "только по текущему остатку, без поставок в пути. "
        "Промежуточные числа показаны округлённо. "
        f"Confidence: {confidence:.3f}; порог: {confidence_threshold:g}."
    )
    if requires_clarification:
        explanation += (
            " Требуется уточнение: проверьте полноту, длину истории "
            "и колебания расхода перед использованием рекомендации."
        )

    return {
        "sku": sku,
        "unit": product["unit"],
        "horizon_days": horizon_days,
        "weekly_average": round(weekly_average, 4),
        "avg_daily_consumption": round(daily_average, 4),
        "forecast_demand": round(forecast_quantity, 2),
        "current_stock": current_stock,
        "incoming_qty": incoming_quantity,
        "safety_stock": round(safety_stock, 2),
        "reorder_point": round(reorder_point, 2),
        "raw_order_quantity": round(raw_order_quantity, 2),
        "recommended_qty": recommended_order_quantity,
        "estimated_cost": round(estimated_cost, 2),
        "stockout_date": calculate_stockout_date(
            as_of,
            current_stock,
            daily_average,
        ),
        "recent_level_ratio": (
            round(level_ratio, 3)
            if level_ratio is not None
            else None
        ),
        "confidence": round(confidence, 3),
        "requires_clarification": requires_clarification,
        "explanation": explanation,
    }
