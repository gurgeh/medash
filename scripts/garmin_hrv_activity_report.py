from datetime import date, timedelta, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.garmin_client import GarminClient


def iso(d: date) -> str:
    return d.isoformat()


def find_hrv_activities(activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for act in activities:
        atype = None
        if isinstance(act.get("activityType"), dict):
            atype = act["activityType"].get("typeKey")
        name = (act.get("activityName") or "").lower()
        if (atype and atype in {"breathwork", "hrv", "breathing"}) or "hrv" in name:
            results.append(act)
    return results


def descriptor_map(details: dict[str, Any]) -> dict[int, dict[str, Any]]:
    descs: dict[int, dict[str, Any]] = {}
    for d in details.get("metricDescriptors", []) or []:
        descs[d["metricsIndex"]] = d
    return descs


def format_metric_entry(entry: dict[str, Any], descs: dict[int, dict[str, Any]]) -> dict[str, Any]:
    metrics = entry.get("metrics", [])
    sample: dict[str, Any] = {}
    for idx, value in enumerate(metrics):
        desc = descs.get(idx)
        key = desc.get("key") if desc else f"metric_{idx}"
        if key == "directTimestamp" and isinstance(value, (int, float)):
            sample[key] = datetime.fromtimestamp(value / 1000.0).isoformat()
        else:
            sample[key] = value
    return sample


def main():
    load_dotenv()
    client = GarminClient.from_env()
    client.login()

    today = date.today()
    start = today - timedelta(days=7)

    g = client._client
    activities = g.get_activities_by_date(iso(start), iso(today))
    hrv_activities = find_hrv_activities(activities)

    lines: list[str] = []
    lines.append("# HRV Test Activities\n")
    lines.append(f"Generated on {iso(today)}\n")
    if not hrv_activities:
        lines.append("No HRV test / breathwork activities found in the last 7 days.\n")
    else:
        for act in hrv_activities:
            activity_id = str(act.get("activityId"))
            name = act.get("activityName")
            atype = None
            if isinstance(act.get("activityType"), dict):
                atype = act["activityType"].get("typeKey")
            lines.append(f"## Activity {activity_id} — {atype} — {name}\n")

            summary_fields = {
                "startTimeLocal": act.get("startTimeLocal"),
                "duration": act.get("duration"),
                "calories": act.get("calories"),
                "averageHR": act.get("averageHR"),
                "maxHR": act.get("maxHR"),
                "avgRespirationRate": act.get("avgRespirationRate"),
                "minRespirationRate": act.get("minRespirationRate"),
                "maxRespirationRate": act.get("maxRespirationRate"),
                "avgStress": act.get("avgStress"),
                "startStress": act.get("startStress"),
                "endStress": act.get("endStress"),
                "differenceStress": act.get("differenceStress"),
                "maxStress": act.get("maxStress"),
            }
            lines.append("- Summary:")
            for key, value in summary_fields.items():
                lines.append(f"  - {key}: {value}")

            details = g.get_activity_details(activity_id)
            descs = descriptor_map(details)
            lines.append("- Details:")
            lines.append(
                f"  - metricsCount={details.get('metricsCount')} totalMetricsCount={details.get('totalMetricsCount')}"
            )
            lines.append(
                f"  - metricDescriptors ({len(descs)}): {[d.get('key') for d in details.get('metricDescriptors', [])[:10]]}"
            )
            activity_detail_metrics = details.get("activityDetailMetrics", []) or []
            lines.append(f"  - activityDetailMetrics entries: {len(activity_detail_metrics)}")
            for entry in activity_detail_metrics[:5]:
                sample = format_metric_entry(entry, descs)
                lines.append(f"    - sample: {sample}")

            heart_rate_dtos = details.get("heartRateDTOs") or []
            lines.append(
                f"  - heartRateDTOs samples: {heart_rate_dtos[:5]} (total {len(heart_rate_dtos)})"
            )

            weather = g.get_activity_weather(activity_id)
            lines.append(f"- Weather: {weather}")

            hr_zones = g.get_activity_hr_in_timezones(activity_id)
            lines.append(f"- HR zones in time: {hr_zones}")

            splits = g.get_activity_splits(activity_id)
            lap_dtos = splits.get("lapDTOs", []) if isinstance(splits, dict) else []
            lines.append(f"- Splits lap count: {len(lap_dtos)}")
            if lap_dtos:
                lines.append(f"  - Lap sample: {lap_dtos[0]}")

            typed_splits = g.get_activity_typed_splits(activity_id)
            if isinstance(typed_splits, dict):
                lines.append(
                    f"- Typed splits keys: {list(typed_splits.keys())}, sample: {typed_splits.get('splits', [])[:1]}"
                )

            split_summaries = g.get_activity_split_summaries(activity_id)
            if isinstance(split_summaries, dict):
                lines.append(
                    f"- Split summaries entries: {len(split_summaries.get('splitSummaries', []) or [])}"
                )

            gear = g.get_activity_gear(activity_id)
            lines.append(f"- Gear: {gear}")

            sets = g.get_activity_exercise_sets(activity_id)
            lines.append(f"- Exercise sets: {sets}")

            lines.append("\n")

    Path('memory-bank/garmin_hrv_activity.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print("Wrote memory-bank/garmin_hrv_activity.md")


if __name__ == '__main__':
    main()
