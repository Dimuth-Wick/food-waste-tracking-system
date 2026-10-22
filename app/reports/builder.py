"""Work out what the weekly report says: this week's waste against last week's, day by day, and advice.

The week is the seven calendar days (Sri Lanka time) up to the day of the report, with the last day counted up
to the moment the report is made. Last week is the same seven days one week earlier, cut at the same moment.
"""

from datetime import datetime, time, timedelta
import logging

import pandas as pd

from app.database.queries import (RecordFilters, list_daily_amounts, list_meal_checks, total_waste_kg,
                                  total_waste_value, utc_text, waste_by)
from app.forecast.views import FOOD_ITEMS, MEAL_TYPES, SAFETY_MARGIN
from app.waste_records.common import DEMO_TIMEZONE, local_time


logger = logging.getLogger(__name__)
TOP_FOODS = 3
FORECAST_ROWS = 6
MEAL_CHECK_SCAN = 2000


def _filters(start: datetime, end: datetime) -> RecordFilters:
    return RecordFilters(start_at_utc=utc_text(start), end_before_utc=utc_text(end))


def _change(now: float, before: float) -> float | None:
    """How much bigger (+) or smaller (-) as a fraction of before, or None when there is nothing to compare."""
    return (now - before) / before if before > 0 else None


def _daily(db, dates, filters) -> list[dict]:
    days = {day: {"date": day, "kg": 0.0, "value": 0.0, "short_kg": 0.0, "short_value": 0.0, "short_count": 0}
            for day in dates}
    for at, kg, value, is_shortage in list_daily_amounts(db, filters):
        day = days.get(local_time(at).date())
        if day is None:
            continue
        if is_shortage:
            day["short_kg"] += kg
            day["short_value"] += value
            day["short_count"] += 1
        else:
            day["kg"] += kg
            day["value"] += value
    return list(days.values())


def _advice(top_foods, days: int) -> list[dict]:
    """For each costly food: how much it wasted and a plain suggestion to prepare less."""
    advice = []
    for name, kg, value in top_foods[:TOP_FOODS]:
        per_day = kg / days
        advice.append({"food": name, "kg": kg, "value": value, "cut_per_day": per_day,
                       "text": f"Prepare about {per_day:.1f} kg less of {name.lower()} each day."})
    return advice


def _forecast(db, model, advice, start: datetime, end: datetime) -> dict:
    """Recommended quantities for next week for the wasteful dishes, at last week's average guests per meal."""
    guests: dict[str, list[int]] = {}
    for check in list_meal_checks(db, limit=MEAL_CHECK_SCAN):
        if utc_text(start) <= check.event_at < utc_text(end):
            guests.setdefault(check.meal_type.capitalize(), []).append(check.guest_count)
    average = {meal: sum(counts) / len(counts) for meal, counts in guests.items() if meal in MEAL_TYPES}
    dishes = [item["food"] for item in advice if item["food"] in FOOD_ITEMS]
    result = {"rows": [], "guests": {meal: round(count) for meal, count in average.items()}, "available": model is not None}
    if model is None or not average or not dishes:
        return result
    wanted = [(meal, dish, count) for dish in dishes for meal, count in average.items()][:FORECAST_ROWS]
    try:
        frame = pd.DataFrame([{"Meal type": meal, "Food item": dish, "Guest count": count} for meal, dish, count in wanted])
        predicted = model.predict(frame)
    except Exception:
        logger.exception("The report could not forecast next week.")
        return result
    for (meal, dish, count), eaten in zip(wanted, predicted):
        result["rows"].append({"meal": meal, "food": dish, "guests": round(count),
                               "kg": round(float(eaten) * (1 + SAFETY_MARGIN), 1)})
    top = max((row["kg"] for row in result["rows"]), default=0)
    for row in result["rows"]:
        row["share"] = row["kg"] / top if top else 0
    return result


def build_report(db, settings, model, end: datetime) -> dict:
    """The numbers for the week ending at ``end`` (a time with a time zone)."""
    end = end.astimezone(DEMO_TIMEZONE)
    dates = [end.date() - timedelta(days=offset) for offset in range(6, -1, -1)]
    start = datetime.combine(dates[0], time.min, tzinfo=DEMO_TIMEZONE)
    now_filters = _filters(start, end)
    before_filters = _filters(start - timedelta(days=7), end - timedelta(days=7))

    kg, value = total_waste_kg(db, now_filters), total_waste_value(db, now_filters)
    kg_before, value_before = total_waste_kg(db, before_filters), total_waste_value(db, before_filters)
    daily = _daily(db, dates, now_filters)
    top_foods = waste_by(db, "categories", now_filters)
    top_areas = waste_by(db, "areas", now_filters)
    peak = max((day["value"] for day in daily), default=0)
    for day in daily:
        day["share"] = day["value"] / peak if peak else 0
    best = max(top_foods[0][2], 1) if top_foods else 1
    advice = _advice(top_foods, 7)
    return {
        "start": dates[0], "end": dates[-1], "end_at": end, "currency": settings["CURRENCY_SYMBOL"],
        "kg": kg, "value": value, "kg_before": kg_before, "value_before": value_before,
        "value_change": _change(value, value_before), "kg_change": _change(kg, kg_before),
        "daily": daily, "peak_day": max(daily, key=lambda day: day["value"]) if peak else None,
        "foods": [{"name": name, "kg": weight, "value": worth, "share": worth / best} for name, weight, worth in top_foods[:5]],
        "areas": [{"name": name, "kg": weight, "value": worth} for name, weight, worth in top_areas[:3]],
        "shortages": [day for day in daily if day["short_count"]],
        "short_value": sum(day["short_value"] for day in daily),
        "advice": advice, "forecast": _forecast(db, model, advice, start, end),
        "link": settings["PUBLIC_URL"],
    }


def subject(report: dict) -> str:
    return (f"Wastewise weekly report: {report['currency']} {round(report['value']):,} of food waste, "
            f"{report['start']:%d %b} to {report['end']:%d %b}")


def plain_text(report: dict) -> str:
    """The same report as plain text, for mail programs that do not show HTML."""
    cur = report["currency"]
    lines = [f"WASTEWISE WEEKLY REPORT, {report['start']:%d %b} to {report['end']:%d %b %Y}", ""]
    lines.append(f"Waste this week: about {cur} {round(report['value']):,} ({report['kg']:.1f} kg)")
    if report["value_change"] is None:
        lines.append("Last week: no waste was recorded to compare with.")
    else:
        word = "down" if report["value_change"] < 0 else "up"
        lines.append(f"Compared with last week ({cur} {round(report['value_before']):,}, {report['kg_before']:.1f} kg): "
                     f"{word} {abs(report['value_change']) * 100:.0f}%")
    lines += ["", "Day by day"]
    for day in report["daily"]:
        extra = f"  | food ran out {day['short_count']}x" if day["short_count"] else ""
        lines.append(f"  {day['date']:%a %d %b}: {cur} {round(day['value']):,} ({day['kg']:.1f} kg){extra}")
    if report["shortages"]:
        lines += ["", f"Food ran out on {len(report['shortages'])} day(s), worth about {cur} {round(report['short_value']):,}."]
    if report["advice"]:
        lines += ["", "Where to cut"]
        lines += [f"  {item['food']}: {item['kg']:.1f} kg wasted, {cur} {round(item['value']):,}. {item['text']}"
                  for item in report["advice"]]
    if report["forecast"]["rows"]:
        lines += ["", "Next week, at last week's guest numbers"]
        lines += [f"  {row['meal']} {row['food']}: prepare {row['kg']} kg for {row['guests']} guests"
                  for row in report["forecast"]["rows"]]
    lines += ["", f"Open Wastewise: {report['link']}"]
    return "\n".join(lines)
