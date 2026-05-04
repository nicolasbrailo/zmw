"""Generate an hourly weather report from Open-Meteo.

Pulls hourly + daily forecast for a fixed location and emits a structured
report with these blocks:
  - +1h, +2h (single-hour blocks)
  - morning / afternoon / evening (aggregated, only if still upcoming today)
  - tomorrow (full-day summary including precipitation)

Each block has a weather category from:
  sunny | cloudy | rain | rain-moderate | rain-heavy |
  windy | thunder | sunny-cloudy | sunny-rainy
"""

import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta


API_URL = "https://api.open-meteo.com/v1/forecast"

# Wind speed (km/h) above which a block is reclassified as "windy"
# unless thunder or heavy rain dominates.
WINDY_THRESHOLD_KMH = 40.0

# Day-part hour ranges (local time, end-exclusive).
MORNING = range(6, 12)
AFTERNOON = range(12, 18)
EVENING = range(18, 23)

# Severity order — higher index wins when aggregating multiple hours.
_SEVERITY = [
    "sunny",
    "sunny-cloudy",
    "cloudy",
    "sunny-rainy",
    "windy",
    "rain",
    "rain-moderate",
    "rain-heavy",
    "thunder",
]


def _classify(weather_code, wind_kmh):
    """Map a WMO weather code (+ wind speed) to one of our categories."""
    code = int(weather_code)

    if code in (95, 96, 99):
        cat = "thunder"
    elif code in (65, 82):
        cat = "rain-heavy"
    elif code in (63, 67, 81):
        cat = "rain-moderate"
    elif code in (61, 66, 80):
        # Light rain; treat as sunny-rainy if it's a shower (80), else rain.
        cat = "sunny-rainy" if code == 80 else "rain"
    elif code in (51, 53, 55, 56, 57):
        cat = "rain"  # drizzle
    elif code in (71, 73, 75, 77, 85, 86):
        # No snow category; map snow to rain-equivalent severity.
        cat = "rain-moderate" if code in (73, 75, 86) else "rain"
    elif code in (45, 48):
        cat = "cloudy"  # fog
    elif code == 3:
        cat = "cloudy"
    elif code in (1, 2):
        cat = "sunny-cloudy"
    elif code == 0:
        cat = "sunny"
    else:
        cat = "cloudy"

    # Override mild categories with "windy" if wind dominates.
    if wind_kmh >= WINDY_THRESHOLD_KMH and cat in ("sunny", "sunny-cloudy", "cloudy"):
        cat = "windy"

    return cat


def _aggregate(cats):
    """Pick the most severe category from a list."""
    return max(cats, key=lambda c: _SEVERITY.index(c) if c in _SEVERITY else -1)


def _fetch(lat, lon, tz):
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": tz,
        "hourly": "temperature_2m,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                 "precipitation_sum,wind_speed_10m_max",
        "forecast_days": 2,
    }
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _parse_hourly(data):
    """Return a list of (datetime, temp_c, code, wind_kmh) tuples."""
    h = data["hourly"]
    out = []
    for i, ts in enumerate(h["time"]):
        out.append((
            datetime.fromisoformat(ts),
            float(h["temperature_2m"][i]),
            int(h["weather_code"][i]),
            float(h["wind_speed_10m"][i]),
        ))
    return out


def _block_from_hours(hours):
    """Build a block dict from a list of hourly tuples."""
    if not hours:
        return None
    temps = [t for _, t, _, _ in hours]
    cats = [_classify(c, w) for _, _, c, w in hours]
    return {
        "category": _aggregate(cats),
        "temp_min": min(temps),
        "temp_max": max(temps),
    }


def build_weather_report(lat, lon, tz, now=None):
    """Build the structured report. `now` is overridable for tests."""
    data = _fetch(lat, lon, tz)
    hourly = _parse_hourly(data)
    if now is None:
        now = datetime.now()

    today = now.date()
    tomorrow = today + timedelta(days=1)

    # Index hourly entries by absolute datetime (truncated to the hour).
    by_hour = {dt.replace(minute=0, second=0, microsecond=0): (dt, t, c, w)
               for dt, t, c, w in hourly}

    def hour_at(offset_h):
        target = (now.replace(minute=0, second=0, microsecond=0)
                  + timedelta(hours=offset_h))
        return by_hour.get(target)

    blocks = []

    for offset in (1, 2):
        entry = hour_at(offset)
        if entry:
            b = _block_from_hours([entry])
            b["label"] = entry[0].strftime("%H:%M")
            blocks.append(b)

    def day_part(label, hour_range):
        # Only include if the *end* of the range is still in the future today.
        if now.hour >= hour_range.stop:
            return
        hours_in = [
            entry for entry in hourly
            if entry[0].date() == today and entry[0].hour in hour_range
            and entry[0] >= now
        ]
        block = _block_from_hours(hours_in)
        if block:
            block["label"] = label
            blocks.append(block)

    day_part("morning", MORNING)
    day_part("afternoon", AFTERNOON)
    day_part("evening", EVENING)

    # Tomorrow — use daily aggregates.
    daily = data["daily"]
    try:
        tom_idx = daily["time"].index(tomorrow.isoformat())
    except ValueError:
        tom_idx = None

    if tom_idx is not None:
        tom_code = int(daily["weather_code"][tom_idx])
        tom_wind = float(daily["wind_speed_10m_max"][tom_idx])
        blocks.append({
            "label": "tomorrow",
            "category": _classify(tom_code, tom_wind),
            "temp_min": float(daily["temperature_2m_min"][tom_idx]),
            "temp_max": float(daily["temperature_2m_max"][tom_idx]),
            "precipitation_mm": float(daily["precipitation_sum"][tom_idx]),
        })

    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "location": {"lat": lat, "lon": lon},
        "blocks": blocks,
    }


def format_report(report):
    lines = [f"Weather report @ {report['generated_at']}"]
    for b in report["blocks"]:
        line = (f"  {b['label']:<10} {b['category']:<14} "
                f"{b['temp_min']:.0f}°C – {b['temp_max']:.0f}°C")
        if "precipitation_mm" in b:
            line += f"  precip {b['precipitation_mm']:.1f} mm"
        lines.append(line)
    return "\n".join(lines)


if __name__ == "__main__":
    try:
        report = build_weather_report(51.5428743,-0.1289942,"auto")
    except Exception as e:  # noqa: BLE001
        print(f"Failed to build weather report: {e}", file=sys.stderr)
        sys.exit(1)
    print(format_report(report))
