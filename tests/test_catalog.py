"""Тесты сопоставления названий со справочником."""

from inventory_ai.catalog import lemmatize_text, match_sku_by_product_name


def test_lemmatize_product_name_in_different_cases() -> None:
    """Разные падежные формы дают одинаковый набор лемм."""
    catalog_name = lemmatize_text("Тапочки одноразовые")
    movement_name = lemmatize_text("тапочек одноразовых")

    assert catalog_name == movement_name


def test_ambiguous_product_name_is_not_guessed() -> None:
    """Общее слово для нескольких товаров не превращается в случайный SKU."""
    text = "Приход массажного масла"

    assert match_sku_by_product_name(text) is None
