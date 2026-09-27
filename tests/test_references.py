"""Тесты извлечения складских ссылочных номеров."""

import pytest

from inventory_ai.normalization import extract_batch, extract_doc_no


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("450 мл, B-OIL-001-012", "B-OIL-001-012"),
        ("3,5 кг, парт.B-WRAP-030-004", "B-WRAP-030-004"),
        ("приход OIL-001, НК-345", None),
    ],
)
def test_extract_batch(text: str, expected: str | None) -> None:
    """Партия извлекается независимо от префикса `парт.` и регистра."""
    assert extract_batch(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("приход OIL-001, НК-345", "НК-345"),
        ("приход OIL-001, нк-345", "НК-345"),
        ("450 мл, B-OIL-001-012", None),
        ("строка без номера документа", None),
    ],
)
def test_extract_doc_no(text: str, expected: str | None) -> None:
    """Номер документа извлекается и не смешивается с номером партии."""
    assert extract_doc_no(text) == expected
