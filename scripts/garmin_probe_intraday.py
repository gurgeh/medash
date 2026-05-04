from datetime import date, timedelta, datetime, timezone
import os

from dotenv import load_dotenv

from src.garmin_client import GarminClient


def iso(d: date) -> str:
    return d.isoformat()


def secs_per_sample_from_window(start_ms: int, end_ms: int, n: int) -> float:
    # start/end are epoch ms (inclusive/exclusive ambiguous); use max(1,n)
    if n <= 0:
        return 0.0
    span_s = (end_ms - start_ms) / 1000.0
    if span_s <= 0:
        return 0.0
    return span_s / n


def main():
    load_dotenv()
    client = GarminClient.from_env()
    client.login()

    today = date.today()
    days = [today - timedelta(days=i) for i in range(0, 3)]

    for d in days:
        ds = iso(d)
        print(f"\n=== {ds} ===")

        # Steps (15-min intervals)
        steps = client._client.get_steps_data(ds)
        print(f"steps intervals: {len(steps)} entries (expect ~96 for full day)")
        if steps:
            first = steps[0]
            last = steps[-1]
            print("  first block:", first.get("startGMT"), "->", first.get("endGMT"), "steps=", first.get("steps"))
            print("  last  block:", last.get("startGMT"), "->", last.get("endGMT"), "steps=", last.get("steps"))

        # Stress daily
        stress = client._client.get_stress_data(ds)
        # Expected keys include stressValuesArray, stressValueDescriptorsDTOList and time bounds
        sv = stress.get("stressValuesArray")
        sdesc = stress.get("stressValueDescriptorsDTOList")
        start_gmt = stress.get("startTimestampGMT")
        end_gmt = stress.get("endTimestampGMT")
        print("stress entries:", None if sv is None else len(sv))
        if sdesc is not None:
            print("  stress descriptors keys:", [k for k in sdesc[0].keys()] if isinstance(sdesc, list) and sdesc else type(sdesc))
        if isinstance(start_gmt, (int, float)) and isinstance(end_gmt, (int, float)) and isinstance(sv, list):
            approx = secs_per_sample_from_window(int(start_gmt), int(end_gmt), len(sv))
            print(f"  stress approx secs/sample: {approx:.2f}")

        # Body battery can appear in stress daily payload
        bb_arr = stress.get("bodyBatteryValuesArray")
        bb_desc = stress.get("bodyBatteryValueDescriptorsDTOList")
        print("body_battery (from stress daily) entries:", None if bb_arr is None else len(bb_arr))
        if bb_desc is not None:
            print("  bb descriptors keys:", [k for k in bb_desc[0].keys()] if isinstance(bb_desc, list) and bb_desc else type(bb_desc))
        if isinstance(start_gmt, (int, float)) and isinstance(end_gmt, (int, float)) and isinstance(bb_arr, list):
            approx_bb = secs_per_sample_from_window(int(start_gmt), int(end_gmt), len(bb_arr))
            print(f"  bb approx secs/sample: {approx_bb:.2f}")

        # Body battery daily reports (range API)
        bb_list = client._client.get_body_battery(ds, ds)
        print("body_battery reports (daily API) count:", None if bb_list is None else len(bb_list))
        if isinstance(bb_list, list) and bb_list:
            keys = list(bb_list[0].keys())
            print("  sample daily keys:", keys[:20])

        # All-day stress endpoint (if available)
        try:
            ad_stress = client._client.get_all_day_stress(ds)
            if isinstance(ad_stress, dict):
                vals = ad_stress.get("allDayStress") or ad_stress.get("stressValuesArray")
                print("all_day_stress entries:", None if vals is None else len(vals))
                if isinstance(vals, list) and vals:
                    # try to infer period from length using 24h window
                    approx2 = (24*3600)/len(vals)
                    print(f"  all_day_stress approx secs/sample: {approx2:.2f}")
                print("  all_day_stress keys:", list(ad_stress.keys())[:20])
        except Exception as e:
            print("get_all_day_stress not available:", e)


if __name__ == "__main__":
    main()
