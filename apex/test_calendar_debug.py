"""
Calendar Debug Test
Run this on your local machine to diagnose exactly what's happening.

Usage: python test_calendar_debug.py
"""

import asyncio
import sys
import time as time_mod
from datetime import datetime, timedelta, timezone


async def main():
    print("=" * 60)
    print("CALENDAR DEBUG TEST")
    print("=" * 60)
    
    # Step 1: Check environment
    print("\n[1] ENVIRONMENT")
    print(f"    Python: {sys.version}")
    print(f"    Platform: {sys.platform}")
    print(f"    System timezone: {time_mod.tzname}")
    print(f"    DST active: {bool(time_mod.daylight and time_mod.localtime().tm_isdst)}")
    
    # Step 2: Connect
    print("\n[2] CONNECTING TO GOOGLE CALENDAR...")
    from connectors.calendar import CalendarConnector
    cal = CalendarConnector()
    ok = await cal.connect()
    if not ok:
        print("    FAILED to connect. Check credentials.")
        return
    print(f"    Connected: True")
    print(f"    Primary calendar: {cal._primary_calendar}")
    print(f"    Calendar timezone: {cal._calendar_timezone}")
    print(f"    Cached calendars: {len(cal._calendars)}")
    
    # Step 3: List all calendars and their access roles
    print("\n[3] ALL CALENDARS:")
    for c in cal._calendars:
        role = c.get('accessRole', '?')
        name = c.get('summary', '?')
        cid = c.get('id', '?')
        marker = " <-- OWNER" if role == 'owner' else (" <-- WRITER" if role == 'writer' else "")
        print(f"    [{role:6s}] {name:40s} {cid[:50]}{marker}")
    
    # Step 4: Test the EXACT API call that list_events makes
    print("\n[4] TESTING API CALLS WITH DIFFERENT timeMin FORMATS:")
    
    today = "2026-04-10"
    tomorrow = "2026-04-11"
    
    formats_to_test = [
        ("RFC3339 UTC (Z suffix)", f"{today}T00:00:00Z", f"{tomorrow}T00:00:00Z"),
        ("RFC3339 with offset (-04:00)", f"{today}T00:00:00-04:00", f"{tomorrow}T00:00:00-04:00"),
        ("Naive (NO timezone)", f"{today}T00:00:00", f"{tomorrow}T00:00:00"),
        ("Date only", today, tomorrow),
    ]
    
    service = cal._service
    primary_id = cal._primary_calendar or 'primary'
    
    for label, t_min, t_max in formats_to_test:
        print(f"\n    --- {label} ---")
        print(f"    timeMin={t_min}  timeMax={t_max}")
        try:
            start = time_mod.time()
            request = service.events().list(
                calendarId=primary_id,
                timeMin=t_min,
                timeMax=t_max,
                maxResults=50,
                singleEvents=True,
                orderBy='startTime',
            )
            result = await asyncio.to_thread(request.execute)
            elapsed = time_mod.time() - start
            items = result.get('items', [])
            print(f"    Result: {len(items)} events in {elapsed:.2f}s")
            for item in items[:5]:
                s = item.get('start', {}).get('dateTime', item.get('start', {}).get('date', '?'))
                print(f"      - {item.get('summary', '(no title)')} @ {s}")
            if len(items) > 5:
                print(f"      ... and {len(items) - 5} more")
        except Exception as e:
            print(f"    ERROR: {type(e).__name__}: {e}")
    
    # Step 5: Test with timeZone parameter (my previous fix attempt)
    print(f"\n    --- Naive + timeZone param ---")
    t_min = f"{today}T00:00:00"
    t_max = f"{tomorrow}T00:00:00"
    cal_tz = cal._calendar_timezone or 'America/New_York'
    print(f"    timeMin={t_min}  timeMax={t_max}  timeZone={cal_tz}")
    try:
        start = time_mod.time()
        request = service.events().list(
            calendarId=primary_id,
            timeMin=t_min,
            timeMax=t_max,
            maxResults=50,
            singleEvents=True,
            orderBy='startTime',
            timeZone=cal_tz,
        )
        result = await asyncio.to_thread(request.execute)
        elapsed = time_mod.time() - start
        items = result.get('items', [])
        print(f"    Result: {len(items)} events in {elapsed:.2f}s")
        for item in items[:5]:
            s = item.get('start', {}).get('dateTime', item.get('start', {}).get('date', '?'))
            print(f"      - {item.get('summary', '(no title)')} @ {s}")
    except Exception as e:
        print(f"    ERROR: {type(e).__name__}: {e}")
    
    # Step 6: Test the FAMILY SHARED calendar resolution
    print("\n[5] TESTING FAMILY SHARED RESOLUTION:")
    family_id = None
    for c in cal._calendars:
        name = (c.get('summary') or '').lower()
        if 'family' in name and 'shared' in name:
            family_id = c.get('id')
            print(f"    Found: '{c.get('summary')}' -> {family_id}")
            break
    
    if not family_id:
        print("    WARNING: No calendar matching 'FAMILY SHARED' found!")
        print("    Available calendars:")
        for c in cal._calendars:
            print(f"      - {c.get('summary')}")
    else:
        print(f"    Querying FAMILY SHARED ({family_id}) with RFC3339 UTC...")
        try:
            request = service.events().list(
                calendarId=family_id,
                timeMin=f"{today}T00:00:00Z",
                timeMax=f"{tomorrow}T00:00:00Z",
                maxResults=50,
                singleEvents=True,
                orderBy='startTime',
            )
            result = await asyncio.to_thread(request.execute)
            items = result.get('items', [])
            print(f"    Result: {len(items)} events")
            for item in items:
                s = item.get('start', {}).get('dateTime', item.get('start', {}).get('date', '?'))
                print(f"      - {item.get('summary', '(no title)')} @ {s}")
        except Exception as e:
            print(f"    ERROR: {type(e).__name__}: {e}")

    # Step 7: Test the full list_events method as called by the engine
    print("\n[6] TESTING list_events() AS ENGINE CALLS IT:")
    print(f"    Params: time_min=datetime(2026,4,10), time_max=datetime(2026,4,11)")
    try:
        start = time_mod.time()
        events = await cal.list_events(
            time_min=datetime(2026, 4, 10),
            time_max=datetime(2026, 4, 11),
        )
        elapsed = time_mod.time() - start
        print(f"    Result: {len(events)} events in {elapsed:.2f}s")
        for e in events[:10]:
            print(f"      - {e.summary} @ {e.start}")
    except Exception as e:
        print(f"    ERROR: {type(e).__name__}: {e}")

    print("\n" + "=" * 60)
    print("DONE. Copy/paste the output above so we can fix the issue.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
