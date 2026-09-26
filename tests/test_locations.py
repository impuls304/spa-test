"""Тесты сопоставления текста со справочником локаций."""

import pytest

from inventory_ai.locations import match_location


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("MS-01 приход товара", "MS-01"),
        ("ms-02 расход товара", "MS-02"),
        ("Сочи списание товара", "Сочи"),
        ("Приход товара, Красная Поляна", "Красная Поляна"),
        ("Возврат товара без объекта", None),
        ("MS-99 приход товара", None),
    ],
)
def test_match_location(text: str, expected: str | None) -> None:
    """Реестр возвращает только известное каноническое название."""
    assert match_location(text) == expected
