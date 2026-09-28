"""Запуск демонстрационного пайплайна и отдельного вопроса."""

import argparse
import json
import os
from pathlib import Path
from typing import Any

from inventory_ai.acceptance import (
    build_end_to_end_scenario, evaluate_acceptance,
)
from inventory_ai.forecasting import forecast_demand
from inventory_ai.normalization import normalize_movement
from inventory_ai.questions import answer_question

DATASET_PATH = Path(__file__).resolve().parents[2] / "dataset.json"


def format_answer(result: tuple, as_of: str, details: bool = False) -> str:
    """Показать рекомендацию, основания и фактический режим разбора."""
    parsed, _, answer = result
    modes = {
        "local": "Локальный разбор",
        "gigachat": "Разбор через GigaChat",
        "local_fallback": "GigaChat недоступен — локальный резервный режим",
    }

    def number(value: float, decimals: int = 2) -> str:
        return f"{value:,.{decimals}f}".replace(",", " ").replace(".", ",")

    lines = [f"Данные на {as_of}", modes[parsed["parser"]], ""]
    if "sku" in parsed.get("llm_enriched_fields", []):
        lines += [
            f"Товар из свободной формулировки распознан как "
            f"{parsed['sku']}.",
            "",
        ]
    results = parsed.get("results", [])
    if not results:
        return "\n".join(lines + [answer])
    if not parsed.get("sku"):
        lines += ["Охват: товары с доступной историей расхода.", ""]
    for item in results:
        unit = item["unit"]
        qty = number(item["recommended_qty"]).rstrip("0").rstrip(",")
        lines += [
            f"{item['sku']} · горизонт: {item['horizon_days']} дней",
            (
                f"Рекомендуется закупить: {qty} {unit}"
                if item["recommended_qty"] else "Закупка не требуется."
            ),
            f"Стоимость: {number(item['estimated_cost'])}",
            "",
            "Основание расчёта:",
            f"  Прогноз расхода: {number(item['forecast_demand'])} {unit}",
            f"  Страховой запас: {number(item['safety_stock'])} {unit}",
            f"  На складе: {number(item['current_stock'])} {unit}",
            f"  В пути: {number(item['incoming_qty'])} {unit}",
            f"  Потребность до округления: "
            f"{number(item['raw_order_quantity'])} {unit}",
            "  Итог учитывает упаковку и минимальную партию.",
            f"Исчерпание текущего остатка: "
            f"{item['stockout_date'] or 'не ожидается при нулевом расходе'}",
        ]
        if item["requires_clarification"]:
            lines.append(
                "Требуется уточнение: проверьте историю расхода "
                "перед использованием рекомендации."
            )
        if details:
            lines += ["", "Подробный расчёт:", item["explanation"]]
        lines.append("")
    if len(results) > 1:
        total = sum(item["estimated_cost"] for item in results)
        lines.append(f"Общая стоимость: {number(total)}")
    if parsed.get("budget_limit") is not None:
        lines.append(f"Бюджетный лимит: {number(parsed['budget_limit'])}")
        lines.append(
            "Лимит превышен; объём заказа автоматически не сокращён."
            if parsed["budget_exceeded"] else "Расчёт укладывается в лимит."
        )
    lines.append(
        "Дата исчерпания рассчитана от даты данных, без поставок в пути."
    )
    return "\n".join(lines)


def load_local_env() -> None:
    """Загрузить настройки GigaChat из .env без изменения окружения."""
    env_path = DATASET_PATH.parent / ".env"
    if not env_path.exists():
        return
    allowed = {
        "GIGACHAT_AUTH_KEY", "GIGACHAT_SCOPE",
        "GIGACHAT_MODEL", "GIGACHAT_CA_BUNDLE",
    }
    for line in env_path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() in allowed:
            os.environ.setdefault(
                key.strip(), value.strip().strip("\"'"),
            )


def format_acceptance(result: dict[str, Any]) -> str:
    """Показать контрольные вопросы и сквозной сценарий приёмки."""
    controls = result["controls"]
    scenario = result["scenario"]
    lines = [
        "Приёмочная проверка MVP",
        "Режим: воспроизводимый локальный fallback",
        f"Контрольные вопросы: {controls['passed']}/{controls['total']}",
        "",
    ]
    for check in controls["checks"]:
        marker = "PASS" if check["passed"] else "FAIL"
        lines.append(f"[{marker}] {check['id']} · {check['question']}")
        if check["mismatches"]:
            lines.append(
                "  " + json.dumps(
                    check["mismatches"], ensure_ascii=False,
                )
            )
    lines += [
        "",
        "Сквозной сценарий: состояние → прогноз → риск → план → бюджет",
        f"Дата данных: {scenario['as_of']}; "
        f"горизонт: {scenario['horizon_days']} дней",
        "",
        "1. Состояние склада",
    ]
    for item in scenario["stock_state"]:
        lines.append(
            f"  {item['sku']}: остаток {item['current_stock']:g} "
            f"{item['unit']}, в пути {item['incoming_qty']:g} {item['unit']}"
        )
    lines.append("2. Прогноз спроса")
    for item in scenario["forecast"]:
        lines.append(
            f"  {item['sku']}: {item['forecast_demand']:.2f} {item['unit']}"
        )
    risks = ", ".join(scenario["deficit_risk_without_incoming"]) or "нет"
    lines += [
        "3. Риск дефицита без учёта поставок в пути",
        f"  {risks}",
        "4. План закупки",
    ]
    for item in scenario["purchase_plan"]:
        lines.append(
            f"  {item['sku']}: {item['qty']:g} {item['unit']}, "
            f"стоимость {item['cost']:.2f}"
        )
    lines += [
        "5. Бюджет",
        f"  {scenario['budget']:.2f}",
        "Ограничения:",
        *(f"  - {limitation}" for limitation in scenario["limitations"]),
    ]
    return "\n".join(lines)


def main() -> None:
    """Вывести читаемый ответ или JSON; offline исключает обращения к API."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["demo", "ask", "acceptance"])
    parser.add_argument("question", nargs="?")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--json", action="store_true", help="Полный JSON")
    parser.add_argument("--details", action="store_true",
                        help="Показать полное объяснение расчёта")
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    args = parser.parse_args()
    if not args.offline and args.command != "acceptance":
        load_local_env()
    if args.command == "ask" and not args.question:
        parser.error("Для ask нужен текст вопроса.")
    data = json.loads(args.dataset.read_text(encoding="utf-8"))
    context = {
        "forecast_history": data["forecast_history"],
        "use_llm": not args.offline and args.command != "acceptance",
    }
    if args.command == "ask":
        result = answer_question(args.question, context)
    elif args.command == "acceptance":
        result = {
            "controls": evaluate_acceptance(context),
            "scenario": build_end_to_end_scenario(
                context["forecast_history"],
            ),
        }
    else:
        result = {
            "movements": [
                {"id": row["id"], "result": normalize_movement(row["text"])}
                for row in data["movements"]
            ],
            "forecasts": [
                forecast_demand(context["forecast_history"], sku, days)
                for sku in context["forecast_history"]["weekly_consumption"]
                for days in (30, 90)
            ],
            "answers": [
                {"question": question,
                 "result": answer_question(question, context)}
                for question in data["questions"]
            ],
        }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "ask":
        print(format_answer(
            result, context["forecast_history"]["as_of"], args.details,
        ))
    elif args.command == "acceptance":
        print(format_acceptance(result))
        if not result["controls"]["all_passed"]:
            raise SystemExit(1)
    else:
        print("Нормализация движений")
        for row in result["movements"]:
            print(row["id"], json.dumps(row["result"], ensure_ascii=False))
        print("\nПрогнозы")
        for item in result["forecasts"]:
            print(
                f"{item['sku']} · {item['horizon_days']} дней: "
                f"{item['recommended_qty']:g} {item['unit']}, "
                f"стоимость {item['estimated_cost']:.2f}"
            )
        print("\nВопросы")
        for row in result["answers"]:
            print("\nВопрос:", row["question"])
            print(format_answer(
                row["result"], context["forecast_history"]["as_of"],
                args.details,
            ))


if __name__ == "__main__":
    main()
