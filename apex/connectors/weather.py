"""
Weather Connector - OpenWeatherMap Integration

Provides current weather, forecasts, and weather alerts.
Uses OpenWeatherMap API (free tier supports 60 calls/min).

Setup:
    export OPENWEATHERMAP_API_KEY="your-key"
    
    # Or
    from connectors.weather import WeatherConnector
    weather = WeatherConnector(api_key="your-key")
    current = await weather.get_current("London")
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://api.openweathermap.org"


@dataclass
class WeatherData:
    """Weather observation."""
    location: str
    country: str
    temperature: float  # Fahrenheit
    feels_like: float
    humidity: int
    description: str
    wind_speed: float  # mph
    wind_direction: Optional[str] = None
    pressure: int = 0  # hPa
    visibility: Optional[float] = None  # miles
    clouds: int = 0  # percentage
    rain_1h: Optional[float] = None  # mm
    snow_1h: Optional[float] = None  # mm
    sunrise: Optional[str] = None
    sunset: Optional[str] = None
    icon: str = ""
    timestamp: str = ""

    def to_dict(self) -> Dict:
        d = {
            "location": self.location,
            "country": self.country,
            "temperature_f": self.temperature,
            "feels_like_f": self.feels_like,
            "temperature_c": round((self.temperature - 32) * 5 / 9, 1),
            "feels_like_c": round((self.feels_like - 32) * 5 / 9, 1),
            "humidity": f"{self.humidity}%",
            "description": self.description,
            "wind_speed_mph": self.wind_speed,
            "pressure_hpa": self.pressure,
            "clouds": f"{self.clouds}%",
        }
        if self.visibility is not None:
            d["visibility_miles"] = self.visibility
        if self.rain_1h is not None:
            d["rain_1h_mm"] = self.rain_1h
        if self.snow_1h is not None:
            d["snow_1h_mm"] = self.snow_1h
        if self.sunrise:
            d["sunrise"] = self.sunrise
        if self.sunset:
            d["sunset"] = self.sunset
        if self.timestamp:
            d["observed_at"] = self.timestamp
        return d


@dataclass
class ForecastEntry:
    """Single forecast time slot."""
    datetime_str: str
    temperature: float
    feels_like: float
    humidity: int
    description: str
    wind_speed: float
    rain_chance: int = 0
    rain_mm: float = 0
    snow_mm: float = 0

    def to_dict(self) -> Dict:
        return {
            "datetime": self.datetime_str,
            "temperature_f": self.temperature,
            "temperature_c": round((self.temperature - 32) * 5 / 9, 1),
            "feels_like_f": self.feels_like,
            "humidity": f"{self.humidity}%",
            "description": self.description,
            "wind_speed_mph": self.wind_speed,
            "rain_chance": f"{self.rain_chance}%",
            "rain_mm": self.rain_mm,
            "snow_mm": self.snow_mm,
        }


def _wind_direction(deg: int) -> str:
    """Convert wind degrees to compass direction."""
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    idx = round(deg / 22.5) % 16
    return dirs[idx]


class WeatherConnector:
    """Weather data via OpenWeatherMap API."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("OPENWEATHERMAP_API_KEY", "")
        self.connected = bool(self.api_key)

    async def _get(self, endpoint: str, params: Dict[str, Any]) -> Dict:
        """Make API request."""
        import httpx

        params["appid"] = self.api_key
        params.setdefault("units", "imperial")  # Fahrenheit, mph

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{BASE_URL}{endpoint}", params=params)
            resp.raise_for_status()
            return resp.json()

    async def get_current(self, location: str) -> WeatherData:
        """Get current weather for a location (city name, zip, or coordinates).
        
        Args:
            location: City name (e.g. "London"), "city,country" (e.g. "Paris,FR"),
                      zip code (e.g. "10001"), or "lat,lon" (e.g. "40.7,-74.0")
        """
        params = self._parse_location(location)
        data = await self._get("/data/2.5/weather", params)
        return self._parse_current(data)

    async def get_forecast(self, location: str, days: int = 3) -> Dict:
        """Get 5-day / 3-hour forecast.
        
        Args:
            location: City name, zip code, or coordinates
            days: Number of days to return (1-5, default 3)
        """
        params = self._parse_location(location)
        data = await self._get("/data/2.5/forecast", params)

        # Parse and group by day
        entries = []
        for item in data.get("list", []):
            entries.append(ForecastEntry(
                datetime_str=item["dt_txt"],
                temperature=item["main"]["temp"],
                feels_like=item["main"]["feels_like"],
                humidity=item["main"]["humidity"],
                description=item["weather"][0]["description"],
                wind_speed=item["wind"]["speed"],
                rain_chance=round(item.get("pop", 0) * 100),
                rain_mm=item.get("rain", {}).get("3h", 0),
                snow_mm=item.get("snow", {}).get("3h", 0),
            ))

        # Limit to requested days (8 entries per day in 3-hour slots)
        max_entries = days * 8
        entries = entries[:max_entries]

        # Group by date
        by_date = {}
        for e in entries:
            date = e.datetime_str.split(" ")[0]
            if date not in by_date:
                by_date[date] = []
            by_date[date].append(e.to_dict())

        city = data.get("city", {})
        return {
            "location": city.get("name", location),
            "country": city.get("country", ""),
            "days": days,
            "forecast": by_date,
        }

    async def get_air_quality(self, location: str) -> Dict:
        """Get air quality index for a location.
        
        Args:
            location: City name or coordinates
        """
        # Air quality API requires lat/lon, so first geocode
        coords = await self._geocode(location)
        if not coords:
            raise ValueError(f"Could not find location: {location}")

        data = await self._get("/data/2.5/air_pollution", {
            "lat": coords["lat"],
            "lon": coords["lon"],
        })

        aqi_labels = {1: "Good", 2: "Fair", 3: "Moderate", 4: "Poor", 5: "Very Poor"}
        result = data.get("list", [{}])[0]
        aqi = result.get("main", {}).get("aqi", 0)
        components = result.get("components", {})

        return {
            "location": location,
            "aqi": aqi,
            "aqi_label": aqi_labels.get(aqi, "Unknown"),
            "components": {
                "co": f"{components.get('co', 0)} μg/m³",
                "no2": f"{components.get('no2', 0)} μg/m³",
                "o3": f"{components.get('o3', 0)} μg/m³",
                "pm2_5": f"{components.get('pm2_5', 0)} μg/m³",
                "pm10": f"{components.get('pm10', 0)} μg/m³",
                "so2": f"{components.get('so2', 0)} μg/m³",
            },
        }

    async def search_cities(self, query: str, limit: int = 5) -> List[Dict]:
        """Search for cities by name.
        
        Args:
            query: City name to search
            limit: Max results (default 5)
        """
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{BASE_URL}/geo/1.0/direct", params={
                "q": query,
                "limit": limit,
                "appid": self.api_key,
            })
            resp.raise_for_status()
            results = resp.json()

        return [{
            "name": r.get("name", ""),
            "country": r.get("country", ""),
            "state": r.get("state", ""),
            "lat": r.get("lat"),
            "lon": r.get("lon"),
        } for r in results]

    # ── Internal helpers ──

    def _parse_location(self, location: str) -> Dict[str, str]:
        """Parse location string into API query params."""
        loc = location.strip()
        # Check if coordinates (lat,lon)
        parts = loc.split(",")
        if len(parts) == 2:
            try:
                lat, lon = float(parts[0].strip()), float(parts[1].strip())
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    return {"lat": str(lat), "lon": str(lon)}
            except ValueError:
                pass
        # Check if zip code (US)
        if loc.isdigit() and len(loc) == 5:
            return {"zip": loc}
        # City name
        return {"q": loc}

    def _parse_current(self, data: Dict) -> WeatherData:
        """Parse API response into WeatherData."""
        main = data.get("main", {})
        wind = data.get("wind", {})
        weather = data.get("weather", [{}])[0]
        sys_data = data.get("sys", {})

        sunrise = sunset = None
        if sys_data.get("sunrise"):
            sunrise = datetime.fromtimestamp(sys_data["sunrise"]).strftime("%I:%M %p")
        if sys_data.get("sunset"):
            sunset = datetime.fromtimestamp(sys_data["sunset"]).strftime("%I:%M %p")

        visibility = None
        if data.get("visibility"):
            visibility = round(data["visibility"] / 1609.34, 1)  # meters to miles

        return WeatherData(
            location=data.get("name", "Unknown"),
            country=sys_data.get("country", ""),
            temperature=main.get("temp", 0),
            feels_like=main.get("feels_like", 0),
            humidity=main.get("humidity", 0),
            description=weather.get("description", ""),
            wind_speed=wind.get("speed", 0),
            wind_direction=_wind_direction(wind.get("deg", 0)) if wind.get("deg") is not None else None,
            pressure=main.get("pressure", 0),
            visibility=visibility,
            clouds=data.get("clouds", {}).get("all", 0),
            rain_1h=data.get("rain", {}).get("1h"),
            snow_1h=data.get("snow", {}).get("1h"),
            sunrise=sunrise,
            sunset=sunset,
            icon=weather.get("icon", ""),
            timestamp=datetime.fromtimestamp(data.get("dt", 0)).strftime("%Y-%m-%d %H:%M:%S"),
        )

    async def _geocode(self, location: str) -> Optional[Dict]:
        """Convert location name to coordinates."""
        results = await self.search_cities(location, limit=1)
        if results:
            return {"lat": results[0]["lat"], "lon": results[0]["lon"]}
        return None
