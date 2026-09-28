"""Ответы на вопросы: проверка запроса, расчёт и объяснение."""

import os
import re
from typing import Any
from urllib.error import URLError

from inventory_ai.catalog import (
    get_morph_analyzer, get_products_by_sku, lemmatize_text,
)
from inventory_ai.forecasting import forecast_demand
from inventory_ai.gigachat_parser import GigaChatParser
from inventory_ai.locations import match_location
from inventory_ai.question_parser import (
    COST_MARKERS, PERIOD_UNITS, extract_entities, find_product_candidates,
    local_scores, select_intent,
)

PARSER = GigaChatParser()
TIME_MARKERS = set(PERIOD_UNITS) | {
    "квартал", "полгода", "год", "следующий", "ближайший", "последующий",
}
CHANGE_MARKERS = {
    "рост", "вырасти", "возрасти", "увеличиться", "увеличение",
    "снизиться", "снижение", "уменьшиться", "уменьшение", "упасть",
}
BUDGET_MARKERS = {"бюджет", "лимит", "максимум", "больше", "превышать"}
GENERIC_PRODUCT_NOUNS = {
    "бюджет", "год", "день", "дефицит", "заказ", "закупка", "запас",
    "количество", "квартал", "месяц", "пополнение", "поставка", "процент",
    "расход", "склад", "стоимость", "сумма", "товар", "цена",
}


def _is_grounded(fragment: str | None, question_words: frozenset[str]) -> bool:
    """Проверить, что предложенный моделью фрагмент присутствует в вопросе."""
    if fragment is None:
        return False
    fragment_words = lemmatize_text(fragment)
    return bool(fragment_words) and fragment_words <= question_words


def _has_unresolved_product_mention(question: str) -> bool:
    """Найти предметное существительное, не являющееся складским термином."""
    morph = get_morph_analyzer()
    for token in re.findall(r"[а-яё]+", question.casefold()):
        parsed = morph.parse(token)[0]
        if (
            parsed.tag.POS == "NOUN"
            and parsed.normal_form not in GENERIC_PRODUCT_NOUNS
        ):
            return True
    return False


def _merge_llm_entities(
    parsed: dict[str, Any], analysis: dict[str, Any], question: str,
) -> None:
    """Дополнить только пропущенные поля проверенными кандидатами LLM."""
    words = lemmatize_text(question)
    enriched = []
    product_text = analysis.get("product_text")
    product_sku = analysis.get("product_sku")
    product = get_products_by_sku().get(product_sku)
    catalog_name_matches = bool(
        product
        and product_text
        and lemmatize_text(product_text) <= lemmatize_text(product["name"])
    )
    product_is_supported = _is_grounded(product_text, words) or (
        catalog_name_matches and _has_unresolved_product_mention(question)
    )
    if (
        not parsed["sku_candidates"]
        and product is not None
        and product_is_supported
    ):
        local_candidates = find_product_candidates(product_text)
        if not local_candidates or local_candidates == [product_sku]:
            parsed["sku"] = product_sku
            parsed["sku_candidates"] = [product_sku]
            enriched.append("sku")

    horizon = analysis.get("horizon_days")
    if (
        parsed["horizon_days"] is None
        and isinstance(horizon, int)
        and bool(words & TIME_MARKERS)
        and not parsed["entity_conflict"]
    ):
        parsed["horizon_days"] = horizon
        enriched.append("horizon_days")

    multiplier = analysis.get("demand_multiplier")
    if (
        not parsed["params"]
        and isinstance(multiplier, (int, float))
        and bool(words & CHANGE_MARKERS)
        and ("процент" in words or "%" in question)
    ):
        parsed["params"]["demand_multiplier"] = multiplier
        enriched.append("demand_multiplier")

    budget = analysis.get("budget_limit")
    if (
        parsed["budget_limit"] is None
        and isinstance(budget, (int, float))
        and bool(words & BUDGET_MARKERS)
    ):
        parsed["budget_limit"] = budget
        enriched.append("budget_limit")

    location_text = analysis.get("location")
    location = match_location(location_text) if location_text else None
    if (
        parsed["location"] is None
        and location is not None
        and _is_grounded(location_text, words)
    ):
        parsed["location"] = location
        enriched.append("location")
    parsed["llm_enriched_fields"] = enriched


def answer_question(
    question: str, context: dict[str, Any],
) -> tuple[dict, float, str]:
    """Вернуть параметры, уверенность разбора и ответ без выдуманных чисел."""
    parsed = extract_entities(question, context)
    words = lemmatize_text(question)
    scores = local_scores(question)
    parsed["parser"] = "local"
    if context.get("use_llm", True) and os.environ.get("GIGACHAT_AUTH_KEY"):
        try:
            analysis = PARSER.parse(
                question, context["forecast_history"].get("as_of"),
            )
            scores = analysis["scores"]
            _merge_llm_entities(parsed, analysis, question)
            parsed["parser"] = "gigachat"
        except (
            URLError, OSError, ValueError, KeyError, TypeError, IndexError,
        ):
            PARSER.expires_at = 0.0
            parsed["parser"] = "local_fallback"
            # Не выводим исключение: ответ сервера может содержать секреты.
    if words & COST_MARKERS:
        # Явный вопрос «сколько стоит / во сколько обойдётся» — это бюджет,
        # даже если LLM приняла слово «пополнение» за закупку одного товара.
        scores = dict.fromkeys(scores, 0.0)
        scores["budget"] = 1.0 if parsed["parser"] == "gigachat" else 0.9
    intent, confidence = select_intent(scores)
    parsed["intent"] = intent
    parsed["intent_scores"] = scores
    parsed["status"] = "requires_clarification"

    def unknown(message: str) -> tuple[dict, float, str]:
        parsed["intent"] = "unknown"
        return parsed, 0.0, message

    if parsed["entity_conflict"]:
        return unknown("Уточните один товар, объект и период расчёта.")
    if "остаться" in words or re.search(r"когда.*привез", question.casefold()):
        return unknown("Для этого запроса нужны данные склада или заказа.")
    if intent == "unknown":
        return unknown(
            "Уточните складскую задачу: закупка, бюджет, дефицит, "
            "сроки годности или изменение цен."
        )
    comparison = words & {"почему", "подорожать", "подешеветь"}
    if comparison and intent != "price_dynamics":
        return unknown("Нужен предыдущий план и его параметры для сравнения.")
    if intent == "forecast_purchase" and not parsed["sku"]:
        return unknown("Уточните товар: укажите SKU или однозначное название.")
    if intent in {
        "forecast_purchase", "budget", "reorder_list", "deficit_risk",
    }:
        if not parsed["horizon_days"]:
            return unknown("Уточните период расчёта в днях или месяцах.")
    if parsed["location"]:
        parsed["status"] = "data_unavailable"
        return parsed, confidence, (
            "Запрос понятен, но нет остатков и истории расхода по этому "
            "объекту. Общие данные не заменяют данные филиала."
        )
    if intent in {"expiry_risk", "price_dynamics"}:
        parsed["status"] = "data_unavailable"
        missing = (
            "партии с датами годности" if intent == "expiry_risk"
            else "история цен для сравнения"
        )
        return (
            parsed, confidence,
            f"Для ответа нужны {missing}; этих данных нет.",
        )
    if parsed["params"].get("demand_multiplier", 1) <= 0:
        return unknown(
            "Уточните изменение расхода: множитель должен быть положительным."
        )
    if "%" in question and not parsed["params"]:
        return unknown("Уточните направление изменения: рост или снижение.")

    history = context["forecast_history"]
    sku = parsed["sku"]
    skus = [sku] if sku else sorted(history["weekly_consumption"])
    if sku and sku not in get_products_by_sku():
        return unknown("Указанный SKU отсутствует в каталоге.")
    results = []
    try:
        for code in skus:
            results.append(forecast_demand(
                history, code, parsed["horizon_days"], parsed["params"],
            ))
    except (ValueError, KeyError, TypeError):
        parsed["status"] = "data_unavailable"
        return parsed, confidence, (
            "Недостаточно корректных данных для расчёта. "
            "Проверьте историю, остатки и параметры товара."
        )
    if intent == "reorder_list":
        results = [
            item for item in results
            if item["current_stock"] + item["incoming_qty"]
            <= item["reorder_point"] and item["recommended_qty"] > 0
        ]
    if intent == "deficit_risk":
        results = [
            item for item in results
            if item["stockout_date"] is not None
            and item["current_stock"] < item["forecast_demand"]
        ]
    parsed["results"] = results
    parsed["status"] = (
        "requires_clarification"
        if any(item["requires_clarification"] for item in results) else "ok"
    )
    coverage = (
        "Охват: только товары с историей расхода; "
        "позиции без истории не включены. " if not sku else ""
    )
    if not results:
        return (
            parsed, confidence,
            coverage + "По выбранному правилу товары не найдены.",
        )
    answer = coverage + "\n".join(
        f"{item['sku']}: {item['explanation']}" for item in results
    )
    total = round(sum(item["estimated_cost"] for item in results), 2)
    if intent in {"budget", "reorder_list", "deficit_risk"}:
        answer += f"\nСуммарная стоимость рассчитанных закупок: {total:.2f}."
    if parsed["budget_limit"] is not None:
        exceeded = total > parsed["budget_limit"]
        answer += (
            "\nУказанный бюджетный лимит превышен."
            if exceeded
            else "\nРасчёт укладывается в указанный бюджетный лимит."
        )
        parsed["budget_exceeded"] = exceeded
    return parsed, confidence, answer
