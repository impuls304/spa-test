"""Тесты нормализации количества и единицы измерения."""
import pytest
from inventory_ai.normalization import extract_quantity_and_unit


def test_extract_quantity_in_base_unit() -> None:
    """Количество в базовой единице возвращается без пересчёта."""
    text = "2026-03-08; MS-01; CONS-051; расход; 48 пар"

    assert extract_quantity_and_unit(text, "CONS-051") == (48.0, "пар")


@pytest.mark.parametrize(
    ("text", "sku", "expected"),
    [
        ("расход 2 л", "OIL-002", (2.0, "л")),
        ("списание 1,2 кг", "SCRB-020", (1.2, "кг")),
        ("корректировка -120 шт", "CONS-052", (-120.0, "шт")),
        ("корректировка −120 шт", "CONS-052", (-120.0, "шт")),
    ],
)
def test_extract_direct_quantity(
    text: str,
    sku: str,
    expected: tuple[float, str],
) -> None:
    """Прямое количество распознаётся в разных форматах."""
    assert extract_quantity_and_unit(text, sku) == expected


@pytest.mark.parametrize(
    ("text", "sku", "expected"),
    [
        ("расход 450 мл", "OIL-001", (0.45, "л")),
        ("списание 750 г", "SCRB-020", (0.75, "кг")),
    ],
)
def test_convert_quantity_to_base_unit(
    text: str,
    sku: str,
    expected: tuple[float, str],
) -> None:
    """Количество преобразуется в базовую единицу товара."""
    assert extract_quantity_and_unit(text, sku) == expected


@pytest.mark.parametrize(
    ("text", "sku", "expected"),
    [
        ("приход 2 канистры по 5 л", "OIL-001", (10.0, "л")),
        ("приход 4 уп. по 50 пар", "CONS-051", (200.0, "пар")),
    ],
)
def test_convert_packages_to_base_quantity(
    text: str,
    sku: str,
    expected: tuple[float, str],
) -> None:
    """Количество упаковок умножается на содержимое одной упаковки"""
    assert extract_quantity_and_unit(text, sku) == expected


@pytest.mark.parametrize(
    ("text", "sku", "expected"),
    [
        (
            "Возврат 12 марта 2026 г.: OIL-002, 2 л",
            "OIL-002",
            (2.0, "л"),
        ),
        (
            "Возврат 12 марта 2026 г.: SCRB-020, 2 кг",
            "SCRB-020",
            (2.0, "кг"),
        ),
    ],
)
def test_date_is_not_mistaken_for_quantity(
    text: str,
    sku: str,
    expected: tuple[float, str],
) -> None:
    """Год с сокращением `г.` не принимается за количество в граммах."""
    assert extract_quantity_and_unit(text, sku) == expected


def test_multiple_compatible_quantities_are_ambiguous() -> None:
    """Несколько подходящих количеств не выбираются случайным образом."""
    text = "расход OIL-001: 2 л, остаток после операции 3 л"

    assert extract_quantity_and_unit(text, "OIL-001") == (None, None)
