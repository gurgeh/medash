from datetime import date, timedelta
from typing import Any, Callable

from dotenv import load_dotenv

from src.garmin_client import GarminClient


def iso(d: date) -> str:
    return d.isoformat()


def days(n: int) -> list[date]:
    t = date.today()
    return [t - timedelta(days=i) for i in range(n)]


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _deep_numeric_present(x: Any) -> bool:
    if _is_number(x):
        return x > 0
    if isinstance(x, list):
        return any(_deep_numeric_present(v) for v in x)
    if isinstance(x, dict):
        skip = {
            "calendarDate",
            "startGMT",
            "endGMT",
            "activityLevel",
            "primaryActivityLevel",
            "activityLevelConstant",
            "measurementSystem",
            "unitSystem",
            "timeOffset",
            "userId",
            "userProfileId",
            "fullName",
            "displayName",
        }
        return any(
            (k not in skip) and _deep_numeric_present(v) for k, v in x.items()
        )
    return False


def has_data_for(name: str, payload: Any) -> bool:
    n = name.lower()

    if n.startswith("steps ("):
        if isinstance(payload, list):
            return any(isinstance(p, dict) and _is_number(p.get("steps")) and p["steps"] > 0 for p in payload)
        return False

    if n == "heart rate":
        if isinstance(payload, dict):
            hr = payload.get("heartRateValues") or payload.get("heartRate")
            if isinstance(hr, list):
                # heartRateValues entries are [timestamp, value]
                for e in hr:
                    if isinstance(e, (list, tuple)) and len(e) >= 2 and _is_number(e[1]) and e[1] > 0:
                        return True
                return False
        return _deep_numeric_present(payload)

    if n == "sleep":
        if isinstance(payload, dict):
            for key in ("sleepTimeInSeconds", "durationInSeconds", "overallScore", "totalSleepSeconds"):
                v = payload.get(key)
                if _is_number(v) and v > 0:
                    return True
        return _deep_numeric_present(payload)

    if n in ("stress", "spo2", "respiration"):
        return _deep_numeric_present(payload)

    if n == "intensity minutes":
        if isinstance(payload, dict):
            for key in ("totalIntensityMinutes", "intensityMinutes", "moderateIntensityMinutes", "vigorousIntensityMinutes"):
                v = payload.get(key)
                if _is_number(v) and v > 0:
                    return True
        return _deep_numeric_present(payload)

    if n == "resting hr (rhr)":
        if isinstance(payload, dict):
            v = payload.get("restingHeartRate")
            return _is_number(v) and v > 0
        return False

    if n == "hrv":
        return _deep_numeric_present(payload)

    if n == "floors":
        if isinstance(payload, dict):
            for key in ("floorsClimbed", "floorsDescended", "dailyFloors"):
                v = payload.get(key)
                if _is_number(v) and v > 0:
                    return True
        return _deep_numeric_present(payload)

    if n == "hydration":
        if isinstance(payload, dict):
            for key in ("totalHydration", "total", "valueInML", "hydrationValues"):
                v = payload.get(key)
                if _is_number(v) and v > 0:
                    return True
                if isinstance(v, list) and any(_is_number(x) and x > 0 for x in v):
                    return True
        return False

    if n == "daily weigh-ins":
        if isinstance(payload, dict):
            lst = payload.get("dateWeightList") or payload.get("weightEntries")
            if isinstance(lst, list) and len(lst) > 0:
                return True
            avg = payload.get("totalAverage")
            if isinstance(avg, dict):
                w = avg.get("weight") or avg.get("weightInKilograms")
                return _is_number(w) and w > 0
        return False

    if n in ("user summary", "stats", "stats + body"):
        return _deep_numeric_present(payload)

    if n == "body battery events":
        return isinstance(payload, list) and len(payload) > 0

    if n == "training readiness":
        if isinstance(payload, dict):
            score = payload.get("trainingReadinessScore") or payload.get("score")
            return _is_number(score) and score > 0
        return False

    if n == "training status":
        if isinstance(payload, dict):
            ts = payload.get("trainingStatus") or payload.get("primaryStatus") or payload.get("status")
            return isinstance(ts, (str, dict)) and bool(ts)
        return False

    if n == "max metrics":
        return _deep_numeric_present(payload)

    return _deep_numeric_present(payload)


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
        w_count = sum(1 for d in last7 if has_data_for(title, fn(iso(d))))
        m_count = sum(1 for d in last30 if has_data_for(title, fn(iso(d))))
        lines.append(f"- {title} — {interval_desc}: week {w_count}/7 days, month {m_count}/30 days")

    lines.append("")
    lines.append("## Range-Based Metrics (last 30 days)")
    for title, interval_desc, fn in per_range_funcs:
        fname = getattr(fn, "__name__", "")
        if fname == "get_daily_steps":
            data = fn((today - timedelta(days=6)).isoformat(), today.isoformat())
            recent_week = isinstance(data, list) and any(
                isinstance(p, dict) and _is_number(p.get("totalSteps")) and p["totalSteps"] > 0 for p in data
            )
            lines.append(f"- {title} — {interval_desc}: week data={recent_week}")
        elif fname == "get_race_predictions":
            d = fn()
            lines.append(f"- {title} — {interval_desc}: available={_deep_numeric_present(d) or bool(d)}")
        else:
            d = fn(start30, end30)
            has = False
            if fname == "get_body_composition":
                if isinstance(d, dict):
                    avg = d.get("totalAverage")
                    if isinstance(avg, dict):
                        w = avg.get("weight") or avg.get("weightInKilograms")
                        has = _is_number(w) and w > 0
                    lst = d.get("dateWeightList")
                    if not has and isinstance(lst, list) and len(lst) > 0:
                        has = True
            elif fname == "get_weigh_ins":
                if isinstance(d, dict):
                    for key in ("dateWeightList", "weighIns", "weights", "weighInList"):
                        lst = d.get(key)
                        if isinstance(lst, list) and len(lst) > 0:
                            has = True
                            break
            else:
                has = _deep_numeric_present(d) or (isinstance(d, list) and len(d) > 0)
            lines.append(f"- {title} — {interval_desc}: month data={has}")

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
