#!/usr/bin/env python3
"""The next daily-run times (08:05 London, Sunday to Friday) in UTC, for booking the run's wake-ups.

  python3 tools/next_runs.py [--from ISO] [--n 2]

Prints one RFC3339 UTC time per line, the first --n run times after --from (default: now). Saturdays are skipped
(Shabbat). 08:05 London is always after Google's daily speech reset (midnight Pacific: 07:00 or 08:00 London).
"""
import argparse
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")


def next_runs(now, n=2):
    out, d = [], now.astimezone(LONDON).date()
    while len(out) < n:
        t = datetime.combine(d, time(8, 5), tzinfo=LONDON)
        if t > now and t.weekday() != 5:
            out.append(t.astimezone(timezone.utc))
        d += timedelta(days=1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start")
    ap.add_argument("--n", type=int, default=2)
    a = ap.parse_args()
    now = datetime.fromisoformat(a.start.replace("Z", "+00:00")) if a.start else datetime.now(timezone.utc)
    for t in next_runs(now, a.n):
        print(t.strftime("%Y-%m-%dT%H:%M:%SZ"))


if __name__ == "__main__":
    main()
