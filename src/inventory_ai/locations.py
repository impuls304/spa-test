"""Загрузка и сопоставление объектов из внешнего справочника."""

import json
import re
from functools import cache
from pathlib import Path
from typing import Any


LOCATIONS_PATH = Path(__file__).resolve().parents[2] / "locations.json"
LOCATION_TOKEN_PATTERN = re.compile(
    r"[0-9a-zа-яё]+(?:-[0-9a-zа-яё]+)*",
    re.IGNORECASE,
)


def normalize_location_alias(value: str) -> str:
    """Нормализовать регистр, пробелы и границы слов варианта локации."""
    return " ".join(LOCATION_TOKEN_PATTERN.findall(value.casefold()))


@cache
def load_locations() -> tuple[dict[str, Any], ...]:
    """Загрузить реестр объектов один раз."""
    with LOCATIONS_PATH.open(encoding="utf-8") as locations_file:
        return tuple(json.load(locations_file))


@cache
def get_location_alias_index() -> dict[str, str]:
    """Построить индекс: нормализованный вариант -> каноническая локация."""
    alias_index: dict[str, str] = {}

    for location in load_locations():
        canonical_name = location["canonical_name"]
        for alias in location["aliases"]:
            normalized_alias = normalize_location_alias(alias)
            existing = alias_index.get(normalized_alias)
            if existing is not None and existing != canonical_name:
                raise ValueError(
                    f"Вариант локации {alias!r} связан с несколькими объектами"
                )
            alias_index[normalized_alias] = canonical_name

    return alias_index


@cache
def get_max_location_alias_words() -> int:
    """Вернуть максимальное число слов в одном варианте локации."""
    return max(len(alias.split()) for alias in get_location_alias_index())


def match_location(text: str) -> str | None:
    """Найти единственную каноническую локацию через индекс вариантов."""
    normalized_text = normalize_location_alias(text)
    words = normalized_text.split()
    alias_index = get_location_alias_index()
    max_words = min(get_max_location_alias_words(), len(words))

    for size in range(max_words, 0, -1):
        matches = {
            alias_index[" ".join(words[start : start + size])]
            for start in range(len(words) - size + 1)
            if " ".join(words[start : start + size]) in alias_index
        }
        if len(matches) == 1:
            return matches.pop()
        if len(matches) > 1:
            return None

    return None
