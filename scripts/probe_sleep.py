from datetime import date, timedelta
from pprint import pprint

from dotenv import load_dotenv

from src.garmin_client import GarminClient


def iso(d: date) -> str:
    return d.isoformat()


def main() -> None:
    load_dotenv()
    client = GarminClient.from_env()
    client.login()
    g = client._client

    today = date.today()
    for i in range(0, 1):
        d = today - timedelta(days=i)
        ds = iso(d)
        print(f"\n=== {ds} ===")
        s = g.get_sleep_data(ds)
        if isinstance(s, dict):
            print('sleep keys:', list(s.keys())[:40])
            for k in ['sleepStartTimestampLocal','sleepEndTimestampLocal','sleepStartTimestampGMT','sleepEndTimestampGMT','durationInSeconds','sleepTimeInSeconds','overallScore','sleepScores','summary','dailySleepDTO','sleepLevelsMap','sleepSegments','sleepProfile']:
                if k in s:
                    v = s[k]
                    print(' ', k, type(v).__name__)
            daily = s.get('dailySleepDTO') or {}
            if isinstance(daily, dict):
                print(' dailySleepDTO keys:', list(daily.keys())[:50])
                print('  types:', type(daily.get('sleepStartTimestampLocal')).__name__, type(daily.get('sleepEndTimestampLocal')).__name__, type(daily.get('sleepStartTimestampGMT')).__name__, type(daily.get('sleepEndTimestampGMT')).__name__)
                print('  stage seconds (deep/light/rem/awake):', daily.get('deepSleepSeconds'), daily.get('lightSleepSeconds'), daily.get('remSleepSeconds'), daily.get('awakeSleepSeconds'))
            levels = s.get('sleepLevels')
            print(' sleepLevels type:', type(levels).__name__)
            if isinstance(levels, dict):
                print(' sleepLevels keys:', list(levels.keys())[:50])
                # Try to show a levels sample
                arr = levels.get('levels') or levels.get('entries') or levels.get('sleepLevels')
                if isinstance(arr, list) and arr:
                    print(' levels[0] keys:', list(arr[0].keys()))
                    print(' levels[0]:', arr[0])
            elif isinstance(levels, list) and levels:
                print(' levels[0] keys:', list(levels[0].keys()))
                print(' levels[0]:', levels[0])
                codes = sorted({e.get('activityLevel') for e in levels if isinstance(e, dict)})
                print(' unique activityLevel codes:', codes)
                # Duration per code (seconds)
                from datetime import datetime as _dt
                acc = {}
                for e in levels:
                    if not isinstance(e, dict):
                        continue
                    st = e.get('startGMT'); en = e.get('endGMT'); code = e.get('activityLevel')
                    if not (isinstance(st, str) and isinstance(en, str)):
                        continue
                    dur = (_dt.strptime(en, '%Y-%m-%dT%H:%M:%S.0') - _dt.strptime(st, '%Y-%m-%dT%H:%M:%S.0')).total_seconds()
                    acc[code] = acc.get(code, 0) + dur
                print(' seconds per code:', {k: int(v) for k, v in sorted(acc.items())})
        r = g.get_respiration_data(ds)
        if isinstance(r, dict):
            print('respiration keys:', list(r.keys())[:40])
        o = g.get_spo2_data(ds)
        if isinstance(o, dict):
            print('spo2 keys:', list(o.keys())[:40])
        hr = s.get('sleepHeartRate')
        print('sleepHeartRate type:', type(hr).__name__)
        if isinstance(hr, dict):
            print(' sleepHeartRate keys:', list(hr.keys()))
        elif isinstance(hr, list) and hr:
            print(' sleepHeartRate sample[0] keys:', list(hr[0].keys()))
        st = s.get('sleepStress')
        print('sleepStress type:', type(st).__name__)
        if isinstance(st, dict):
            print(' sleepStress keys:', list(st.keys()))
        elif isinstance(st, list) and st:
            print(' sleepStress sample[0] keys:', list(st[0].keys()))
        bb = s.get('sleepBodyBattery')
        print('sleepBodyBattery type:', type(bb).__name__)
        if isinstance(bb, dict):
            print(' sleepBodyBattery keys:', list(bb.keys()))
        elif isinstance(bb, list) and bb:
            print(' sleepBodyBattery sample[0] keys:', list(bb[0].keys()))


if __name__ == '__main__':
    main()
