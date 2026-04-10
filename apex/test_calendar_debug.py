"""
Calendar Debug Test — Raw HTTP version

Tests Google Calendar API directly with raw HTTP requests.
No google-api-python-client dependency needed. Just Python + requests.

Usage: python test_calendar_debug.py

If 'requests' is not installed:  pip install requests
"""

import json
import sys
import time as time_mod
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package not installed. Run: pip install requests")
    sys.exit(1)


TOKEN_FILE = Path("~/.apex/google_token.json").expanduser()
CALENDAR_API = "https://www.googleapis.com/calendar/v3"


def load_token():
    """Load and refresh the Google OAuth token."""
    if not TOKEN_FILE.exists():
        print(f"ERROR: No token file found at {TOKEN_FILE}")
        print("Start the Ziggy server first to authenticate.")
        sys.exit(1)
    
    data = json.loads(TOKEN_FILE.read_text())
    access_token = data.get("token")
    refresh_token = data.get("refresh_token")
    client_id = data.get("client_id")
    client_secret = data.get("client_secret")
    
    # Try the existing access token first
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get(f"{CALENDAR_API}/calendars/primary", headers=headers)
    
    if r.status_code == 401 and refresh_token:
        print("    Access token expired, refreshing...")
        resp = requests.post("https://oauth2.googleapis.com/token", data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        })
        if resp.status_code == 200:
            new_token = resp.json()["access_token"]
            headers = {"Authorization": f"Bearer {new_token}"}
            # Save refreshed token
            data["token"] = new_token
            TOKEN_FILE.write_text(json.dumps(data, indent=2))
            print("    Token refreshed OK")
        else:
            print(f"    ERROR refreshing token: {resp.status_code} {resp.text}")
            sys.exit(1)
    elif r.status_code != 200:
        print(f"    ERROR: API returned {r.status_code}: {r.text[:200]}")
        sys.exit(1)
    
    return headers


def api_get(path, params, headers):
    """Make a GET request to the Calendar API."""
    r = requests.get(f"{CALENDAR_API}{path}", params=params, headers=headers)
    return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text


def main():
    print("=" * 70)
    print("CALENDAR DEBUG TEST (Raw HTTP)")
    print("=" * 70)
    
    # Step 1: Environment
    print("\n[1] ENVIRONMENT")
    print(f"    Python: {sys.version}")
    print(f"    Platform: {sys.platform}")
    print(f"    System timezone: {time_mod.tzname}")
    dst_active = bool(time_mod.daylight and time_mod.localtime().tm_isdst)
    print(f"    DST active: {dst_active}")
    
    if dst_active:
        utc_offset_sec = -time_mod.altzone
    else:
        utc_offset_sec = -time_mod.timezone
    offset_hours = utc_offset_sec // 3600
    offset_mins = abs(utc_offset_sec) % 3600 // 60
    offset_str = f"{offset_hours:+03d}:{offset_mins:02d}"
    print(f"    UTC offset: {offset_str}")
    
    # Step 2: Connect
    print("\n[2] AUTHENTICATING...")
    headers = load_token()
    print("    Authenticated OK")
    
    # Step 3: Get primary calendar info
    print("\n[3] PRIMARY CALENDAR:")
    status, data = api_get("/calendars/primary", {}, headers)
    if status == 200:
        print(f"    ID: {data.get('id')}")
        print(f"    Timezone: {data.get('timeZone')}")
        cal_tz = data.get('timeZone', 'America/New_York')
        primary_id = data.get('id')
    else:
        print(f"    ERROR: {status} {data}")
        return
    
    # Step 4: List all calendars
    print("\n[4] ALL CALENDARS:")
    status, data = api_get("/users/me/calendarList", {}, headers)
    if status == 200:
        calendars = data.get("items", [])
        family_id = None
        owner_writer_cals = []
        for c in calendars:
            role = c.get("accessRole", "?")
            name = c.get("summary", "?")
            cid = c.get("id", "?")
            marker = ""
            if role in ("owner", "writer"):
                marker = f" <-- {role.upper()}"
                owner_writer_cals.append(cid)
            if "family" in name.lower() and "shared" in name.lower():
                family_id = cid
                marker += " *** FAMILY ***"
            print(f"    [{role:6s}] {name:40s} {marker}")
        print(f"\n    Owner/writer calendars: {len(owner_writer_cals)}")
        if family_id:
            print(f"    FAMILY SHARED resolved to: {family_id}")
        else:
            print(f"    WARNING: No 'FAMILY SHARED' calendar found!")
    else:
        print(f"    ERROR: {status}")
    
    # Step 5: Test different timeMin formats against PRIMARY calendar
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    
    print(f"\n[5] TESTING API CALLS ON PRIMARY CALENDAR ({today}):")
    
    test_cases = [
        ("RFC3339 UTC",         f"{today}T00:00:00Z",           f"{tomorrow}T00:00:00Z"),
        ("RFC3339 w/ offset",   f"{today}T00:00:00{offset_str}", f"{tomorrow}T00:00:00{offset_str}"),
        ("Naive (NO tz)",       f"{today}T00:00:00",            f"{tomorrow}T00:00:00"),
    ]
    
    for label, t_min, t_max in test_cases:
        print(f"\n    --- {label} ---")
        print(f"    timeMin={t_min}  timeMax={t_max}")
        params = {
            "timeMin": t_min,
            "timeMax": t_max,
            "maxResults": 50,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        start = time_mod.time()
        status, result = api_get(f"/calendars/{primary_id}/events", params, headers)
        elapsed = time_mod.time() - start
        if status == 200:
            items = result.get("items", [])
            print(f"    Result: {len(items)} events in {elapsed:.2f}s")
            for item in items[:8]:
                s = item.get("start", {}).get("dateTime", item.get("start", {}).get("date", "?"))
                print(f"      - {item.get('summary', '(no title)')} @ {s}")
            if len(items) > 8:
                print(f"      ... and {len(items) - 8} more")
        else:
            err = result if isinstance(result, str) else json.dumps(result.get("error", result), indent=2)
            print(f"    ERROR {status}: {err[:300]}")
    
    # Step 6: Test FAMILY SHARED if found
    if family_id:
        print(f"\n[6] TESTING FAMILY SHARED CALENDAR:")
        params = {
            "timeMin": f"{today}T00:00:00Z",
            "timeMax": f"{tomorrow}T00:00:00Z",
            "maxResults": 50,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        start = time_mod.time()
        status, result = api_get(f"/calendars/{family_id}/events", params, headers)
        elapsed = time_mod.time() - start
        if status == 200:
            items = result.get("items", [])
            print(f"    Result: {len(items)} events in {elapsed:.2f}s")
            for item in items:
                s = item.get("start", {}).get("dateTime", item.get("start", {}).get("date", "?"))
                print(f"      - {item.get('summary', '(no title)')} @ {s}")
        else:
            print(f"    ERROR {status}: {result}")
    
    # Step 7: Test with string "FAMILY SHARED" as calendarId (what was happening before our fix)
    print(f"\n[7] TESTING RAW 'FAMILY SHARED' AS calendarId (the old bug):")
    params = {
        "timeMin": f"{today}T00:00:00Z",
        "timeMax": f"{tomorrow}T00:00:00Z",
        "maxResults": 50,
        "singleEvents": True,
        "orderBy": "startTime",
    }
    status, result = api_get("/calendars/FAMILY SHARED/events", params, headers)
    if status == 200:
        print(f"    Somehow worked: {len(result.get('items', []))} events")
    else:
        err = result if isinstance(result, str) else result.get("error", {}).get("message", str(result))
        print(f"    ERROR {status}: {err}")
        print(f"    (This confirms the name resolution bug was real)")
    
    # Step 8: Test what list_events would produce with our current code
    print(f"\n[8] SIMULATING list_events() CODE PATH:")
    dt_min = datetime.fromisoformat(today)  # naive
    dt_max = dt_min + timedelta(days=1)     # naive
    print(f"    Input: datetime.fromisoformat('{today}') = {dt_min} (tzinfo={dt_min.tzinfo})")
    
    # This is what the code does now:
    if dt_min.tzinfo:
        computed_min = dt_min.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        computed_max = dt_max.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    else:
        computed_min = dt_min.strftime('%Y-%m-%dT%H:%M:%S') + offset_str
        computed_max = dt_max.strftime('%Y-%m-%dT%H:%M:%S') + offset_str
    
    print(f"    Computed timeMin: {computed_min}")
    print(f"    Computed timeMax: {computed_max}")
    params = {
        "timeMin": computed_min,
        "timeMax": computed_max,
        "maxResults": 50,
        "singleEvents": True,
        "orderBy": "startTime",
    }
    start = time_mod.time()
    status, result = api_get(f"/calendars/{primary_id}/events", params, headers)
    elapsed = time_mod.time() - start
    if status == 200:
        items = result.get("items", [])
        print(f"    Result: {len(items)} events in {elapsed:.2f}s")
        for item in items[:8]:
            s = item.get("start", {}).get("dateTime", item.get("start", {}).get("date", "?"))
            print(f"      - {item.get('summary', '(no title)')} @ {s}")
    else:
        err = result if isinstance(result, str) else json.dumps(result.get("error", result), indent=2)
        print(f"    ERROR {status}: {err[:300]}")
    
    # Step 9: Query ALL owner/writer calendars (what list_events does by default)
    if owner_writer_cals:
        print(f"\n[9] QUERYING ALL {len(owner_writer_cals)} OWNER/WRITER CALENDARS:")
        total_events = 0
        for cal_id in owner_writer_cals:
            cal_name = next((c.get("summary") for c in calendars if c.get("id") == cal_id), cal_id)
            params = {
                "timeMin": f"{today}T00:00:00Z",
                "timeMax": f"{tomorrow}T00:00:00Z",
                "maxResults": 50,
                "singleEvents": True,
                "orderBy": "startTime",
            }
            start = time_mod.time()
            status, result = api_get(f"/calendars/{cal_id}/events", params, headers)
            elapsed = time_mod.time() - start
            if status == 200:
                items = result.get("items", [])
                total_events += len(items)
                if items:
                    print(f"    {cal_name}: {len(items)} events ({elapsed:.2f}s)")
                    for item in items[:3]:
                        s = item.get("start", {}).get("dateTime", item.get("start", {}).get("date", "?"))
                        print(f"      - {item.get('summary', '(no title)')} @ {s}")
                else:
                    print(f"    {cal_name}: 0 events ({elapsed:.2f}s)")
            else:
                print(f"    {cal_name}: ERROR {status}")
        print(f"\n    TOTAL: {total_events} events across {len(owner_writer_cals)} calendars")
    
    print("\n" + "=" * 70)
    print("DONE. Copy/paste ALL output above.")
    print("=" * 70)


if __name__ == "__main__":
    main()
