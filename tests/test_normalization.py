"""Тесты нормализации складских записей."""

from inventory_ai.normalization import extract_operation, extract_date, extract_sku, extract_location


def test_extract_operation_receipt() -> None:
    """Русское слово «приход» преобразуется в receipt."""
    text = "05.03.2026 MS-01 приход OIL-001, 2 канистры по 5 л"

    assert extract_operation(text) == "receipt"


def test_extract_operation_consume() -> None:
    """Русское слово «расход» преобразуется в consume."""
    text = "MS-01 расход OIL-001 - 450 мл"

    assert extract_operation(text) == "consume"
    
    
def test_extract_operation_writeoff() -> None:
    """Русское слово «списание» преобразуется в writeoff."""
    text = "03/06/26 Сочи списание SCRB-020 1,2 кг, истек срок"

    assert extract_operation(text) == "writeoff"
    
    
def test_extract_operation_return() -> None:
    """Русское слово «возврат» преобразуется в return."""
    text = "Возврат 12 марта 2026 г.: OIL-002, 2л, брак упаковки"

    assert extract_operation(text) == "return"
    
    
def test_extract_operation_correction() -> None:
    """Русское слово «корректировка» преобразуется в correction."""
    text = "Корректировка 15.03.2026, MS-02, CONS-052: -120 шт"

    assert extract_operation(text) == "correction"
    
 
def test_extract_date_dotted_format() -> None:
    """Нормализация формата даты в ISO формат"""
    text = "05.03.2026 MS-01 приход OIL-001" 
    
    assert extract_date(text) == "2026-03-05"
    
    
def test_extract_date_missing() -> None:
    """Если даты нет возвращаем None"""
    text = "Приход тапочек одноразовых"
    
    assert extract_date(text) is None
    
    
def test_extract_date_short_year() -> None:
    """Проверка короткого форматы даты"""
    text  = "07.03.26 ms-02 WRAP 030 расход 3,5 кг"
    
    assert extract_date(text) == "2026-03-07"
    

def test_extract_date_slash_format() -> None:
    """Дата с косыми чертами преобразуется в ISO-формат"""
    text = "03/06/26 Сочи списание SCRB-020 1,2 кг"

    assert extract_date(text) == "2026-06-03"


def test_extract_date_iso_format() -> None:
    """Дата cоответствующая YYYY-MM-DD ISO-формат"""
    text = "2026-03-08; MS-01; CONS-051; расход; 48 пар"

    assert extract_date(text) == "2026-03-08"


def test_extract_date_russian_month() -> None:
    """Дата с русским названием месяца преобразуется в ISO-формат"""
    text = "1 марта 2026 MS-01 расход oil 001 — 450 мл"

    assert extract_date(text) == "2026-03-01"  
    

def test_extract_date_russian_month_with_year_suffix() -> None:
    """Сокращение (г.) не мешает извлечению даты"""
    text = "Возврат 12 марта 2026 г.: OIL-002, 2 л"

    assert extract_date(text) == "2026-03-12"


def test_extract_sku_standard_format() -> None:
    """SKU в стандартном формате извлекается без изменения."""
    text = "05.03.2026 MS-01 приход OIL-001, 2 канистры по 5 л"

    assert extract_sku(text) == "OIL-001"


def test_extract_sku_space_and_lowercase() -> None:
    """SKU с пробелом и строчными буквами приводим к стандартному формату"""
    text = "1 марта 2026 MS-01 расход oil 001 — 450 мл"

    assert extract_sku(text) == "OIL-001"  


def test_extract_sku_unknown_code() -> None:
    """Код, отсутствующий в справочнике, не принимается как SKU."""
    text = "Приход ABC-999, 5 шт"

    assert extract_sku(text) is None


def test_extract_sku_by_product_name() -> None:
    """SKU определяется по названию товара, если явного кода нет"""
    text = "Приход тапочек одноразовых, 4 уп. по 50 пар, Красная Поляна"

    assert extract_sku(text) == "CONS-051"


def test_extract_location_standard_code() -> None:
    """Код объекта в стандартном формате извлекается без изменения"""
    text = "05.03.2026 MS-01 приход OIL-001"

    assert extract_location(text) == "MS-01"


def test_extract_location_lowercase_code() -> None:
    """Код объекта в нижнем регистре нормализуется."""
    text = "07.03.26 ms-02 WRAP 030 расход 3,5 кг"

    assert extract_location(text) == "MS-02"


def test_extract_location_named_city() -> None:
    """Название города извлекается как локация."""
    text = "03/06/26 Сочи списание SCRB-020 1,2 кг"

    assert extract_location(text) == "Сочи"
    