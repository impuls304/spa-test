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

NUMERIC_DATE_PATTERNS = (
    (re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{4}\b"), "%d.%m.%Y"),
    (re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{2}\b"), "%d.%m.%y"),
    (re.compile(r"\b\d{1,2}/\d{1,2}/\d{2}\b"), "%d/%m/%y"),
    (re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b"), "%Y-%m-%d"),
)

RUSSIAN_DATE_PATTERN = re.compile(
    r"\b(?P<day>\d{1,2})\s+"
    r"(?P<month>[а-яё]+)\s+"
    r"(?P<year>\d{4})"
    r"(?:\s*г\.)?",
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

UNIT_PATTERN = "|".join(
    sorted(
        map(re.escape, UNIT_CONVERSIONS),
        key=len,
        reverse=True,
    )
)

DIRECT_QUANTITY_PATTERN = re.compile(
    rf"(?P<qty>[−-]?\d+(?:[.,]\d+)?)\s*(?P<unit>{UNIT_PATTERN})\b",
    re.IGNORECASE,
)

PACKAGE_QUANTITY_PATTERN = re.compile(
    rf"(?P<packages>\d+)\s*"
    rf"(?:канистр(?:а|ы)?|уп\.?|упаковк(?:а|и|ок))\s+"
    rf"по\s+"
    rf"(?P<qty_per_package>\d+(?:[.,]\d+)?)\s*"
    rf"(?P<unit>{UNIT_PATTERN})\b",
    re.IGNORECASE,
)


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


def _extract_date_with_span(
    text: str,
) -> tuple[str, tuple[int, int]] | None:
    """Извлечь нормализованную дату и её границы в исходном тексте."""
    for pattern, date_format in NUMERIC_DATE_PATTERNS:
        for match in pattern.finditer(text):
            try:
                parsed_date = datetime.strptime(match.group(), date_format)
            except ValueError:
                continue

            return parsed_date.date().isoformat(), match.span()

    for match in RUSSIAN_DATE_PATTERN.finditer(text):
        month = RUSSIAN_MONTHS.get(match.group("month").lower())

        if month is None:
            continue

        try:
            parsed_date = datetime(
                int(match.group("year")),
                month,
                int(match.group("day")),
            )
        except ValueError:
            continue

        return parsed_date.date().isoformat(), match.span()

    return None


def extract_date(text: str) -> str | None:
    """Извлечь дату и вернуть её в ISO-формате."""
    result = _extract_date_with_span(text)

    if result is None:
        return None

    normalized_date, _ = result
    return normalized_date


def _mask_date(text: str) -> str:
    """Заменить найденную дату пробелами, сохранив позиции остального текста."""
    result = _extract_date_with_span(text)

    if result is None:
        return text

    _, (start, end) = result
    return text[:start] + " " * (end - start) + text[end:]


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

    text_without_date = _mask_date(text)
    product_unit = product["unit"]
    package_matches = [
        match
        for match in PACKAGE_QUANTITY_PATTERN.finditer(text_without_date)
        if UNIT_CONVERSIONS[match.group("unit").lower()][0] == product_unit
    ]

    if len(package_matches) > 1:
        return None, None

    if package_matches:
        package_match = package_matches[0]
        packages = int(package_match.group("packages"))
        qty_per_package = float(
            package_match.group("qty_per_package").replace(",", ".")
        )
        quantity = packages * qty_per_package
        source_unit = package_match.group("unit").lower()
    else:
        direct_matches = [
            match
            for match in DIRECT_QUANTITY_PATTERN.finditer(text_without_date)
            if UNIT_CONVERSIONS[match.group("unit").lower()][0] == product_unit
        ]

        if len(direct_matches) != 1:
            return None, None

        match = direct_matches[0]
        quantity = float(
            match.group("qty")
            .replace("−", "-")
            .replace(",", ".")
        )
        source_unit = match.group("unit").lower()

    conversion = UNIT_CONVERSIONS.get(source_unit)

    if conversion is None:
        return None, None

    base_unit, multiplier = conversion

    if base_unit != product_unit:
        return None, None

    normalized_quantity = quantity * multiplier

    return normalized_quantity, product_unit


def extract_batch(text: str) -> str | None:
    """Извлечь и нормализовать номер партии товара."""
    match = re.search(
        r"\bB-[A-Za-z]{3,4}-\d{3}-\d{3}\b",
        text,
        flags=re.IGNORECASE,
    )

    if match is None:
        return None

    return match.group().upper()


def extract_doc_no(text: str) -> str | None:
    """Извлечь и нормализовать номер складского документа"""
    match = re.search(r"\b[А-ЯЁ]{2}-\d{3}\b", text, flags=re.IGNORECASE)

    if match is None:
        return None

    return match.group().upper()


def normalize_movement(text: str) -> dict[str, Any]:
    """Преобразовать неструктурированную запись в единый словарь."""
    sku = extract_sku(text)
    quantity, unit = extract_quantity_and_unit(text, sku)

    return {
        "date": extract_date(text),
        "sku": sku,
        "location": extract_location(text),
        "operation": extract_operation(text),
        "qty": quantity,
        "unit": unit,
        "batch": extract_batch(text),
        "doc_no": extract_doc_no(text),
    }
    
    
