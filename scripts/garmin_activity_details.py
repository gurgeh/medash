from datetime import date, timedelta
from typing import Any

from dotenv import load_dotenv

from src.garmin_client import GarminClient


def iso(d: date) -> str:
    return d.isoformat()


def days(n: int) -> list[date]:
    t = date.today()
    return [t - timedelta(days=i) for i in range(n)]


def _type_of(x: Any) -> str:
    if isinstance(x, list):
        if not x:
            return "list<empty>"
        inner = {type(e).__name__ for e in x}
        return f"list<{','.join(sorted(inner))}>"
    if isinstance(x, dict):
        return "object"
    return type(x).__name__


def _kv(obj: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {k: obj.get(k) for k in keys if k in obj}


def main():
    load_dotenv()
    client = GarminClient.from_env()
    client.login()

    today = date.today()
    start30 = (today - timedelta(days=29)).isoformat()
    end30 = today.isoformat()

    g = client._client
    acts = g.get_activities_by_date(start30, end30)

    lines: list[str] = []
    lines.append("# Garmin Activity Details (last 30 days)\n")
    lines.append(f"Generated on {today.isoformat()}\n")
    lines.append(f"Total activities: {len(acts)}\n")

    for a in acts:
        aid = str(a.get("activityId"))
        atype = (
            (a.get("activityType") or {}).get("typeKey")
            if isinstance(a.get("activityType"), dict)
            else a.get("activityTypeName")
        )
        header = f"## Activity {aid} — {atype} — {a.get('startTimeLocal')}\n"
        lines.append(header)
        lines.append("- Summary fields: " + ", ".join(sorted(list(a.keys()))[:30]))

        # High-level detail
        det = g.get_activity_details(aid)
        lines.append(f"- Details: type={_type_of(det)} keys={list(det.keys())[:20]}")

        # Splits
        splits = g.get_activity_splits(aid)
        lines.append(
            f"- Splits: type={_type_of(splits)} keys={list(splits.keys())[:20]}"
        )
        # Typed splits
        tsplits = g.get_activity_typed_splits(aid)
        lines.append(
            f"- Typed splits: type={_type_of(tsplits)} keys={list(tsplits.keys())[:20]}"
        )
        # Split summaries
        spsum = g.get_activity_split_summaries(aid)
        lines.append(
            f"- Split summaries: type={_type_of(spsum)} keys={list(spsum.keys())[:20]}"
        )

        # Weather
        w = g.get_activity_weather(aid)
        lines.append(f"- Weather: type={_type_of(w)} keys={list(w.keys())[:20]}")

        # HR in timezones
        hrtz = g.get_activity_hr_in_timezones(aid)
        if isinstance(hrtz, dict):
            lines.append(
                f"- HR in timezones: type={_type_of(hrtz)} keys={list(hrtz.keys())[:20]}"
            )
        elif isinstance(hrtz, list):
            if hrtz:
                lines.append(
                    f"- HR in timezones: list with {len(hrtz)} items; sample keys={list(hrtz[0].keys())[:20]}"
                )
            else:
                lines.append("- HR in timezones: list<empty>")
        else:
            lines.append(f"- HR in timezones: type={_type_of(hrtz)}")

        # Gear
        gear = g.get_activity_gear(aid)
        if isinstance(gear, list) and gear:
            lines.append(
                f"- Gear: list with {len(gear)} items; sample keys={list(gear[0].keys())[:20]}"
            )
        else:
            lines.append(f"- Gear: type={_type_of(gear)}")

        # Exercise sets (likely for strength training)
        sets = g.get_activity_exercise_sets(aid)
        if isinstance(sets, list) and sets:
            lines.append(
                f"- Exercise sets: list with {len(sets)} items; sample keys={list(sets[0].keys())[:20]}"
            )
        else:
            lines.append(f"- Exercise sets: type={_type_of(sets)}")

        # A few sample values from the high-level activity summary
        sample_keys = [
            "distance",
            "duration",
            "elapsedDuration",
            "calories",
            "averageHR",
            "maxHR",
            "averageSpeed",
            "elevationGain",
            "elevationLoss",
            "steps",
        ]
        lines.append("- Samples: " + str(_kv(a, sample_keys)))
        lines.append("")

    out = "memory-bank/garmin_activity_details.md"
    with open(out, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
