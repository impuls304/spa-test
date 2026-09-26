"""Загрузка и индексация справочника товаров."""

import json
import re
from collections import defaultdict
from functools import cache
from pathlib import Path
from typing import Any

from pymorphy3 import MorphAnalyzer


CATALOG_PATH = Path(__file__).resolve().parents[2] / "catalog.json"
RUSSIAN_WORD_PATTERN = re.compile(r"[а-яё]+", re.IGNORECASE)
MIN_PRODUCT_NAME_COVERAGE = 0.8
MIN_PRODUCT_NAME_SCORE_GAP = 0.2


@cache
def get_morph_analyzer() -> MorphAnalyzer:
    """Создать морфологический анализатор один раз."""
    return MorphAnalyzer()


def lemmatize_text(text: str) -> frozenset[str]:
    """Вернуть уникальные начальные формы русских слов."""
    morph = get_morph_analyzer()
    words = RUSSIAN_WORD_PATTERN.findall(text.casefold())

    return frozenset(
        morph.parse(word)[0].normal_form
        for word in words
    )


@cache
def load_catalog() -> tuple[dict[str, Any], ...]:
    """Загрузить справочник один раз и вернуть неизменяемую коллекцию записей."""
    with CATALOG_PATH.open(encoding="utf-8") as catalog_file:
        return tuple(json.load(catalog_file))


@cache
def get_valid_skus() -> frozenset[str]:
    """Вернуть множество SKU, присутствующих в справочнике."""
    return frozenset(item["sku"] for item in load_catalog())


@cache
def get_products_by_sku() -> dict[str, dict[str, Any]]:
    """Построить индекс карточек товаров по SKU."""
    return {
        item["sku"]: item
        for item in load_catalog()
    }


def get_product_by_sku(sku: str | None) -> dict[str, Any] | None:
    """Вернуть карточку товара либо None для отсутствующего SKU."""
    if sku is None:
        return None
    return get_products_by_sku().get(sku)


@cache
def get_product_lemmas_by_sku() -> dict[str, frozenset[str]]:
    """Связать каждый SKU с леммами его названия."""
    return {
        item["sku"]: lemmatize_text(item["name"])
        for item in load_catalog()
    }


@cache
def get_product_lemma_index() -> dict[str, frozenset[str]]:
    """Построить обратный индекс: лемма -> подходящие SKU."""
    mutable_index: dict[str, set[str]] = defaultdict(set)

    for sku, lemmas in get_product_lemmas_by_sku().items():
        for lemma in lemmas:
            mutable_index[lemma].add(sku)

    return {
        lemma: frozenset(skus)
        for lemma, skus in mutable_index.items()
    }


def match_sku_by_product_name(text: str) -> str | None:
    """Сопоставить текст с названием товара без угадывания при неоднозначности."""
    text_lemmas = lemmatize_text(text)
    lemma_index = get_product_lemma_index()
    product_lemmas = get_product_lemmas_by_sku()

    candidates: set[str] = set()
    for lemma in text_lemmas:
        candidates.update(lemma_index.get(lemma, ()))

    if not candidates:
        return None

    scored_candidates = sorted(
        (
            len(text_lemmas & product_lemmas[sku]) / len(product_lemmas[sku]),
            sku,
        )
        for sku in candidates
    )
    best_score, best_sku = scored_candidates[-1]

    if best_score < MIN_PRODUCT_NAME_COVERAGE:
        return None

    if len(scored_candidates) > 1:
        second_score = scored_candidates[-2][0]
        if best_score - second_score < MIN_PRODUCT_NAME_SCORE_GAP:
            return None

    return best_sku
