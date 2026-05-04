from datetime import date, datetime, timedelta
from statistics import mean
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


def _collect_numbers(x: Any) -> list[float]:
    # Traverse nested data and return numeric values, skipping timestamps.
    nums: list[float] = []
    if _is_number(x):
        nums.append(float(x))
    elif isinstance(x, list):
        for e in x:
            if isinstance(e, (list, tuple)) and len(e) >= 2 and _is_number(e[1]):
                nums.append(float(e[1]))
            else:
                nums.extend(_collect_numbers(e))
    elif isinstance(x, dict):
        skip_keys = {
            "calendarDate",
            "startGMT",
            "endGMT",
            "valueStartDate",
            "valueEndDate",
            "measurementSystem",
            "timeOffset",
            "userId",
            "userProfileId",
            "fullName",
            "displayName",
            "summaryId",
        }
        for k, v in x.items():
            if k in skip_keys:
                continue
            nums.extend(_collect_numbers(v))
    return nums


def _type_of(x: Any) -> str:
    if isinstance(x, list):
        if not x:
            return "list<empty>"
        inner = {type(e).__name__ for e in x}
        return f"list<{','.join(sorted(inner))}>"
    if isinstance(x, dict):
        return "object"
    return type(x).__name__


def _sample_values_for_metric(name: str, payload: Any) -> list[Any]:
    n = name.lower()
    out: list[Any] = []
    if n.startswith("steps ("):
        if isinstance(payload, list):
            for e in payload[:3]:
                if isinstance(e, dict):
                    out.append({k: e.get(k) for k in ("startGMT", "endGMT", "steps")})
            return out
    if n == "heart rate" and isinstance(payload, dict):
        hr = payload.get("heartRateValues") or payload.get("heartRate")
        if isinstance(hr, list):
            for e in hr[:3]:
                if isinstance(e, (list, tuple)) and len(e) >= 2:
                    ts, v = e[0], e[1]
                    out.append({"t": ts, "bpm": v})
            return out
    if isinstance(payload, dict):
        # Pick three numeric top-level fields if any, else three arbitrary items
        numeric_items = [(k, v) for k, v in payload.items() if _is_number(v)]
        if numeric_items:
            for k, v in numeric_items[:3]:
                out.append({k: v})
            return out
        for k in list(payload.keys())[:3]:
            out.append({k: payload.get(k)})
        return out
    if isinstance(payload, list):
        return payload[:3]
    return [payload]


def _stats(nums: list[float]) -> dict[str, float]:
    return {
        "min": min(nums),
        "max": max(nums),
        "mean": mean(nums),
        "count": float(len(nums)),
    }


def _resolution_hint(name: str, payload: Any) -> str:
    n = name.lower()
    if n.startswith("steps (") and isinstance(payload, list) and len(payload) >= 2:
        # Derive minutes between first two intervals
        def parse_gmt(s: str) -> datetime:
            # Example: 2025-09-27T22:00:00.0
            if "." in s and not s.endswith("Z"):
                return datetime.fromisoformat(s)
            return datetime.fromisoformat(s.replace("Z", "+00:00"))

        a = payload[0]
        b = payload[1]
        if isinstance(a, dict) and isinstance(b, dict):
            dt1 = parse_gmt(a.get("startGMT"))
            dt2 = parse_gmt(b.get("startGMT"))
            mins = int((dt2 - dt1).total_seconds() // 60)
            return f"~{mins} min intervals"
        return "intervals"
    if n == "heart rate" and isinstance(payload, dict):
        hr = payload.get("heartRateValues") or []
        if isinstance(hr, list) and len(hr) >= 2:
            a, b = hr[0], hr[1]
            if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
                t0, t1 = a[0], b[0]
                if _is_number(t0) and _is_number(t1):
                    # appears to be epoch ms
                    dt = (float(t1) - float(t0)) / 1000.0
                    return f"~{int(dt)} s samples"
        return "variable sampling"
    # Otherwise treat as daily
    return "daily"


def generate_report(client: GarminClient) -> str:
    today = date.today()
    last7 = list(reversed(days(7)))
    start30 = (today - timedelta(days=29)).isoformat()
    end30 = today.isoformat()

    g = client._client

    per_day: list[tuple[str, Callable[[str], Any]]] = [
        ("Steps (15-min intervals)", g.get_steps_data),
        ("Heart rate", g.get_heart_rates),
        ("Sleep", g.get_sleep_data),
        ("Stress", g.get_stress_data),
        ("SpO2", g.get_spo2_data),
        ("Respiration", g.get_respiration_data),
        ("Intensity minutes", g.get_intensity_minutes_data),
        ("Resting HR (RHR)", g.get_rhr_day),
        ("HRV", g.get_hrv_data),
        ("Floors", g.get_floors),
        ("Hydration", g.get_hydration_data),
        ("Daily weigh-ins", g.get_daily_weigh_ins),
        ("User summary", g.get_user_summary),
        ("Stats", g.get_stats),
        ("Stats + body", g.get_stats_and_body),
        ("Body Battery events", g.get_body_battery_events),
        ("Training readiness", g.get_training_readiness),
        ("Training status", g.get_training_status),
        ("Max metrics", g.get_max_metrics),
    ]

    per_range: list[tuple[str, Callable[..., Any]]] = [
        ("Daily steps (totals)", g.get_daily_steps),
        ("Body Battery", g.get_body_battery),
        ("Body composition", g.get_body_composition),
        ("Weigh-ins", g.get_weigh_ins),
        ("Endurance score", g.get_endurance_score),
        ("Hill score", g.get_hill_score),
        ("Race predictions", g.get_race_predictions),
    ]

    lines: list[str] = []
    lines.append(f"# Garmin Data Details\n")
    lines.append(f"Generated on {today.isoformat()}\n")

    lines.append("## Per-Day Metrics")
    for title, fn in per_day:
        # Find up to 3 recent days with data
        ds = []
        payloads = []
        for d in last7:
            p = fn(iso(d))
            # consider data present if we can collect any numbers from it
            nums = _collect_numbers(p)
            if nums or (isinstance(p, list) and len(p) > 0) or (isinstance(p, dict) and len(p) > 0):
                ds.append(d)
                payloads.append(p)
            if len(ds) == 3:
                break

        lines.append(f"- Metric: {title}")
        if not payloads:
            lines.append("  - Data: none in last 7 days")
            continue

        # Type and resolution from first payload
        p0 = payloads[0]
        lines.append(f"  - Type: {_type_of(p0)}")
        lines.append(f"  - Resolution: {_resolution_hint(title, p0)}")

        # Stats from first payload numeric values
        nums0 = _collect_numbers(p0)
        if nums0:
            st = _stats(nums0)
            lines.append(
                f"  - Stats (sample day): min={st['min']:.3f}, max={st['max']:.3f}, mean={st['mean']:.3f}, count={int(st['count'])}"
            )

        # Sample values (up to 3) from first payload
        samples = _sample_values_for_metric(title, p0)
        for i, s in enumerate(samples[:3], 1):
            lines.append(f"  - Sample {i}: {s}")

        # Object keys for first payload if it's an object
        if isinstance(p0, dict):
            keys = list(p0.keys())
            lines.append(f"  - Object keys ({len(keys)}): {keys[:20]}")

    lines.append("")
    lines.append("## Range Metrics (weekly/monthly)")
    for title, fn in per_range:
        lines.append(f"- Metric: {title}")
        fname = getattr(fn, "__name__", "")
        if fname == "get_daily_steps":
            d = fn((today - timedelta(days=6)).isoformat(), today.isoformat())
            lines.append(f"  - Type: {_type_of(d)}")
            nums = _collect_numbers(d)
            if nums:
                st = _stats(nums)
                lines.append(
                    f"  - Stats (last 7 days): min={st['min']:.3f}, max={st['max']:.3f}, mean={st['mean']:.3f}, count={int(st['count'])}"
                )
            if isinstance(d, list) and d:
                lines.append(f"  - Sample 1: {{'date': {d[0].get('calendarDate')}, 'totalSteps': {d[0].get('totalSteps')}}}")
        elif fname == "get_race_predictions":
            d = fn()
            lines.append(f"  - Type: {_type_of(d)}")
            if isinstance(d, dict):
                lines.append(f"  - Keys: {list(d.keys())[:20]}")
        else:
            d = fn(start30, end30)
            lines.append(f"  - Type: {_type_of(d)}")
            nums = _collect_numbers(d)
            if nums:
                st = _stats(nums)
                lines.append(
                    f"  - Stats (last 30 days): min={st['min']:.3f}, max={st['max']:.3f}, mean={st['mean']:.3f}, count={int(st['count'])}"
                )
            if isinstance(d, dict):
                lines.append(f"  - Keys: {list(d.keys())[:20]}")

    lines.append("")
    lines.append("## Activities — Last 30 Days")
    acts = g.get_activities_by_date(start30, end30)
    lines.append(f"Total activities: {len(acts)}")

    # Group by type
    def act_type(a: dict) -> str:
        t = None
        if isinstance(a.get("activityType"), dict):
            t = a["activityType"].get("typeKey") or a["activityType"].get("typeId")
        if not t:
            t = a.get("activityTypeName") or a.get("type") or str(a.get("activityTypeId"))
        return str(t)

    groups: dict[str, list[dict]] = {}
    for a in acts:
        groups.setdefault(act_type(a), []).append(a)

    cand_numeric = [
        "distance",
        "duration",
        "elapsedDuration",
        "averageHR",
        "maxHR",
        "averageSpeed",
        "maxSpeed",
        "elevationGain",
        "elevationLoss",
        "calories",
        "steps",
        "movingDuration",
        "trainingEffect",
        "aerobicTrainingEffect",
        "anaerobicTrainingEffect",
    ]

    for t, arr in sorted(groups.items(), key=lambda kv: kv[0]):
        lines.append(f"- Type: {t} — count {len(arr)}")
        a0 = arr[0]
        keys = list(a0.keys())
        lines.append(f"  - Activity keys ({len(keys)}): {keys[:20]}")
        # Samples
        for i, a in enumerate(arr[:3], 1):
            samp = {
                k: a.get(k)
                for k in (
                    "startTimeLocal",
                    "distance",
                    "duration",
                    "calories",
                    "averageHR",
                    "averageSpeed",
                )
                if k in a
            }
            lines.append(f"  - Sample {i}: {samp}")
        # Summary stats per numeric field present
        for k in cand_numeric:
            vals = [v.get(k) for v in arr if _is_number(v.get(k))]
            if vals:
                lines.append(
                    f"  - {k}: min={min(vals):.3f}, max={max(vals):.3f}, mean={mean(vals):.3f}, count={len(vals)}"
                )

    lines.append("")
    lines.append("Notes: activity details (splits, laps, weather, HR-in-timezones, gear, sets) are retrievable via detail endpoints and can be added next.")

    return "\n".join(lines) + "\n"


def main():
    load_dotenv()
    client = GarminClient.from_env()
    client.login()
    content = generate_report(client)
    out = "memory-bank/garmin_inventory_detailed.md"
    with open(out, "w") as f:
        f.write(content)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
