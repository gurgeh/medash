from datetime import date, timedelta
from typing import Any, Callable

from dotenv import load_dotenv

from src.garmin_client import GarminClient


def iso(d: date) -> str:
    return d.isoformat()


def days(n: int) -> list[date]:
    t = date.today()
    return [t - timedelta(days=i) for i in range(n)]


def truthy(x: Any) -> bool:
    return bool(x)


def survey(client: GarminClient) -> str:
    today = date.today()
    last7 = list(reversed(days(7)))
    last30 = list(reversed(days(30)))
    start30 = (today - timedelta(days=29)).isoformat()
    end30 = today.isoformat()

    g = client._client

    per_day_funcs: list[tuple[str, str, Callable[[str], Any]]] = [
        ("Steps (15-min intervals)", "15-min intervals", g.get_steps_data),
        ("Heart rate", "per-day (variable sampling)", g.get_heart_rates),
        ("Sleep", "per-day", g.get_sleep_data),
        ("Stress", "per-day", g.get_stress_data),
        ("SpO2", "per-day", g.get_spo2_data),
        ("Respiration", "per-day", g.get_respiration_data),
        ("Intensity minutes", "per-day", g.get_intensity_minutes_data),
        ("Resting HR (RHR)", "per-day", g.get_rhr_day),
        ("HRV", "per-day", g.get_hrv_data),
        ("Floors", "per-day", g.get_floors),
        ("Hydration", "per-day", g.get_hydration_data),
        ("Daily weigh-ins", "per-day", g.get_daily_weigh_ins),
        ("User summary", "per-day", g.get_user_summary),
        ("Stats", "per-day", g.get_stats),
        ("Stats + body", "per-day", g.get_stats_and_body),
        ("Body Battery events", "per-day events", g.get_body_battery_events),
        ("Training readiness", "per-day", g.get_training_readiness),
        ("Training status", "per-day", g.get_training_status),
        ("Max metrics", "per-day", g.get_max_metrics),
    ]

    per_range_funcs: list[tuple[str, str, Callable[..., Any]]] = [
        ("Daily steps (totals)", "daily totals over range", g.get_daily_steps),
        ("Body Battery", "time series over range", g.get_body_battery),
        ("Body composition", "range (weight/body comp)", g.get_body_composition),
        ("Weigh-ins", "range (entries)", g.get_weigh_ins),
        ("Endurance score", "range", g.get_endurance_score),
        ("Hill score", "range", g.get_hill_score),
        ("Race predictions", "range", g.get_race_predictions),
    ]

    lines: list[str] = []
    lines.append(f"# Garmin Data Inventory\n")
    lines.append(f"Generated on {today.isoformat()}\n")
    lines.append(f"Date ranges: last 7 days and last 30 days (inclusive of today).\n")

    lines.append("## Time Series With Recent Values")
    lines.append("For each metric: the interval and how many days returned data.")

    for title, interval_desc, fn in per_day_funcs:
        w_count = sum(1 for d in last7 if truthy(fn(iso(d))))
        m_count = sum(1 for d in last30 if truthy(fn(iso(d))))
        lines.append(f"- {title} — {interval_desc}: week {w_count}/7 days, month {m_count}/30 days")

    lines.append("")
    lines.append("## Range-Based Metrics (last 30 days)")
    for title, interval_desc, fn in per_range_funcs:
        if getattr(fn, "__name__", "") == "get_daily_steps":
            data = fn((today - timedelta(days=6)).isoformat(), today.isoformat())
            recent_week = bool(data)
            lines.append(f"- {title} — {interval_desc}: week data={recent_week}")
        elif getattr(fn, "__name__", "") == "get_race_predictions":
            d = fn()
            lines.append(f"- {title} — {interval_desc}: available={bool(d)}")
        else:
            d = fn(start30, end30)
            lines.append(f"- {title} — {interval_desc}: month data={bool(d)}")

    lines.append("")
    lines.append("## Activities (Events) — Last 30 Days")
    acts = g.get_activities_by_date(start30, end30)
    lines.append(f"Total activities: {len(acts)}")

    counts: dict[str, int] = {}
    for a in acts:
        t = None
        if isinstance(a.get("activityType"), dict):
            t = a["activityType"].get("typeKey") or a["activityType"].get("typeId")
        if not t:
            t = a.get("activityTypeName") or a.get("type") or str(a.get("activityTypeId"))
        t = str(t)
        counts[t] = counts.get(t, 0) + 1

    for k in sorted(counts.keys()):
        lines.append(f"- {k}: {counts[k]} in last 30 days (details available: splits, weather, HR-in-timezones, gear, exercise sets, full activity details)")

    lines.append("")
    lines.append("## Suggested Extra Metadata To Store")
    lines.append("- Source device IDs, names, and firmware versions")
    lines.append("- Timestamps with timezone offsets and device timezone")
    lines.append("- Aggregation granularities used (e.g., 1s HR, 15-min steps, daily totals)")
    lines.append("- Units (metric/imperial) and measurement system from user settings")
    lines.append("- Activity-level fields: lap/split summaries, training effect/load, VO2max, weather, gear, course")
    lines.append("- Data quality flags and missing-data markers (days without data)")
    lines.append("- Any Garmin-specific IDs needed to re-fetch details later")

    return "\n".join(lines) + "\n"


def main():
    load_dotenv()
    client = GarminClient.from_env()
    client.login()
    content = survey(client)
    out = "memory-bank/garmin_inventory.md"
    with open(out, "w") as f:
        f.write(content)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
