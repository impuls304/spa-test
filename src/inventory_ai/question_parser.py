"""Локальное извлечение намерений и параметров складского вопроса."""

import calendar
import re
from datetime import date
from typing import Any

from inventory_ai.catalog import get_product_lemmas_by_sku, lemmatize_text
from inventory_ai.locations import load_locations

MIN_INTENT_SCORE = 0.6
MIN_INTENT_GAP = 0.15
MATCH_SCORE = 0.9
DAYS_PER_MONTH = 30
COST_MARKERS = {"стоить", "стоимость", "обойтись"}
NUMBER_WORDS = {
    "один": 1, "два": 2, "три": 3, "четыре": 4,
    "пять": 5, "шесть": 6, "семь": 7, "восемь": 8,
    "девять": 9, "десять": 10, "двенадцать": 12,
}
PERIOD_UNITS = {"день": 1, "неделя": 7, "месяц": DAYS_PER_MONTH}
INTENT_RULES = {
    "forecast_purchase": {"закупить", "закупка", "расход", "уйти"},
    "reorder_list": {"заказать", "заказ"},
    "budget": {"бюджет"},
    "deficit_risk": {"дефицит", "закончиться"},
    "expiry_risk": {"сгореть", "годность", "просрочить"},
    "price_dynamics": {"подорожать", "подешеветь", "цена"},
}


def find_product_candidates(text: str) -> list[str]:
    """Найти все равно лучшие SKU по явному коду или леммам названия."""
    normalized_text = text.casefold().replace("ё", "е")
    explicit = re.findall(r"\b([a-z]+)[ -](\d{3})\b", normalized_text)
    candidates = sorted(
        {f"{prefix.upper()}-{code}" for prefix, code in explicit}
    )
    if candidates:
        return candidates
    words = lemmatize_text(text)
    products = get_product_lemmas_by_sku()
    counts = {sku: len(lemmas & words) for sku, lemmas in products.items()}
    best = max(counts.values(), default=0)
    if best == 0:
        return []
    return [sku for sku, count in counts.items() if count == best]


def local_scores(question: str) -> dict[str, float]:
    """Оценить интенты по леммам, а не по полному тексту примера."""
    words = lemmatize_text(question)
    scores = {
        intent: MATCH_SCORE if words & markers else 0.0
        for intent, markers in INTENT_RULES.items()
    }
    if words & {"бюджет", "дефицит"}:
        scores["forecast_purchase"] = 0.0
    if "лимит" in words and words & {"закупка", "закупить"}:
        scores["forecast_purchase"] = MATCH_SCORE
        scores["budget"] = 0.0
    if "стоить" in words and words & {"весь", "всё", "все"}:
        if not scores["deficit_risk"]:
            scores["budget"] = MATCH_SCORE
    if words & COST_MARKERS and not scores["deficit_risk"]:
        scores["budget"] = MATCH_SCORE
        scores["forecast_purchase"] = 0.0
        scores["reorder_list"] = 0.0
    if words & {"заказать", "заказ"} and not words & {"что", "список"}:
        scores["forecast_purchase"] = MATCH_SCORE
        scores["reorder_list"] = 0.0
    return scores


def select_intent(scores: dict[str, float]) -> tuple[str, float]:
    """Отказаться от слабого или неоднозначного распознавания."""
    ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    (intent, first), (_, second) = ranked[:2]
    if first < MIN_INTENT_SCORE or first - second < MIN_INTENT_GAP:
        return "unknown", first
    return intent, first


def extract_entities(question: str, context: dict[str, Any]) -> dict[str, Any]:
    """Извлечь только параметры, подтверждённые текстом или выбором."""
    text = question.casefold().replace("ё", "е")
    words = lemmatize_text(question)
    candidates = find_product_candidates(question)
    sku = candidates[0] if len(candidates) == 1 else None
    if not candidates:
        sku = context.get("selected_sku")

    locations = []
    for location in load_locations():
        for alias in location["aliases"]:
            alias_words = lemmatize_text(alias)
            matched = (
                alias_words <= words if alias_words
                else alias.casefold() in text
            )
            if matched:
                locations.append(location["canonical_name"])
                break
    location = locations[0] if len(locations) == 1 else None
    if not locations:
        location = context.get("selected_location")

    tokens = re.findall(r"\d+(?:[.,]\d+)?|[а-я]+", text)
    normalized = []
    for token in tokens:
        normalized.append(
            next(iter(lemmatize_text(token)), token)
            if token.isalpha() else token
        )
    periods = []
    for index, token in enumerate(normalized):
        if token in PERIOD_UNITS:
            previous = normalized[index - 1] if index else ""
            count = NUMBER_WORDS.get(previous)
            if count is None and previous.isdigit():
                count = int(previous)
            periods.append(
                (1 if count is None else count) * PERIOD_UNITS[token]
            )
        elif token in {"квартал", "полгода", "год"}:
            periods.append({"квартал": 90, "полгода": 180, "год": 365}[token])
    if "в этом месяце" in text:
        as_of = date.fromisoformat(context["forecast_history"]["as_of"])
        periods = [calendar.monthrange(as_of.year, as_of.month)[1]
                   - as_of.day + 1]
    horizon = periods[0] if len(set(periods)) == 1 else None
    if not periods:
        horizon = context.get("default_horizon_days")

    budget = re.search(
        r"(?:лимит\w*|бюджет\w*)\s+(\d+(?:[.,]\d+)?)"
        r"\s*(тыс\w*|млн|миллион\w*)?", text,
    )
    budget_limit = None
    if budget:
        budget_limit = float(budget[1].replace(",", "."))
        if budget[2]:
            budget_limit *= 1000 if budget[2].startswith("тыс") else 1000000
    percentage = re.search(r"(\d+(?:[.,]\d+)?)\s*%", text)
    params = {}
    if percentage:
        change = float(percentage[1].replace(",", ".")) / 100
        if re.search(r"сниз|сниж|уменьш|упад", text):
            params["demand_multiplier"] = 1 - change
        elif re.search(r"выраст|возраст|увелич|рост", text):
            params["demand_multiplier"] = 1 + change

    return {
        "sku": sku, "sku_candidates": candidates, "location": location,
        "horizon_days": horizon, "budget_limit": budget_limit,
        "params": params,
        "entity_conflict": len(candidates) > 1 or len(locations) > 1
        or len(set(periods)) > 1,
    }
