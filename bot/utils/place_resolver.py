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
        self._refined_tz = None   # уточнённая IANA-зона

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
        # ... (код без изменений, как в предыдущей версии)
        # Оставляем тот же код, он работает.

    def _get_timezone_from_coords(self, lat: float, lng: float) -> str:
        tz_name = self._tf.timezone_at(lat=lat, lng=lng)
        if tz_name and tz_name in zoneinfo.available_timezones():
            return tz_name
        logger.warning(f"Не удалось определить IANA-таймзону для ({lat}, {lng})")
        return self.DEFAULT_TZ

    def _ask_gemini_for_coords(self, city: str, country: str) -> Optional[Dict]:
        # ... (код без изменений)
        pass

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
            # Проверяем, не вернула ли Gemini "НЕЗНАЮ"
            if "НЕЗНАЮ" in response:
                logger.info("ℹ️ Gemini не смогла определить UTC время. Будем использовать current_tz и запишем в БД 'UNKNOWN'.")
                self._refined_tz = "UNKNOWN"
                return None

            # Пытаемся извлечь JSON
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                if 'utc_datetime' in data:
                    utc_str = data['utc_datetime']
                    utc_dt = datetime.strptime(utc_str, "%Y-%m-%d %H:%M:%S")
                    self._utc_datetime = utc_dt.replace(tzinfo=timezone.utc)

                    # Вычисляем смещение: local_time (с учетом timezone) - utc_time
                    # Так как мы не знаем точную timezone, мы можем вычислить смещение как разницу между local и utc
                    # Но local_time у нас есть как datetime без timezone. Предположим, что local_time - это время в том часовом поясе, который мы ищем.
                    # Мы можем вычислить смещение = local_time - utc_time (в часах)
                    local_dt = dt  # это naive datetime
                    offset_seconds = (local_dt - utc_dt).total_seconds()
                    offset_hours = offset_seconds / 3600
                    logger.info(f"✅ Вычислено смещение: UTC{offset_hours:+g}")

                    # Подбираем IANA-зону по смещению и координатам
                    tz_candidate = self._find_iana_zone_by_offset(lat, lng, utc_dt, offset_hours)
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

    def _find_iana_zone_by_offset(self, lat: float, lng: float, utc_date: datetime, offset_hours: float) -> Optional[str]:
        """
        По координатам и дате находит IANA-зону, смещение которой в указанную дату равно offset_hours.
        Использует timezonefinder для получения списка возможных зон, затем проверяет смещение.
        """
        # Получаем список всех зон, которые покрывают данную точку
        # timezonefinder может вернуть несколько зон, но обычно только одну.
        tz_name = self._tf.timezone_at(lat=lat, lng=lng)
        if not tz_name:
            return None

        # Проверяем смещение для этой зоны на указанную дату
        try:
            tz = zoneinfo.ZoneInfo(tz_name)
            # Создаём local datetime с этой зоной
            local_dt = utc_date.astimezone(tz)
            # Вычисляем фактическое смещение
            actual_offset = local_dt.utcoffset().total_seconds() / 3600
            if abs(actual_offset - offset_hours) < 0.5:  # допуск 0.5 часа
                return tz_name
            else:
                # Если не совпадает, попробуем найти другие зоны с таким же смещением
                # Простой перебор всех зон (можно ограничить)
                for tz_candidate in zoneinfo.available_timezones():
                    try:
                        tz_obj = zoneinfo.ZoneInfo(tz_candidate)
                        # Проверяем, что зона покрывает координаты (приблизительно)
                        # Для простоты проверим по смещению на указанную дату
                        local_dt_candidate = utc_date.astimezone(tz_obj)
                        offset_candidate = local_dt_candidate.utcoffset().total_seconds() / 3600
                        if abs(offset_candidate - offset_hours) < 0.5:
                            # Дополнительно проверим, что зона географически близка
                            # Это сложно, но можно проверить по названию (например, содержит регион)
                            if city.lower() in tz_candidate.lower() or country.lower() in tz_candidate.lower():
                                return tz_candidate
                    except:
                        continue
                logger.warning(f"Не найдена зона с смещением {offset_hours:+g} для {city}, {country}")
                return None
        except Exception as e:
            logger.warning(f"Ошибка проверки смещения для {tz_name}: {e}")
            return None