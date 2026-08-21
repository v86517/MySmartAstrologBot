import logging
import re
import json
import time
import zoneinfo
from datetime import datetime, timezone
from typing import Tuple, Optional, Dict, Any
from pathlib import Path

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from timezonefinder import TimezoneFinder
import requests

from bot.services.gemini import GeminiService

logger = logging.getLogger(__name__)


class PlaceResolver:
    """
    Определяет координаты и IANA-часовой пояс по названию места (город, страна).
    Кеширует результат для повторных вызовов.
    """

    DEFAULT_LAT = 55.7558
    DEFAULT_LNG = 37.6173
    DEFAULT_TZ = "Europe/Moscow"

    def __init__(self, gemini_service: Optional[GeminiService] = None):
        self._cache = {}  # кеш по (city, country) → (lat, lng, tz)
        self._tf = TimezoneFinder()
        self.gemini = gemini_service

    def resolve(self, city: str, country: str,
                birth_date: str, birth_time: str) -> Tuple[float, float, str]:
        """
        Возвращает (lat, lng, IANA_tz) для указанного места.
        Использует кеш, чтобы не повторять геокодинг.
        """
        key = (city.strip().lower(), country.strip().lower())
        if key in self._cache:
            lat, lng, tz = self._cache[key]
            logger.info(f"✅ Используем кешированные координаты для {city}, {country}: ({lat}, {lng}, {tz})")
            return lat, lng, tz

        logger.info(f"🌐 Выполняем геокодинг для {city}, {country}")
        lat, lng, tz = self._geocode(city, country)

        # Уточняем таймзону через Gemini с учётом даты рождения
        refined_tz = self._refine_timezone(city, country, lat, lng, birth_date, birth_time, tz)
        if refined_tz:
            tz = refined_tz

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

        # 3. Gemini (если доступен)
        if self.gemini:
            try:
                result = self._ask_gemini_for_coords(city, country)
                if result and 'lat' in result and 'lng' in result and 'timezone' in result:
                    lat, lng, tz = result['lat'], result['lng'], result['timezone']
                    logger.info(f"✅ Найдено через Gemini: {city}, {country} ({lat}, {lng}, {tz})")
                    return lat, lng, tz
            except Exception as e:
                logger.warning(f"⚠️ Ошибка Gemini: {e}")

        # Fallback
        logger.warning(f"❌ Не удалось определить координаты для {city}, {country}. Используем Москву.")
        return self.DEFAULT_LAT, self.DEFAULT_LNG, self.DEFAULT_TZ

    def _get_timezone_from_coords(self, lat: float, lng: float) -> str:
        tz_name = self._tf.timezone_at(lat=lat, lng=lng)
        if tz_name and tz_name in zoneinfo.available_timezones():
            return tz_name
        logger.warning(f"Не удалось определить IANA-таймзону для ({lat}, {lng})")
        return self.DEFAULT_TZ

    def _ask_gemini_for_coords(self, city: str, country: str) -> Optional[Dict]:
        if not self.gemini:
            return None
        prompt = (
            f"Определи географические координаты (широту и долготу) и часовой пояс IANA для места: {city}, {country}. "
            f"Если точное место не найдено, найди координаты столицы страны {country}. "
            "Верни ответ строго в формате JSON: {\"lat\": число, \"lng\": число, \"timezone\": \"строка IANA\"}. "
            "Если данные не найдены, верни {\"error\": \"not found\"}."
        )
        try:
            response = self.gemini.send_raw_prompt(prompt)
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                if 'lat' in data and 'lng' in data and 'timezone' in data:
                    if data['timezone'] in zoneinfo.available_timezones():
                        return data
            logger.warning(f"Не удалось распарсить ответ Gemini: {response[:200]}...")
        except Exception as e:
            logger.error(f"Ошибка запроса к Gemini: {e}")
        return None

    def _refine_timezone(self, city: str, country: str, lat: float, lng: float,
                         birth_date: str, birth_time: str, current_tz: str) -> Optional[str]:
        """Уточняет таймзону через Gemini с учётом исторических переходов."""
        if not self.gemini:
            return None

        try:
            dt = datetime.strptime(f"{birth_date} {birth_time}", "%d.%m.%Y %H:%M")
        except ValueError:
            logger.warning(f"Неверный формат даты/времени: {birth_date} {birth_time}")
            return None

        prompt = (
            f"Для места {city}, {country} с координатами {lat}, {lng} определи точный IANA-часовой пояс, "
            f"который действовал на местную дату {dt.strftime('%Y-%m-%d')} и время {dt.strftime('%H:%M')}. "
            f"Учти все исторические переходы на летнее время в этом регионе. "
            f"Верни только название IANA (например, 'Europe/Moscow') без дополнительного текста. "
            f"Если точно определить невозможно, верни '{current_tz}'."
        )
        try:
            response = self.gemini.send_raw_prompt(prompt)
            tz_candidate = response.strip().strip('"').strip("'")
            if tz_candidate in zoneinfo.available_timezones():
                logger.info(f"✅ Таймзона уточнена через Gemini: {tz_candidate} (было: {current_tz})")
                return tz_candidate
        except Exception as e:
            logger.warning(f"⚠️ Ошибка уточнения таймзоны: {e}")
        return None


    def utc_from_local(self, local_date: str, local_time: str, tz_str: str) -> datetime:
        """
        Преобразует локальную дату и время в UTC datetime с использованием IANA.
        """
        try:
            dt = datetime.strptime(f"{local_date} {local_time}", "%d.%m.%Y %H:%M")
        except ValueError:
            logger.warning(f"Неверный формат даты/времени: {local_date} {local_time}")
            return None

        tz = zoneinfo.ZoneInfo(tz_str)
        local_dt = dt.replace(tzinfo=tz)
        return local_dt.astimezone(timezone.utc)