import logging
import re
import json
import time
import logging
import time
import zoneinfo
from typing import Tuple, Optional, Dict, Any

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from timezonefinder import TimezoneFinder
import requests

logger = logging.getLogger(__name__)


class PlaceResolver:
    """
    Определяет координаты и IANA-часовой пояс по названию места (город, страна).
    Использует геокодинг и timezonefinder. Без дополнительных уточнений.
    """
    DEFAULT_LAT = 55.7558
    DEFAULT_LNG = 37.6173
    DEFAULT_TZ = "Europe/Moscow"

    def __init__(self):
        self._cache = {}
        self._tf = TimezoneFinder()

    def resolve(self, city: str, country: str) -> Tuple[float, float, str]:
        key = (city.strip().lower(), country.strip().lower())
        if key in self._cache:
            lat, lng, tz = self._cache[key]
            logger.info(f"✅ Используем кешированные координаты для {city}, {country}: ({lat}, {lng}, {tz})")
            return lat, lng, tz

        logger.info(f"🌐 Выполняем геокодинг для {city}, {country}")
        lat, lng, tz = self._geocode(city, country)

        self._cache[key] = (lat, lng, tz)
        logger.info(f"✅ Сохранено в кеш: {city}, {country} → ({lat}, {lng}, {tz})")
        return lat, lng, tz

    def _geocode(self, city: str, country: str) -> Tuple[float, float, str]:
        # 1. Nominatim
        try:
            time.sleep(1)
            geolocator = Nominatim(user_agent="my_astrolog_bot")
            query = f"{city}, {country}" if country else city
            location = geolocator.geocode(query, timeout=10)
            if location:
                lat, lng = location.latitude, location.longitude
                tz = self._get_timezone_from_coords(lat, lng)
                logger.info(f"✅ Найдено через Nominatim: {location.address} ({lat}, {lng}, {tz})")
                return lat, lng, tz
        except Exception as e:
            logger.warning(f"⚠️ Ошибка Nominatim: {e}")

        # 2. Open-Meteo
        try:
            time.sleep(1)
            url = "https://geocoding-api.open-meteo.com/v1/search"
            params = {"name": city, "count": 1, "format": "json", "language": "ru"}
            if country:
                params["countryCode"] = country.upper()
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results")
                if results:
                    loc = results[0]
                    lat, lng = loc["latitude"], loc["longitude"]
                    tz = self._get_timezone_from_coords(lat, lng)
                    logger.info(f"✅ Найдено через Open-Meteo: {loc.get('name', city)}, {loc.get('country', '')} ({lat}, {lng}, {tz})")
                    return lat, lng, tz
        except Exception as e:
            logger.warning(f"⚠️ Ошибка Open-Meteo: {e}")

        # Fallback
        logger.warning(f"❌ Не удалось определить координаты для {city}, {country}. Используем Москву.")
        return self.DEFAULT_LAT, self.DEFAULT_LNG, self.DEFAULT_TZ

    def _get_timezone_from_coords(self, lat: float, lng: float) -> str:
        tz_name = self._tf.timezone_at(lat=lat, lng=lng)
        if tz_name and tz_name in zoneinfo.available_timezones():
            return tz_name
        logger.warning(f"Не удалось определить IANA-таймзону для ({lat}, {lng})")
        return self.DEFAULT_TZ