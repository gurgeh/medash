from datetime import datetime, timezone
from statistics import mean
from typing import Any, Dict, Iterable, List

from dotenv import load_dotenv
from withings_api.common import MeasureType, MeasureGetMeasGroupCategory

from src.withings_client import WithingsClient


def _as_type_id(mtype: Any) -> int:
    if isinstance(mtype, MeasureType):
        return int(mtype.value)
    try:
        return int(mtype)
    except Exception:
        return -1


def _iter_measures(measures: Iterable[Any]) -> Iterable[Dict[str, Any]]:
    for m in measures or []:
        if isinstance(m, dict):
            yield m
        else:
            # withings-api returns typed objects; adapt to dict-like
            yield {
                "type": getattr(m, "type", None),
                "value": getattr(m, "value", None),
                "unit": getattr(m, "unit", None),
            }


def decode_measures(measures: Iterable[Any]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for m in _iter_measures(measures):
        mtype = _as_type_id(m.get("type"))
        val = m.get("value")
        unit = m.get("unit")  # power of 10 exponent
        if val is None or unit is None:
            continue
        scaled = float(val) * (10 ** float(unit))
        try:
            key = MeasureType(mtype).name.lower()
        except Exception:
            key = f"type_{mtype}"
        out[key] = scaled
    return out


def main():
    load_dotenv()
    client = WithingsClient.from_tokens_file()
    # Sanity: print devices
    try:
        devices = client.api.user_get_device().devices
        print("Devices:", [d.model for d in devices])
    except Exception as e:
        print("user_get_device failed:", e)

    # Expand window and force REAL category; fetch all measures first
    end = datetime.utcnow()
    from datetime import timedelta as _td
    start = end - _td(days=120)
    resp = client.api.measure_get_meas(
        startdate=start,
        enddate=end,
        category=MeasureGetMeasGroupCategory.REAL,
        lastupdate=None,
    )
    groups = getattr(resp, "measuregrps", []) or []
    print("All measures groups (120d):", len(groups))

    # If still zero, try weight-only
    if not groups:
        resp = client.api.measure_get_meas(
            startdate=start,
            enddate=end,
            category=MeasureGetMeasGroupCategory.REAL,
            meastype=MeasureType.WEIGHT,
            lastupdate=None,
        )
        groups = getattr(resp, "measuregrps", []) or []
        print("Weight-only groups (120d):", len(groups))

    # Decode groups
    decoded: List[Dict[str, Any]] = []
    for g in groups:
        dval = getattr(g, "date", 0)
        if hasattr(dval, "int_timestamp"):
            ts = int(dval.int_timestamp)
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        else:
            try:
                ts = int(dval)
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                # Fallback to string
                dt = datetime.fromtimestamp(0, tz=timezone.utc)
        row = {
            "datetime_utc": dt.isoformat(),
            "category": getattr(g, "category", None),
        }
        row.update(decode_measures(getattr(g, "measures", []) or []))
        decoded.append(row)

    # Print quick preview
    print(f"Groups: {len(groups)}")
    for r in decoded[:5]:
        print(r)

    # Write markdown summary
    lines: List[str] = []
    lines.append("# Withings Measures (last 30 days)\n")
    lines.append(f"Total groups: {len(decoded)}\n")

    # Compute simple stats for weight if present
    weights = [r.get("weight") for r in decoded if isinstance(r.get("weight"), (int, float))]
    if weights:
        lines.append(
            f"Weight (kg): min={min(weights):.2f}, max={max(weights):.2f}, mean={mean(weights):.2f}\n"
        )

    # Table header
    keys = [
        "datetime_utc",
        "weight",
        "fat_mass_weight",
        "fat_ratio",
        "fat_free_mass",
        "muscle_mass",
        "bone_mass",
        "hydration",
        "pulse_wave_velocity",
    ]
    lines.append("| " + " | ".join(keys) + " |")
    lines.append("|" + "|".join([" --- "] * len(keys)) + "|")
    for r in decoded:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(r.get(k, "")) if not isinstance(r.get(k), float) else f"{r.get(k):.2f}"
                    for k in keys
                ]
            )
            + " |"
        )

    out = "memory-bank/withings_measures.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
