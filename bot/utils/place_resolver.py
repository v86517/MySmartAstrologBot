import logging
import re
import json
import time
import zoneinfo
from datetime import datetime, timezone, timedelta
from typing import Tuple, Optional, Dict, Any, List

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
        self._cache = {}
        self._tf = TimezoneFinder()
        self.gemini = gemini_service
        self._utc_datetime = None
        self._refined_tz = None

    def resolve(self, city: str, country: str,
                birth_date: str, birth_time: str) -> Tuple[float, float, str]:
        key = (city.strip().lower(), country.strip().lower())
        if key in self._cache:
            lat, lng, tz = self._cache[key]
            logger.info(f"✅ Используем кешированные координаты для {city}, {country}: ({lat}, {lng}, {tz})")
            return lat, lng, tz

        logger.info(f"🌐 Выполняем геокодинг для {city}, {country}")
        lat, lng, tz = self._geocode(city, country)

        # Уточняем таймзону через Gemini
        refined_tz = self._refine_timezone(city, country, lat, lng, birth_date, birth_time, tz)
        if refined_tz:
            tz = refined_tz
            self._refined_tz = refined_tz

        self._cache[key] = (lat, lng, tz)
        logger.info(f"✅ Сохранено в кеш: {city}, {country} → ({lat}, {lng}, {tz})")
        return lat, lng, tz

    def get_utc_datetime(self) -> Optional[datetime]:
        return self._utc_datetime

    def get_refined_timezone(self) -> Optional[str]:
        return self._refined_tz

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
        """
        Запрашивает у Gemini UTC время для указанной даты/времени и места.
        Если Gemini возвращает UTC время, вычисляем смещение и подбираем IANA-зону.
        Если Gemini возвращает "НЕЗНАЮ", используем current_tz, но в БД запишем "UNKNOWN".
        """
        if not self.gemini:
            return None

        try:
            dt = datetime.strptime(f"{birth_date} {birth_time}", "%d.%m.%Y %H:%M")
        except ValueError:
            logger.warning(f"Неверный формат даты/времени: {birth_date} {birth_time}")
            return None

        prompt = (
            f"Сколько было время по UTC для местной даты {dt.strftime('%Y-%m-%d')} и времени {dt.strftime('%H:%M')} "
            f"в {city}, {country} (координаты {lat}, {lng}) с учётом исторических переходов на летнее время в этом регионе. "
            f"Верни ответ строго в формате JSON: {{\"utc_datetime\": \"YYYY-MM-DD HH:MM:SS\"}}. "
            f"Если точно определить невозможно, верни \"НЕЗНАЮ\"."
        )
        try:
            response = self.gemini.send_raw_prompt(prompt)
            logger.info(f"📥 Ответ Gemini для уточнения UTC: {response[:200]}...")
            if "НЕЗНАЮ" in response:
                logger.info("ℹ️ Gemini не смогла определить UTC время. Будем использовать current_tz и запишем в БД 'UNKNOWN'.")
                self._refined_tz = "UNKNOWN"
                return None

            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                if 'utc_datetime' in data:
                    utc_str = data['utc_datetime']
                    utc_dt = datetime.strptime(utc_str, "%Y-%m-%d %H:%M:%S")
                    self._utc_datetime = utc_dt.replace(tzinfo=timezone.utc)

                    # Вычисляем смещение: local_time - utc_time (в часах)
                    local_dt = dt
                    offset_seconds = (local_dt - utc_dt).total_seconds()
                    offset_hours = offset_seconds / 3600
                    logger.info(f"✅ Вычислено смещение: UTC{offset_hours:+g}")

                    # Подбираем IANA-зону по смещению и координатам (передаём city, country)
                    tz_candidate = self._find_iana_zone_by_offset(lat, lng, utc_dt, offset_hours, city, country)
                    if tz_candidate:
                        logger.info(f"✅ Подобрана IANA-зона: {tz_candidate} (смещение {offset_hours:+g})")
                        self._refined_tz = tz_candidate
                        return tz_candidate
                    else:
                        logger.warning(f"⚠️ Не удалось подобрать IANA-зону для смещения {offset_hours:+g}. Используем current_tz.")
                        self._refined_tz = "UNKNOWN"
                        return None
            else:
                logger.warning(f"Не удалось извлечь JSON из ответа Gemini: {response[:200]}...")
                self._refined_tz = "UNKNOWN"
                return None
        except Exception as e:
            logger.warning(f"⚠️ Ошибка уточнения UTC: {e}")
            self._refined_tz = "UNKNOWN"
            return None

        return None

    def _find_iana_zone_by_offset(self, lat: float, lng: float, utc_date: datetime,
                                  offset_hours: float, city: str = "", country: str = "") -> Optional[str]:
        """
        По координатам и дате находит IANA-зону, смещение которой в указанную дату равно offset_hours.
        """
        # Сначала пробуем основную зону по координатам
        tz_name = self._tf.timezone_at(lat=lat, lng=lng)
        if tz_name:
            try:
                tz = zoneinfo.ZoneInfo(tz_name)
                local_dt = utc_date.astimezone(tz)
                actual_offset = local_dt.utcoffset().total_seconds() / 3600
                if abs(actual_offset - offset_hours) < 0.5:
                    return tz_name
            except Exception as e:
                logger.warning(f"Ошибка проверки смещения для {tz_name}: {e}")

        # Если не совпало, ищем по всем зонам с фильтрацией по названиям
        candidates = []
        for tz_candidate in zoneinfo.available_timezones():
            try:
                tz_obj = zoneinfo.ZoneInfo(tz_candidate)
                local_dt_candidate = utc_date.astimezone(tz_obj)
                offset_candidate = local_dt_candidate.utcoffset().total_seconds() / 3600
                if abs(offset_candidate - offset_hours) < 0.5:
                    # Проверяем, не содержит ли зона название города или страны (приблизительно)
                    if city and city.lower() in tz_candidate.lower():
                        return tz_candidate
                    if country and country.lower() in tz_candidate.lower():
                        return tz_candidate
                    candidates.append(tz_candidate)
            except:
                continue

        if candidates:
            # Если несколько зон, вернём первую (можно улучшить)
            return candidates[0]

        return None