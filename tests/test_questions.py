"""Проверка контракта, неоднозначности и безопасного fallback."""

import json
from pathlib import Path
from typing import Any
from urllib.error import URLError

import pytest

from inventory_ai import questions
from inventory_ai.gigachat_parser import GigaChatParser
from inventory_ai.question_parser import INTENT_RULES, select_intent

DATA = json.loads(
    (Path(__file__).resolve().parents[1] / "dataset.json").read_text()
)


def llm_analysis(
    intent: str, **entities: Any,
) -> dict[str, Any]:
    """Собрать валидный результат семантического разбора для теста."""
    scores = dict.fromkeys(INTENT_RULES, 0.0)
    if intent != "unknown":
        scores[intent] = 1.0
    return {
        "scores": scores,
        "product_text": None,
        "product_sku": None,
        "horizon_days": None,
        "demand_multiplier": None,
        "budget_limit": None,
        "location": None,
        **entities,
    }


@pytest.fixture
def context() -> dict[str, Any]:
    """Независимая копия демонстрационной истории."""
    return {
        "forecast_history": json.loads(json.dumps(DATA["forecast_history"])),
        "use_llm": False,
    }


@pytest.mark.parametrize("index,intent,status", [
    (0, "unknown", "requires_clarification"),
    (1, "reorder_list", "ok"),
    (2, "budget", "ok"),
    (3, "unknown", "requires_clarification"),
    (4, "expiry_risk", "data_unavailable"),
    (5, "price_dynamics", "data_unavailable"),
    (6, "unknown", "requires_clarification"),
    (7, "forecast_purchase", "ok"),
    (8, "unknown", "requires_clarification"),
    (9, "unknown", "requires_clarification"),
    (10, "unknown", "requires_clarification"),
    (11, "unknown", "requires_clarification"),
    (12, "unknown", "requires_clarification"),
    (13, "unknown", "requires_clarification"),
    (14, "unknown", "requires_clarification"),
])
def test_dataset(
    context: dict[str, Any], index: int, intent: str, status: str,
) -> None:
    """Все вопросы имеют объяснимый результат без API."""
    parsed, confidence, answer = questions.answer_question(
        DATA["questions"][index], context,
    )
    assert parsed["intent"] == intent
    assert parsed["status"] == status
    assert 0 <= confidence <= 1
    assert answer


def test_budget_and_limit(context: dict[str, Any]) -> None:
    """Общий бюджет берётся из расчётов, лимит не урезает потребность."""
    parsed, _, answer = questions.answer_question(
        DATA["questions"][2], context,
    )
    assert sum(r["estimated_cost"] for r in parsed["results"]) == 414189.0
    assert "414189.00" in answer
    parsed, _, _ = questions.answer_question(DATA["questions"][7], context)
    assert parsed["budget_limit"] == 200000
    assert parsed["budget_exceeded"] is True


def test_replenishment_cost_is_total_budget(
    context: dict[str, Any],
) -> None:
    """Стоимость пополнения без SKU считается по всем товарам с историей."""
    parsed, _, answer = questions.answer_question(
        "Во сколько обойдётся пополнение склада в последующие 30 дней?",
        context,
    )
    assert parsed["intent"] == "budget"
    assert parsed["sku"] is None
    assert parsed["status"] == "ok"
    assert len(parsed["results"]) == 3
    assert "78802.00" in answer


def test_replenishment_cost_without_period_asks_only_for_period(
    context: dict[str, Any],
) -> None:
    """Для общего бюджета нужен период, но не обязательный SKU."""
    parsed, _, answer = questions.answer_question(
        "Во сколько обойдётся пополнение склада?", context,
    )
    assert parsed["intent"] == "unknown"
    assert parsed["sku"] is None
    assert answer == "Уточните период расчёта в днях или месяцах."


def test_scenario_and_selected_product(context: dict[str, Any]) -> None:
    """Выбранный явно SKU допускает вопрос без повторного названия."""
    context["selected_sku"] = "SCRB-020"
    parsed, _, _ = questions.answer_question(
        "Посчитай расход на 30 дней при росте на 15%", context,
    )
    assert parsed["params"]["demand_multiplier"] == 1.15
    assert parsed["results"][0]["sku"] == "SCRB-020"


def test_location_not_replaced_with_global_stock(
    context: dict[str, Any],
) -> None:
    """Остаток филиала нельзя подменять общим."""
    parsed, _, _ = questions.answer_question(
        "Закупить SCRB-020 на 30 дней в Сочи", context,
    )
    assert parsed["status"] == "data_unavailable"
    assert "results" not in parsed


def test_close_intents() -> None:
    """Близкие оценки требуют уточнения."""
    scores = dict.fromkeys(INTENT_RULES, 0.0)
    scores.update(budget=0.8, forecast_purchase=0.75)
    assert select_intent(scores)[0] == "unknown"


def test_api_failure_falls_back(
    context: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ошибка API не мешает локальному расчёту."""
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "test-placeholder")
    context["use_llm"] = True

    def fail(*args: Any) -> dict[str, Any]:
        raise URLError("unavailable")

    monkeypatch.setattr(questions.PARSER, "parse", fail)
    parsed, _, _ = questions.answer_question(DATA["questions"][7], context)
    assert parsed["parser"] == "local_fallback"
    assert parsed["status"] == "ok"


def test_no_key_never_calls_api(
    context: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Автоматический режим без ключа не обращается к сети."""
    monkeypatch.delenv("GIGACHAT_AUTH_KEY", raising=False)
    context["use_llm"] = True

    def fail(*args: Any) -> dict[str, Any]:
        pytest.fail("Unexpected network request")

    monkeypatch.setattr(questions.PARSER, "parse", fail)
    assert questions.answer_question(
        DATA["questions"][7], context,
    )[0]["parser"] == "local"


def test_gigachat_oauth_and_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    """OAuth, метка интента и повторное использование токена."""
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "test-placeholder")
    parser = GigaChatParser()
    calls = []
    scores = dict.fromkeys(INTENT_RULES, 0.0)
    scores["budget"] = 1.0

    def post(
        url: str, data: bytes, headers: dict[str, str],
    ) -> dict[str, Any]:
        calls.append(url)
        if "oauth" in url:
            return {"access_token": "test-token", "expires_at": 9999999999999}
        return {"choices": [{"message": {"content": "budget"}}]}

    monkeypatch.setattr(parser, "_post", post)
    assert parser.parse("Бюджет на квартал")["scores"] == scores
    assert parser.parse("Бюджет на месяц")["scores"] == scores
    assert sum("oauth" in url for url in calls) == 1


def test_gigachat_rejects_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Неполный JSON модели не принимается за готовый разбор."""
    parser = GigaChatParser()
    parser.token = "test-token"
    parser.expires_at = 9999999999
    monkeypatch.setattr(
        parser, "_post",
        lambda *args: {"choices": [{"message": {"content": '{"budget": 2}'}}]},
    )
    with pytest.raises(ValueError):
        parser.parse("Бюджет")


def test_gigachat_accepts_quoted_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Кавычки вокруг единственной допустимой метки не мешают разбору."""
    parser = GigaChatParser()
    parser.token = "test-token"
    parser.expires_at = 9999999999
    scores = dict.fromkeys(INTENT_RULES, 0.0)
    scores["forecast_purchase"] = 1.0
    monkeypatch.setattr(
        parser, "_post",
        lambda *args: {
            "choices": [{"message": {"content": '"forecast_purchase"'}}],
        },
    )
    assert parser.parse("Закупка SCRB-020")["scores"] == scores


def test_gigachat_extracts_semantic_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Компактный ответ содержит интент и кандидаты параметров."""
    parser = GigaChatParser()
    parser.token = "test-token"
    parser.expires_at = 9999999999
    content = (
        "forecast_purchase|эксфолианта|SCRB-020|30|1.15|200000|-"
    )
    monkeypatch.setattr(
        parser, "_post",
        lambda *args: {"choices": [{"message": {"content": content}}]},
    )
    analysis = parser.parse("Свободный вопрос")
    assert analysis["scores"]["forecast_purchase"] == 1.0
    assert analysis["product_text"] == "эксфолианта"
    assert analysis["product_sku"] == "SCRB-020"
    assert analysis["horizon_days"] == 30
    assert analysis["demand_multiplier"] == 1.15
    assert analysis["budget_limit"] == 200000


def test_gigachat_retries_malformed_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Единичный повреждённый ответ модели повторяется автоматически."""
    parser = GigaChatParser()
    parser.token = "test-token"
    parser.expires_at = 9999999999
    scores = dict.fromkeys(INTENT_RULES, 0.0)
    scores["forecast_purchase"] = 1.0
    replies = iter([
        {"choices": [{"message": {"content": "неверный формат"}}]},
        {"choices": [{"message": {"content": "forecast_purchase"}}]},
    ])
    monkeypatch.setattr(parser, "_post", lambda *args: next(replies))
    assert parser.parse("Закупка SCRB-020")["scores"] == scores


def test_llm_cannot_resolve_ambiguous_oil(
    context: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Уверенность модели не устраняет неоднозначность каталога."""
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "test-placeholder")
    context["use_llm"] = True
    scores = dict.fromkeys(INTENT_RULES, 0.0)
    scores["forecast_purchase"] = 1.0
    monkeypatch.setattr(
        questions.PARSER, "parse", lambda *args: llm_analysis(
            "forecast_purchase",
        ),
    )
    parsed, _, _ = questions.answer_question(DATA["questions"][0], context)
    assert parsed["parser"] == "gigachat"
    assert parsed["intent"] == "unknown"
    assert "results" not in parsed


def test_valid_llm_route_uses_python_calculation(
    context: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM-оценки ведут к тем же числам расчётного модуля."""
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "test-placeholder")
    context["use_llm"] = True
    scores = dict.fromkeys(INTENT_RULES, 0.0)
    scores["budget"] = 0.95
    monkeypatch.setattr(
        questions.PARSER, "parse", lambda *args: {
            **llm_analysis("budget"), "scores": scores,
        },
    )
    parsed, _, answer = questions.answer_question(
        DATA["questions"][2], context,
    )
    assert parsed["parser"] == "gigachat"
    assert "414189.00" in answer


def test_llm_enriches_grounded_free_form_entities(
    context: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Модель дополняет синоним товара и процент, подтверждённые вопросом."""
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "test-placeholder")
    context["use_llm"] = True
    monkeypatch.setattr(
        questions.PARSER, "parse", lambda *args: llm_analysis(
            "forecast_purchase",
            product_text="Скраб для тела кофейный",
            product_sku="SCRB-020",
            horizon_days=30,
            demand_multiplier=1.15,
        ),
    )
    parsed, _, _ = questions.answer_question(
        "Сколько эксфолианта заказать на ближайший месяц, если расход "
        "вырастет на пятнадцать процентов?",
        context,
    )
    assert parsed["sku"] == "SCRB-020"
    assert parsed["params"]["demand_multiplier"] == 1.15
    assert parsed["llm_enriched_fields"] == ["sku", "demand_multiplier"]
    assert parsed["status"] == "ok"


def test_llm_cannot_invent_missing_entities(
    context: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Неподтверждённые вопросом SKU и период не принимаются."""
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "test-placeholder")
    context["use_llm"] = True
    monkeypatch.setattr(
        questions.PARSER, "parse", lambda *args: llm_analysis(
            "forecast_purchase",
            product_text="скраб",
            product_sku="SCRB-020",
            horizon_days=30,
        ),
    )
    parsed, _, answer = questions.answer_question("Сколько заказать?", context)
    assert parsed["sku"] is None
    assert parsed["horizon_days"] is None
    assert parsed["llm_enriched_fields"] == []
    assert "Уточните товар" in answer
