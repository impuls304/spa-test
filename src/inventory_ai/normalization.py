"""Нормализация текстовых записей о движении товара."""

from typing import Any
import re
from datetime import datetime
from inventory_ai.catalog import get_product_by_sku, get_valid_skus, match_sku_by_product_name
from inventory_ai.locations import match_location

RUSSIAN_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}

DIRECT_QUANTITY_PATTERN = re.compile(
    r"(?P<qty>[−-]?\d+(?:[.,]\d+)?)\s*(?P<unit>мл|л|кг|г|пар|шт)\b",
    re.IGNORECASE,
)

UNIT_CONVERSIONS = {
    "мл": ("л", 0.001),
    "л": ("л", 1.0),
    "г": ("кг", 0.001),
    "кг": ("кг", 1.0),
    "пар": ("пар", 1.0),
    "шт": ("шт", 1.0),
}

def extract_operation(text: str) -> str | None:
    """Извлечь и нормализовать тип складской операции."""
    normalized_text = text.lower()
    
    if "приход" in normalized_text:
        return "receipt"
    if "расход" in normalized_text:
        return "consume"
    if "списание" in normalized_text:
        return "writeoff"
    if "возврат" in normalized_text:
        return "return"
    if "корректировка" in normalized_text:
        return "correction"
    
    return None

    
def extract_date(text: str) -> str | None:
    """Извлечь дату и вернуть её в ISO-формате."""
    match = re.search(r"\b\d{2}\.\d{2}\.\d{4}\b", text)

    if match is not None:
        parsed_date = datetime.strptime(match.group(), "%d.%m.%Y")
        return parsed_date.date().isoformat()   
    
    match = re.search(r"\b\d{2}\.\d{2}\.\d{2}\b", text)
    
    if match is not None:
        parsed_date = datetime.strptime(match.group(), "%d.%m.%y")
        return parsed_date.date().isoformat()

    match = re.search(r"\b\d{2}/\d{2}/\d{2}\b", text)

    if match is not None:
        parsed_date = datetime.strptime(match.group(), "%d/%m/%y")
        return parsed_date.date().isoformat()

    match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
   
    if match is not None:
        parsed_date = datetime.strptime(match.group(), "%Y-%m-%d")
        return parsed_date.date().isoformat()

    match = re.search(r"\b(\d{1,2})\s+([а-яё]+)\s+(\d{4})\b",text.lower())

    if match is not None:
        day_text, month_text, year_text = match.groups()
        month = RUSSIAN_MONTHS.get(month_text)

        if month is not None:
            parsed_date = datetime(int(year_text), month, int(day_text))
            return parsed_date.date().isoformat()
    
    return None


def extract_sku(text: str) -> str | None:
    """Извлекаем SKU и приводим его к стандартному написанию"""
    match = re.search(r"\b([A-Za-z]{3,4})[-\s](\d{3})\b",text)

    if match is None:
        return match_sku_by_product_name(text)

    prefix, number = match.groups()
    normalized_sku = f"{prefix.upper()}-{number}"

    if normalized_sku not in get_valid_skus():
        return None

    return normalized_sku
 

def extract_location(text: str) -> str | None:
    """Извлечь и нормализовать локацию или склад."""
    match = re.search(r"\bms[-\s](\d{2})\b",text,flags=re.IGNORECASE)

    if match is not None:
        location_number = match.group(1)
        return match_location(f"MS-{location_number}")

    return match_location(text)


def extract_quantity_and_unit(
    text: str,
    sku: str | None,
) -> tuple[float | None, str | None]:
    """Извлечь количество и привести его к базовой единице товара."""
    product = get_product_by_sku(sku)

    if product is None:
        return None, None

    match = DIRECT_QUANTITY_PATTERN.search(text)

    if match is None:
        return None, None

    quantity_text = match.group("qty")
    source_unit = match.group("unit").lower()

    quantity = float(
        quantity_text
        .replace("−", "-")
        .replace(",", ".")
    )

    conversion = UNIT_CONVERSIONS.get(source_unit)

    if conversion is None:
        return None, None

    base_unit, multiplier = conversion

    if base_unit != product["unit"]:
        return None, None

    normalized_quantity = quantity * multiplier

    return normalized_quantity, product["unit"]


def normalize_movement(text: str) -> dict[str, Any]:
    """Преобразовать неструктурированную запись в единый словарь."""
    # Эту функцию будем собирать по частям после небольших вспомогательных функций.
    raise NotImplementedError
    
    
