#bot/calculators/astrology_calculator.py
import os
import requests
import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import pytz
from geopy.exc import GeocoderRateLimited, GeocoderTimedOut, GeocoderUnavailable

from kerykeion import AstrologicalSubject
from timezonefinder import TimezoneFinder
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from bot.db import _get_user_birth_timezone_sync, _set_user_birth_timezone_sync


logger = logging.getLogger(__name__)


class AstrologyCalculator:
    """
    Класс для расчёта астрологических параметров с помощью kerykeion.
    Все недостающие данные заменяются значениями по умолчанию.
    """

    DEFAULT_LAT = 55.7558
    DEFAULT_LNG = 37.6173
    DEFAULT_TZ = "Europe/Moscow"

    MAJOR_ASPECTS = {'conjunction', 'opposition', 'trine', 'square', 'sextile'}
    MAX_ORB = 5.0

    gemini_service = None

    def __init__(self, user_data: Dict[str, Any], telegram_id: Optional[int] = None):
        self.user_data = user_data
        self.name = user_data.get('name', 'Человек')
        self.gender = user_data.get('gender', 'M')
        self.birth_date_str = user_data.get('birth_date')
        self.birth_time_str = user_data.get('birth_time')
        self.birth_place = user_data.get('birth_place', '')
        self.extra_info = user_data.get('extra_info', '')

        self._coords = None
        self._chart_data = None
        self._timezone = None
        self._tf = TimezoneFinder()
        self._progression_data = None
        #self._cached_coords = None
        #self._cached_timezone = None
        self._angles = None  # FIXED: кеш углов
        self.telegram_id = telegram_id
        self._calculated_coords = None

    def _parse_birth_datetime(self) -> Tuple[int, int, int, int, int]:
        date_str = self.birth_date_str or "01.01.2000"
        time_str = self.birth_time_str or "12:00"
        try:
            dt = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")
            return dt.year, dt.month, dt.day, dt.hour, dt.minute
        except ValueError:
            logger.warning(f"Неверный формат даты/времени: {date_str} {time_str}. Используем 01.01.2000 12:00")
            return 2000, 1, 1, 12, 0

    def _parse_birth_place(self) -> Tuple[str, str]:
        place = self.birth_place.strip()
        if not place:
            return "Москва", "RU"
        parts = [p.strip() for p in place.split(',') if p.strip()]
        city = parts[0] if parts else "Москва"
        country = parts[1] if len(parts) > 1 else "RU"
        return city, country

    def _get_coordinates_and_timezone(self) -> Tuple[float, float, str]:
        """
        Определяет координаты и часовой пояс места рождения.
        Проверяет наличие координат в self.user_data (переданы из хендлера).
        Если их нет — выполняет геокодинг.
        Координаты НЕ СОХРАНЯЮТСЯ в БД внутри этого метода.
        """
        # 1. Проверяем наличие координат в user_data
        lat = self.user_data.get('birth_lat')
        lng = self.user_data.get('birth_lng')
        tz = self.user_data.get('birth_timezone')
        if lat is not None and lng is not None and tz:
            logger.info(f"✅ Используем координаты из user_data: ({lat}, {lng}, {tz})")
            return lat, lng, tz

        # 2. Если координат нет — выполняем геокодинг
        city, country = self._parse_birth_place()
        logger.info(f"🌐 Выполняем геокодинг для {city}, {country}")

        lat, lng, tz = self._perform_geocoding(city, country)

        # 3. Уточняем часовой пояс через Gemini (если доступен)
        try:
            refined_tz = self._refine_timezone(tz, city, country, lat, lng)
            if refined_tz:
                logger.info(f"✅ Таймзона уточнена через Gemini: {refined_tz} (было: {tz})")
                tz = refined_tz
        except Exception as e:
            logger.warning(f"⚠️ Ошибка уточнения таймзоны: {e}")

        # 4. Сохраняем координаты в атрибуты для последующего использования в хендлере
        self._calculated_coords = (lat, lng, tz)
        logger.info(f"🌐 Координаты: {lat}, {lng}, часовой пояс: {tz}")

        return lat, lng, tz

    def _perform_geocoding(self, city: str, country: str) -> Tuple[float, float, str]:
        # 1. Nominatim
        try:
            time.sleep(1)
            coords = self._get_coordinates_geocoder(city, country)
            if coords:
                lat, lng = coords['lat'], coords['lng']
                tz_str = self._get_timezone_from_coords(lat, lng)
                if tz_str:
                    logger.info(f"✅ Найдено через геокодер: {city}, {country} ({lat}, {lng}, {tz_str})")
                    return lat, lng, tz_str
        except (GeocoderRateLimited, GeocoderTimedOut, GeocoderUnavailable) as e:
            logger.warning(f"⚠️ Геокодер недоступен: {e}")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка Nominatim: {e}")

        # 2. Open-Meteo API
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
                    tz_str = self._get_timezone_from_coords(lat, lng)
                    if tz_str:
                        logger.info(
                            f"✅ Найдено через Open-Meteo: {loc.get('name', city)}, {loc.get('country', '')} ({lat}, {lng}, {tz_str})")
                        return lat, lng, tz_str
        except Exception as e:
            logger.warning(f"⚠️ Ошибка Open-Meteo: {e}")

        # 3. Gemini (если доступен)
        if self.__class__.gemini_service:
            try:
                result = self._ask_gemini_for_coords(city, country)
                if result and 'lat' in result and 'lng' in result and 'timezone' in result:
                    lat, lng, tz_str = result['lat'], result['lng'], result['timezone']
                    logger.info(f"✅ Найдено через нейросеть: {city}, {country} ({lat}, {lng}, {tz_str})")
                    return lat, lng, tz_str
            except Exception as e:
                logger.warning(f"⚠️ Ошибка Gemini: {e}")

        # 4. Fallback — Москва
        logger.warning(f"❌ Не удалось определить координаты для {city}, {country}. Используем Москву.")
        return self.DEFAULT_LAT, self.DEFAULT_LNG, self.DEFAULT_TZ

    def _get_coordinates_geocoder(self, city: str, country: str = None) -> Optional[Dict[str, float]]:
        try:
            geolocator = Nominatim(user_agent="my_astrolog_bot")
            query = f"{city}, {country}" if country else city
            location = geolocator.geocode(query, timeout=10)
            if location:
                logger.info(f"✅ Найдено через Nominatim: {location.address} ({location.latitude}, {location.longitude})")
                return {"lat": location.latitude, "lng": location.longitude}
            else:
                logger.warning(f"❌ Nominatim не нашёл '{query}'")
        except (GeocoderTimedOut, GeocoderUnavailable) as e:
            logger.warning(f"⚠️ Ошибка Nominatim: {e}. Пробуем Open-Meteo.")

        url = "https://geocoding-api.open-meteo.com/v1/search"
        params = {"name": city, "count": 1, "format": "json", "language": "ru"}
        if country:
            params["countryCode"] = country.upper()
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results")
            if results:
                loc = results[0]
                lat, lng = loc["latitude"], loc["longitude"]
                logger.info(f"✅ Найдено через Open-Meteo: {loc.get('name', city)}, {loc.get('country', '')} ({lat}, {lng})")
                return {"lat": lat, "lng": lng}
            else:
                logger.warning(f"❌ Open-Meteo не нашёл '{city}'")
        except Exception as e:
            logger.error(f"⚠️ Ошибка Open-Meteo: {e}")

        return None

    def _get_capital_coords(self, country: str) -> Optional[Dict[str, float]]:
        try:
            geolocator = Nominatim(user_agent="my_astrolog_bot")
            query = f"capital of {country}"
            location = geolocator.geocode(query, timeout=10)
            if location:
                return {"lat": location.latitude, "lng": location.longitude}
            else:
                logger.warning(f"❌ Не найдена столица для {country}")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при поиске столицы: {e}")
        return None

    def _get_timezone_from_coords(self, lat: float, lng: float) -> Optional[str]:
        try:
            tz_name = self._tf.timezone_at(lat=lat, lng=lng)
            if tz_name:
                return tz_name
            else:
                logger.warning(f"Не удалось определить часовой пояс для ({lat}, {lng})")
                return None
        except Exception as e:
            logger.error(f"Ошибка определения часового пояса: {e}")
            return None

    def _ask_gemini_for_coords(self, city: str, country: str) -> Optional[Dict]:
        if not self.__class__.gemini_service:
            return None

        prompt = (
            f"Определи географические координаты (широту и долготу) и часовой пояс для места: {city}, {country}. "
            f"Если точное место не найдено, найди координаты столицы страны {country}. "
            "Верни ответ строго в формате JSON: {\"lat\": число, \"lng\": число, \"timezone\": \"строка\"}. "
            "Если данные не найдены, верни {\"error\": \"not found\"}."
        )

        try:
            response = self.__class__.gemini_service.send_raw_prompt(prompt)
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                data = json.loads(json_str)
                if 'lat' in data and 'lng' in data and 'timezone' in data:
                    return data
                else:
                    logger.warning(f"Ответ Gemini не содержит нужных полей: {data}")
            else:
                logger.warning(f"Не удалось найти JSON в ответе Gemini: {response[:200]}...")
        except Exception as e:
            logger.error(f"Ошибка при запросе к Gemini: {e}")

        return None

    def _get_house_for_longitude(self, longitude: float, houses: List[Dict]) -> int:
        """
        Определяет номер дома по долготе планеты на основе куспидов домов.
        houses — список словарей с ключами 'number' и 'degree'.
        """
        if not houses:
            return 0
        sorted_houses = sorted(houses, key=lambda h: h['degree'])
        for i, h in enumerate(sorted_houses):
            next_house = sorted_houses[(i + 1) % len(sorted_houses)]
            start = h['degree']
            end = next_house['degree']
            if end < start:  # переход через 0°
                if longitude >= start or longitude < end:
                    return h['number']
            else:
                if start <= longitude < end:
                    return h['number']
        return 0

    def _calculate_chart(self) -> Dict[str, Any]:
        if self._chart_data is not None:
            logger.info("📊 _chart_data уже закешировано, возвращаем")
            return self._chart_data

        logger.info("🔮 Начинаем расчёт натальной карты...")

        year, month, day, hour, minute = self._parse_birth_datetime()
        city, country = self._parse_birth_place()
        logger.info(f"📅 Дата/время: {day}.{month}.{year} {hour:02d}:{minute:02d}, место: {city}, {country}")

        lat, lng, tz_str = self._get_coordinates_and_timezone()
        self._coords = {"lat": lat, "lng": lng}
        self._timezone = tz_str
        logger.info(f"🌐 Координаты: {lat:.4f}, {lng:.4f}, часовой пояс: {tz_str}")

        subject = AstrologicalSubject(
            name=self.name,
            year=year,
            month=month,
            day=day,
            hour=hour,
            minute=minute,
            lat=lat,
            lng=lng,
            tz_str=tz_str,
        )
        logger.info(f"👤 Субъект создан: {subject.name}")

        model_data = subject.model() if callable(subject.model) else subject.model
        if hasattr(model_data, 'dict'):
            data = model_data.dict()
        elif hasattr(model_data, 'model_dump'):
            data = model_data.model_dump()
        else:
            data = model_data.__dict__
        logger.info(f"📦 Модель получена, количество ключей: {len(data)}")

        # ---- ИЗВЛЕЧЕНИЕ УГЛОВ С ЛОГИРОВАНИЕМ ----
        # Пробуем получить ascendant из data
        asc_raw = data.get('ascendant')
        mc_raw = data.get('midheaven')

        logger.info(f"🔍 asc_raw: {asc_raw} (тип: {type(asc_raw).__name__})")
        logger.info(f"🔍 mc_raw: {mc_raw} (тип: {type(mc_raw).__name__})")

        # Универсальная функция для извлечения числового значения
        def extract_value(obj):
            if obj is None:
                return 0.0
            if isinstance(obj, (int, float)):
                return float(obj)
            if isinstance(obj, dict):
                # может быть {'position': 123.45, ...}
                if 'position' in obj:
                    return float(obj['position'])
                elif 'value' in obj:
                    return float(obj['value'])
                else:
                    # попробуем взять первый числовой ключ
                    for v in obj.values():
                        if isinstance(v, (int, float)):
                            return float(v)
                    return 0.0
            if hasattr(obj, 'position'):
                return float(obj.position)
            if hasattr(obj, 'value'):
                return float(obj.value)
            # если это что-то другое, попробуем преобразовать
            try:
                return float(obj)
            except:
                return 0.0

        asc = extract_value(asc_raw)
        mc = extract_value(mc_raw)

        # Если всё ещё нулевые, попробуем получить из subject напрямую
        if asc == 0.0 and hasattr(subject, 'ascendant'):
            asc_obj = subject.ascendant
            logger.info(f"🔄 Пробуем subject.ascendant: {asc_obj} (тип: {type(asc_obj).__name__})")
            asc = extract_value(asc_obj)

        if mc == 0.0 and hasattr(subject, 'midheaven'):
            mc_obj = subject.midheaven
            logger.info(f"🔄 Пробуем subject.midheaven: {mc_obj} (тип: {type(mc_obj).__name__})")
            mc = extract_value(mc_obj)

        dsc = (asc + 180) % 360
        ic = (mc + 180) % 360
        self._angles = {"ASC": asc, "MC": mc, "DSC": dsc, "IC": ic}
        logger.info(f"📐 Углы: ASC={asc:.2f}, MC={mc:.2f}, DSC={dsc:.2f}, IC={ic:.2f}")

        # ---- Извлечение куспидов домов ----
        house_keys = [
            'first_house', 'second_house', 'third_house', 'fourth_house',
            'fifth_house', 'sixth_house', 'seventh_house', 'eighth_house',
            'ninth_house', 'tenth_house', 'eleventh_house', 'twelfth_house'
        ]
        houses = []
        house_cusps = []
        for i, key in enumerate(house_keys, 1):
            if key in data:
                obj = data[key]
                if isinstance(obj, dict):
                    if 'sign' in obj and 'position' in obj:
                        degree = obj.get('position', 0.0)
                        houses.append({
                            "number": i,
                            "sign": obj.get('sign', 'unknown'),
                            "degree": degree,
                        })
                        house_cusps.append({"number": i, "degree": degree})
                else:
                    if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                        degree = getattr(obj, 'position', 0.0)
                        houses.append({
                            "number": i,
                            "sign": getattr(obj, 'sign', 'unknown'),
                            "degree": degree,
                        })
                        house_cusps.append({"number": i, "degree": degree})
        logger.info(f"🏠 Куспиды домов: {len(houses)} домов, house_cusps: {len(house_cusps)}")

        # ---- Формирование планет с вычислением домов ----
        planet_keys = [
            'sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter', 'saturn',
            'uranus', 'neptune', 'pluto', 'chiron', 'pholus',
            'mean_lilith', 'true_lilith', 'ceres', 'pallas', 'juno', 'vesta',
            'eris', 'sedna', 'haumea', 'makemake', 'ixion', 'orcus', 'quaoar',
            'mean_north_lunar_node', 'true_north_lunar_node',
            'mean_south_lunar_node', 'true_south_lunar_node',
            'regulus', 'spica', 'aldebaran', 'antares', 'sirius', 'fomalhaut',
            'algol', 'betelgeuse', 'canopus', 'procyon', 'arcturus', 'pollux',
            'deneb', 'altair', 'rigel', 'achernar', 'capella', 'vega',
            'alcyone', 'alphecca', 'algorab', 'deneb_algedi', 'alkaid',
            'pars_fortunae', 'pars_spiritus', 'pars_amoris', 'pars_fidei',
            'vertex', 'anti_vertex',
            'hygeia'
        ]

        planets = []
        for key in planet_keys:
            if key in data:
                obj = data[key]
                if isinstance(obj, dict):
                    if 'sign' in obj and 'position' in obj:
                        degree = obj.get('position', 0.0)
                        house = self._get_house_for_longitude(degree, house_cusps)
                        planets.append({
                            "name": key.capitalize(),
                            "sign": obj.get('sign', 'unknown'),
                            "degree": degree,
                            "house": house,
                            "latitude": obj.get('latitude', 0.0),
                            "retrograde": obj.get('retrograde', False),
                            "speed": obj.get('speed', 0.0),
                        })
                else:
                    if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                        degree = getattr(obj, 'position', 0.0)
                        house = self._get_house_for_longitude(degree, house_cusps)
                        planets.append({
                            "name": key.capitalize(),
                            "sign": getattr(obj, 'sign', 'unknown'),
                            "degree": degree,
                            "house": house,
                            "latitude": getattr(obj, 'latitude', 0.0),
                            "retrograde": getattr(obj, 'retrograde', False),
                            "speed": getattr(obj, 'speed', 0.0),
                        })
        logger.info(f"🪐 Планет найдено: {len(planets)}")

        # ---- Аспекты ----
        aspects = []
        try:
            from kerykeion import AspectsFactory
            aspects_data = AspectsFactory.single_chart_aspects(subject)
            if aspects_data and hasattr(aspects_data, 'aspects') and aspects_data.aspects:
                for a in aspects_data.aspects:
                    orb_val = getattr(a, 'orbit', getattr(a, 'orb', getattr(a, 'orbis', 0.0)))
                    aspects.append({
                        "p1": getattr(a, 'p1_name', 'unknown'),
                        "p2": getattr(a, 'p2_name', 'unknown'),
                        "aspect": getattr(a, 'aspect', 'unknown'),
                        "orb": orb_val,
                    })
                logger.info(f"🔮 Аспекты через AspectsFactory: {len(aspects)}")
        except Exception as e:
            logger.warning(f"⚠️ AspectsFactory ошибка: {e}")

        if not aspects:
            try:
                from kerykeion import NatalAspects
                aspects_obj = NatalAspects(subject)
                if hasattr(aspects_obj, 'relevant_aspects'):
                    for a in aspects_obj.relevant_aspects:
                        orb_val = getattr(a, 'orbit', getattr(a, 'orb', getattr(a, 'orbis', 0.0)))
                        aspects.append({
                            "p1": getattr(a, 'p1_name', 'unknown'),
                            "p2": getattr(a, 'p2_name', 'unknown'),
                            "aspect": getattr(a, 'aspect', 'unknown'),
                            "orb": orb_val,
                        })
                    logger.info(f"🔮 Аспекты через NatalAspects: {len(aspects)}")
            except Exception as e:
                logger.warning(f"⚠️ NatalAspects ошибка: {e}")

        if not aspects:
            logger.warning("⚠️ Не удалось получить аспекты (пусто)")

        utc_datetime = None
        if hasattr(subject.model, 'iso_formatted_utc_datetime'):
            utc_datetime = subject.model.iso_formatted_utc_datetime
        elif hasattr(subject, 'iso_formatted_utc_datetime'):
            utc_datetime = subject.iso_formatted_utc_datetime

        result = {
            "name": subject.name,
            "datetime": f"{year}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}",
            "timezone": tz_str,
            "location": {"lat": lat, "lng": lng},
            "planets": planets,
            "houses": houses,
            "aspects": aspects,
            "utc_datetime": utc_datetime,
            "angles": self._angles,
        }

        logger.info(f"✅ Расчёт завершён: {len(planets)} планет, {len(houses)} домов, {len(aspects)} аспектов")
        self._chart_data = result
        return result

    # ---------- НОВЫЕ МЕТОДЫ ДЛЯ ПРОГНОСТИЧЕСКИХ ДАННЫХ ----------

    def _get_progression_subject(self) -> AstrologicalSubject:
        """Создаёт субъект для вторичных прогрессий (день за год)."""
        year, month, day, hour, minute = self._parse_birth_datetime()
        birth_date = datetime(year, month, day, hour, minute)
        now = datetime.now()
        age_in_days = (now - birth_date).days
        prog_date = birth_date + timedelta(days=age_in_days)
        lat, lng, tz_str = self._get_coordinates_and_timezone()
        return AstrologicalSubject(
            name=f"Progressed_{self.name}",
            year=prog_date.year,
            month=prog_date.month,
            day=prog_date.day,
            hour=prog_date.hour,
            minute=prog_date.minute,
            lat=lat,
            lng=lng,
            tz_str=tz_str,
        )

    def _extract_planets_from_subject(self, subject: AstrologicalSubject) -> List[Dict]:
        """Извлекает список планет с градусами и знаками из субъекта."""
        planets = []
        try:
            # Пытаемся получить планеты через атрибут .planets
            if hasattr(subject, 'planets') and subject.planets:
                for p in subject.planets:
                    planets.append({
                        "name": p.name,
                        "sign": p.sign,
                        "degree": p.position,
                        "house": p.house,
                    })
            else:
                # Иначе через модель
                model = subject.model() if callable(subject.model) else subject.model
                data = model.dict() if hasattr(model, 'dict') else model.__dict__
                planet_keys = [
                    'sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter', 'saturn',
                    'uranus', 'neptune', 'pluto', 'chiron', 'mean_lilith', 'true_lilith',
                    'ceres', 'pallas', 'juno', 'vesta', 'eris', 'sedna', 'haumea', 'makemake',
                    'mean_north_lunar_node', 'true_north_lunar_node',
                    'mean_south_lunar_node', 'true_south_lunar_node'
                ]
                for key in planet_keys:
                    if key in data:
                        obj = data[key]
                        if isinstance(obj, dict):
                            if 'sign' in obj and 'position' in obj:
                                planets.append({
                                    "name": key.capitalize(),
                                    "sign": obj.get('sign', 'unknown'),
                                    "degree": obj.get('position', 0.0),
                                    "house": obj.get('house', 0),
                                })
                        else:
                            if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                                planets.append({
                                    "name": key.capitalize(),
                                    "sign": getattr(obj, 'sign', 'unknown'),
                                    "degree": getattr(obj, 'position', 0.0),
                                    "house": getattr(obj, 'house', 0),
                                })
        except Exception as e:
            logger.warning(f"Не удалось извлечь планеты из субъекта: {e}")
        return planets


    def _get_progression_aspects_string(self, lang: str = 'ru') -> str:
        """Возвращает строку с аспектами прогрессивных планет к натальным."""
        try:
            natal_subject = self._get_natal_subject()
            prog_subject = self._get_progression_subject()

            # Извлекаем планеты
            natal_planets = self._extract_planets_from_subject(natal_subject)
            prog_planets = self._extract_planets_from_subject(prog_subject)

            if not natal_planets or not prog_planets:
                return "Не удалось извлечь планеты для расчёта прогрессий."

            # Ручной расчёт аспектов (мажорные, орбис ≤ 5°)
            aspects = self._calculate_aspects_manual(prog_planets, natal_planets)

            if not aspects:
                return "Нет значимых прогрессивных аспектов на текущий период."

            # Форматируем
            lines = []
            for a in aspects:
                lines.append(f"Progressed {a['p1']} → Natal {a['p2']} → {a['aspect']} → {a['orb']:.2f}°")
            return "\n".join(lines)

        except Exception as e:
            logger.error(f"Ошибка при расчёте прогрессивных аспектов: {e}")
            return "Ошибка при расчёте прогрессивных аспектов."

    def _calculate_aspects_manual(self, planets1: List[Dict], planets2: List[Dict]) -> List[Dict]:
        """Ручной расчёт аспектов между двумя списками планет (мажорные)."""
        aspect_types = {
            'conjunction': 8,
            'opposition': 8,
            'trine': 6,
            'square': 6,
            'sextile': 5,
        }
        aspects = []
        for p1 in planets1:
            for p2 in planets2:
                if p1['name'] == p2['name']:
                    continue  # пропускаем аспект планеты к самой себе
                diff = abs(p1['degree'] - p2['degree']) % 360
                if diff > 180:
                    diff = 360 - diff
                for aspect_name, orb in aspect_types.items():
                    if aspect_name == 'conjunction' and diff <= orb:
                        aspects.append({
                            'p1': p1['name'],
                            'p2': p2['name'],
                            'aspect': aspect_name,
                            'orb': diff,
                        })
                        break
                    elif aspect_name == 'opposition' and abs(diff - 180) <= orb:
                        aspects.append({
                            'p1': p1['name'],
                            'p2': p2['name'],
                            'aspect': aspect_name,
                            'orb': abs(diff - 180),
                        })
                        break
                    elif aspect_name == 'trine' and abs(diff - 120) <= orb:
                        aspects.append({
                            'p1': p1['name'],
                            'p2': p2['name'],
                            'aspect': aspect_name,
                            'orb': abs(diff - 120),
                        })
                        break
                    elif aspect_name == 'square' and abs(diff - 90) <= orb:
                        aspects.append({
                            'p1': p1['name'],
                            'p2': p2['name'],
                            'aspect': aspect_name,
                            'orb': abs(diff - 90),
                        })
                        break
                    elif aspect_name == 'sextile' and abs(diff - 60) <= orb:
                        aspects.append({
                            'p1': p1['name'],
                            'p2': p2['name'],
                            'aspect': aspect_name,
                            'orb': abs(diff - 60),
                        })
                        break
        return aspects

    def _get_health_indicators_string(self, lang: str = 'ru') -> str:
        """Анализирует 6-й и 8-й дома, аспекты к Гигиее, сигнификаторы здоровья."""
        chart = self._calculate_chart()
        houses = chart.get('houses', [])
        planets = chart.get('planets', [])
        aspects = chart.get('aspects', [])

        indicators = []

        # 1. Анализ 6-го дома (здоровье, режим)
        if len(houses) >= 6:
            house6 = houses[5]
            sign6 = house6.get('sign', 'неизвестный')
            planets_in_6 = [p for p in planets if p.get('house') == 6]
            planets6_names = ', '.join([p['name'] for p in planets_in_6]) if planets_in_6 else 'нет'
            indicators.append(f"6-й дом (здоровье) в знаке {sign6}: планеты – {planets6_names}")

        # 2. Анализ 8-го дома (кризисы, трансформация)
        if len(houses) >= 8:
            house8 = houses[7]
            sign8 = house8.get('sign', 'неизвестный')
            planets_in_8 = [p for p in planets if p.get('house') == 8]
            planets8_names = ', '.join([p['name'] for p in planets_in_8]) if planets_in_8 else 'нет'
            indicators.append(f"8-й дом (кризисы) в знаке {sign8}: планеты – {planets8_names}")

        # 3. Астероид Гигиея (здоровье)
        hygeia = next((p for p in planets if p.get('name').lower() == 'hygeia'), None)
        if hygeia:
            hygeia_sign = hygeia.get('sign', 'неизвестный')
            hygeia_house = hygeia.get('house', 'неизвестный')
            indicators.append(f"Гигиея (астероид здоровья) в {hygeia_sign} в {hygeia_house} доме")
            # Аспекты к Гигиее (мажорные)
            hygeia_aspects = []
            for a in aspects:
                p1 = a.get('p1', '').lower()
                p2 = a.get('p2', '').lower()
                if 'hygeia' in (p1, p2):
                    aspect_name = a.get('aspect', '')
                    orb = a.get('orb', 0.0)
                    if aspect_name.lower() in self.MAJOR_ASPECTS and orb <= self.MAX_ORB:
                        other = p2 if p1 == 'hygeia' else p1
                        hygeia_aspects.append(f"{other} {aspect_name} (орбис: {orb:.2f}°)")
            if hygeia_aspects:
                indicators.append("Аспекты Гигиеи к планетам: " + ", ".join(hygeia_aspects))
            else:
                indicators.append("Нет значимых аспектов к Гигиее.")
        else:
            indicators.append("Астероид Гигиея не найден в карте (возможно, не поддерживается версией kerykeion).")

        # 4. Сигнификаторы здоровья: Луна, Сатурн, Хирон
        moon = next((p for p in planets if p.get('name').lower() == 'moon'), None)
        saturn = next((p for p in planets if p.get('name').lower() == 'saturn'), None)
        chiron = next((p for p in planets if p.get('name').lower() == 'chiron'), None)

        if moon:
            indicators.append(
                f"Луна (эмоции, циклы) в {moon.get('sign', 'неизвестно')} доме {moon.get('house', 'неизвестно')}")
        if saturn:
            indicators.append(
                f"Сатурн (хронические состояния) в {saturn.get('sign', 'неизвестно')} доме {saturn.get('house', 'неизвестно')}")
        if chiron:
            indicators.append(
                f"Хирон (уязвимость, исцеление) в {chiron.get('sign', 'неизвестно')} доме {chiron.get('house', 'неизвестно')}")

        # 5. Дополнительные аспекты между сигнификаторами
        health_aspects = []
        for a in aspects:
            p1 = a.get('p1', '').lower()
            p2 = a.get('p2', '').lower()
            if any(x in (p1, p2) for x in ['moon', 'saturn', 'chiron', 'hygeia']):
                if p1 != p2:
                    aspect_name = a.get('aspect', '')
                    orb = a.get('orb', 0.0)
                    if aspect_name.lower() in self.MAJOR_ASPECTS and orb <= self.MAX_ORB:
                        health_aspects.append(f"{p1.capitalize()} {aspect_name} {p2.capitalize()} (орбис: {orb:.2f}°)")
        if health_aspects:
            indicators.append("Аспекты между сигнификаторами здоровья: " + ", ".join(health_aspects[:3]))  # ограничим 3

        return "\n".join(indicators) if indicators else "Нет данных по медицинским показателям."

    def _get_astrocartography_string(self, lang: str = 'ru') -> str:
        """
        Рассчитывает астрокартографические линии (MC, IC, ASC, DSC) для основных планет
        с помощью библиотеки ephem.
        """
        try:
            import ephem
            from math import pi, degrees
        except ImportError:
            if lang == 'ru':
                return "❌ Библиотека ephem не установлена. Установите её для расчёта астрокартографии."
            else:
                return "❌ ephem library is not installed. Install it for astrocartography calculation."

        try:
            # 1. Парсим дату и время рождения
            year, month, day, hour, minute = self._parse_birth_datetime()
            birth_dt = datetime(year, month, day, hour, minute)
            date_str = birth_dt.strftime('%Y/%m/%d %H:%M:%S')

            # 2. Получаем координаты места рождения
            lat, lng, tz_str = self._get_coordinates_and_timezone()

            # 3. Создаём наблюдателя для расчёта звёздного времени (на месте рождения)
            obs = ephem.Observer()
            obs.lat = str(lat)
            obs.lon = str(lng)
            obs.date = date_str

            # 4. Гринвичское звёздное время (GST) в радианах и часах
            gst_rad = obs.sidereal_time()  # радианы
            gst_hours = gst_rad * 12 / pi  # часы (0–24)

            # 5. Список планет
            planet_names = ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars', 'Jupiter', 'Saturn']

            lines_by_planet = {}

            for name in planet_names:
                body = getattr(ephem, name)()
                body.compute(ephem.Date(date_str))

                # Прямое восхождение (RA) в часах
                ra_hours = body.ra * 12 / pi

                # Списки долгот для каждой линии
                mc = []
                ic = []
                asc = []
                dsc = []

                # Перебираем долготы на Земле от -180 до +180 с шагом 1°
                for lon_deg in range(-180, 181, 1):
                    # Местное звёздное время = GST + долгота (1 час = 15°)
                    lst = (gst_hours + lon_deg / 15) % 24

                    # Порог совпадения (0.3 часа ≈ 4.5°)
                    threshold = 0.3

                    # MC – планета в верхней кульминации (RA == LST)
                    if abs(lst - ra_hours) % 24 < threshold:
                        mc.append(lon_deg)

                    # IC – планета в нижней кульминации (RA == LST + 12h)
                    if abs((lst - (ra_hours + 12) % 24)) % 24 < threshold:
                        ic.append(lon_deg)

                    # ASC – планета восходит (RA == LST + 6h)
                    if abs((lst - (ra_hours + 6) % 24)) % 24 < threshold:
                        asc.append(lon_deg)

                    # DSC – планета заходит (RA == LST + 18h)
                    if abs((lst - (ra_hours + 18) % 24)) % 24 < threshold:
                        dsc.append(lon_deg)

                # Сохраняем результаты, если есть хотя бы одна линия
                if mc or ic or asc or dsc:
                    lines_by_planet[name] = {
                        'MC': mc,
                        'IC': ic,
                        'ASC': asc,
                        'DSC': dsc
                    }

            # 8. Форматируем результат для промпта
            if not lines_by_planet:
                if lang == 'ru':
                    return "Астрокартографические линии не найдены. Попробуйте изменить порог чувствительности."
                else:
                    return "Astrocartography lines not found. Try adjusting the threshold."

            result_lines = []
            # Переводы названий линий и планет (для русского языка)
            line_names_ru = {
                'MC': 'кульминация (карьера)',
                'IC': 'надир (дом)',
                'ASC': 'восход (личность)',
                'DSC': 'заход (отношения)'
            }
            planet_names_ru = {
                'Sun': 'Солнце',
                'Moon': 'Луна',
                'Mercury': 'Меркурий',
                'Venus': 'Венера',
                'Mars': 'Марс',
                'Jupiter': 'Юпитер',
                'Saturn': 'Сатурн'
            }

            for planet, lines in lines_by_planet.items():
                if lang == 'ru':
                    planet_display = planet_names_ru.get(planet, planet)
                    line_desc = []
                    if lines['MC']:
                        line_desc.append(f"MC: {', '.join(map(str, lines['MC']))}°")
                    if lines['IC']:
                        line_desc.append(f"IC: {', '.join(map(str, lines['IC']))}°")
                    if lines['ASC']:
                        line_desc.append(f"ASC: {', '.join(map(str, lines['ASC']))}°")
                    if lines['DSC']:
                        line_desc.append(f"DSC: {', '.join(map(str, lines['DSC']))}°")
                    result_lines.append(f"• {planet_display}: " + "; ".join(line_desc))
                else:
                    line_desc = []
                    if lines['MC']:
                        line_desc.append(f"MC: {', '.join(map(str, lines['MC']))}°")
                    if lines['IC']:
                        line_desc.append(f"IC: {', '.join(map(str, lines['IC']))}°")
                    if lines['ASC']:
                        line_desc.append(f"ASC: {', '.join(map(str, lines['ASC']))}°")
                    if lines['DSC']:
                        line_desc.append(f"DSC: {', '.join(map(str, lines['DSC']))}°")
                    result_lines.append(f"• {planet}: " + "; ".join(line_desc))

            # Добавляем краткое пояснение
            note = ("\n\n*Примечание: линии рассчитаны приблизительно (погрешность ~4.5°). "
                    "Для точного анализа используйте специализированные сервисы.*" if lang == 'ru'
                    else "\n\n*Note: lines are approximate (error ~4.5°). For precise analysis, use specialized services.*")

            return "\n".join(result_lines) + note

        except Exception as e:
            logger.error(f"Ошибка при расчёте астрокартографии: {e}")
            if lang == 'ru':
                return "Произошла ошибка при расчёте астрокартографических линий."
            else:
                return "An error occurred while calculating astrocartography lines."

# ---------- ОСТАЛЬНЫЕ МЕТОДЫ (build_prompt, get_display_parameters и др.) ----------

    def _load_prompt_template(self) -> Optional[str]:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        filepath = os.path.join(base_dir, 'prompts', 'prompt_astrology.txt')
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            logger.error("Файл prompt_astrology.txt не найден")
            return None

    def build_prompt(self, lang: str = 'ru') -> str:
        chart = self._calculate_chart()
        from bot.locales import TEXTS
        texts = TEXTS.get(lang, TEXTS['ru'])

        sign_abbr = texts.get('astro_sign_abbr', {})

        def translate_sign(sign):
            return sign_abbr.get(sign, sign)

        sun_sign = None
        moon_sign = None
        ascendant = None
        for planet in chart['planets']:
            if planet['name'] == 'Sun':
                sun_sign = translate_sign(planet['sign'])
            elif planet['name'] == 'Moon':
                moon_sign = translate_sign(planet['sign'])
        if chart['houses']:
            ascendant = translate_sign(chart['houses'][0]['sign'])

        planets_str = "\n".join(
            f"- {p['name']} в {translate_sign(p['sign'])} ({p['degree']:.2f}°) в {p['house']} доме"
            for p in chart['planets']
        )

        filtered_aspects = []
        for a in chart['aspects']:
            aspect_name = a['aspect'].lower()
            if aspect_name in self.MAJOR_ASPECTS and a['orb'] <= self.MAX_ORB:
                filtered_aspects.append(a)

        aspects_str = ""
        if filtered_aspects:
            aspects_str = "\n".join(
                f"- {a['p1']} {a['aspect']} {a['p2']} (орбис: {a['orb']:.2f}°)" for a in filtered_aspects
            )

        cusps_str = self._get_house_cusps_string(lang)

        transit_aspects_str = self._get_transit_aspects_string(lang)
        progression_aspects_str = self._get_progression_aspects_string(lang)
        health_indicators_str = self._get_health_indicators_string(lang)
        astrocartography_str = self._get_astrocartography_string(lang)

        gender_display = "Мужчина" if self.gender == 'M' else "Женщина"
        pronoun = "он" if self.gender == 'M' else "она"
        possessive = "его" if self.gender == 'M' else "её"

        # ---- Языковая инструкция для нейросети ----
        if lang == 'en':
            language_instruction = "IMPORTANT: Respond in English only. All your analysis must be in English."
        else:
            language_instruction = "ВАЖНО: Отвечай только на русском языке. Весь анализ должен быть на русском."

        template = self._load_prompt_template()
        if not template:
            return self._build_fallback_prompt(chart, lang)

        replacements = {
            "name": chart['name'],
            "gender_display": gender_display,
            "birth_date": self.birth_date_str or "не указана (используем 01.01.2000)",
            "birth_time": self.birth_time_str or "не указано (используем 12:00)",
            "birth_place": self.birth_place or "не указано (используем Москва)",
            "sun_sign": sun_sign or "не известно",
            "moon_sign": moon_sign or "не известно",
            "ascendant": ascendant or "не известно",
            "planets_list": planets_str,
            "aspects_list": aspects_str,
            "cusps_list": cusps_str,
            "transit_aspects_list": transit_aspects_str,
            "progression_aspects_list": progression_aspects_str,
            "health_indicators_list": health_indicators_str,
            "astrocartography_lines": astrocartography_str,
            "extra_info": self.extra_info,
            "pronoun": pronoun,
            "possessive": possessive,
            "language_instruction": language_instruction,  # <-- добавлено
        }

        prompt = template
        for key, value in replacements.items():
            prompt = prompt.replace(f'{{{key}}}', str(value))

        return prompt

    def _build_fallback_prompt(self, chart: dict, lang: str = 'ru') -> str:
        from bot.locales import TEXTS
        texts = TEXTS.get(lang, TEXTS['ru'])
        sign_abbr = texts.get('astro_sign_abbr', {})
        def translate_sign(sign):
            return sign_abbr.get(sign, sign)

        planets_str = "\n".join(
            f"- {p['name']} в {translate_sign(p['sign'])} ({p['degree']:.2f}°) в {p['house']} доме"
            for p in chart['planets']
        )
        cusps_str = self._get_house_cusps_string(lang)
        transit_aspects_str = self._get_transit_aspects_string(lang)
        progression_aspects_str = self._get_progression_aspects_string(lang)
        health_indicators_str = self._get_health_indicators_string(lang)
        pronoun = "он" if self.gender == 'M' else "она"
        possessive = "его" if self.gender == 'M' else "её"
        return f"""
Ты — профессиональный астролог. Проведи интерпретацию натальной карты для {chart['name']} ({pronoun}).

Данные рождения:
- Дата и время: {chart['datetime']}
- Место: широта {chart['location']['lat']}, долгота {chart['location']['lng']}

Планеты в знаках и домах:
{planets_str}

Куспиды домов:
{cusps_str}

Транзитные аспекты на текущий момент:
{transit_aspects_str}

Прогрессивные аспекты:
{progression_aspects_str}

Медицинские показатели (6-й и 8-й дома, Гигиея):
{health_indicators_str}

Опиши характер, эмоции, общение, сильные стороны, зоны роста, таланты, дай практические советы, учти влияние транзитов, прогрессий и здоровье.
"""

    def _get_house_cusps_string(self, lang: str = 'ru') -> str:
        chart = self._calculate_chart()
        from bot.locales import TEXTS
        texts = TEXTS.get(lang, TEXTS['ru'])
        sign_abbr = texts.get('astro_sign_abbr', {})
        def translate_sign(sign):
            return sign_abbr.get(sign, sign)

        cusp_fmt = texts.get('astro_house_cusp', "House {number}: {sign} {degree:.2f}°")
        lines = []
        for h in chart['houses']:
            sign = translate_sign(h['sign'])
            degree = h['degree']
            lines.append(cusp_fmt.format(number=h['number'], sign=sign, degree=degree))
        return "\n".join(lines)

    def get_basic_parameters(self, lang: str = 'ru') -> str:
        chart = self._calculate_chart()
        from bot.locales import TEXTS
        texts = TEXTS.get(lang, TEXTS['ru'])
        sign_abbr = texts.get('astro_sign_abbr', {})
        def translate_sign(sign):
            return sign_abbr.get(sign, sign)

        sun_sign = None
        moon_sign = None
        ascendant = None
        for planet in chart['planets']:
            if planet['name'] == 'Sun':
                sun_sign = translate_sign(planet['sign'])
            elif planet['name'] == 'Moon':
                moon_sign = translate_sign(planet['sign'])
        if chart['houses']:
            ascendant = translate_sign(chart['houses'][0]['sign'])

        name_label = texts.get('astro_name', '👤 Name')
        gender_label = texts.get('astro_gender', '⚥ Gender')
        local_time_label = texts.get('astro_local_time', '📅 Local time')
        timezone_label = texts.get('astro_timezone', '🕒 Timezone')
        utc_label = texts.get('astro_utc_time', '🕒 UTC time')
        place_label = texts.get('astro_place', '📍 Place')
        coords_label = texts.get('astro_coordinates', '🌐 Coordinates')
        sun_label = texts.get('astro_sun', '☀️ Sun')
        moon_label = texts.get('astro_moon', '🌙 Moon')
        asc_label = texts.get('astro_ascendant', '⬆️ Ascendant')

        datetime_used = chart['datetime']
        timezone_used = chart['timezone']
        lat = chart['location']['lat']
        lng = chart['location']['lng']
        utc_display = chart.get('utc_datetime', 'не известно')
        city, country = self._parse_birth_place()
        place_display = f"{city}, {country}" if city else "не указано (использованы координаты по умолчанию)"
        gender_display = texts.get('astro_gender_male', 'Male') if self.gender == 'M' else texts.get('astro_gender_female', 'Female')

        lines = [
            "━━━━━━━━━━━━━━━━━━━━━",
            f"{name_label}: {self.name}",
            f"{gender_label}: {gender_display}",
            f"{local_time_label}: {datetime_used}",
            f"{timezone_label}: {timezone_used}",
            f"{utc_label}: {utc_display}",
            f"{place_label}: {place_display}",
            f"{coords_label}: {lat:.4f}, {lng:.4f}",
            "━━━━━━━━━━━━━━━━━━━━━",
            f"{sun_label}: {sun_sign or 'не известно'}",
            f"{moon_label}: {moon_sign or 'не известно'}",
            f"{asc_label}: {ascendant or 'не известно'}",
        ]
        return "\n".join(lines)

    def get_extra_parameters(self, lang: str = 'ru') -> str:
        chart = self._calculate_chart()
        from bot.locales import TEXTS
        texts = TEXTS.get(lang, TEXTS['ru'])

        planet_names = texts.get('astro_planet_names', {})
        sign_abbr = texts.get('astro_sign_abbr', {})
        house_names = texts.get('astro_house_names', {})
        aspect_names = texts.get('astro_aspect_names', {})

        def translate_planet(name):
            return planet_names.get(name, name)

        def translate_sign(sign):
            return sign_abbr.get(sign, sign)

        def translate_house(house):
            return house_names.get(house, house)

        def translate_aspect(aspect):
            return aspect_names.get(aspect, aspect)

        planets_lines = []
        for p in chart['planets']:
            planet_name = translate_planet(p['name'])
            sign = translate_sign(p['sign'])
            house = translate_house(p['house'])
            degree = p['degree']
            fmt = texts.get('astro_planet_format', '  • {planet} in {sign} ({degree:.2f}°) in {house} house')
            planets_lines.append(fmt.format(planet=planet_name, sign=sign, degree=degree, house=house))
        planets_str = "\n".join(planets_lines)

        filtered_aspects = []
        for a in chart['aspects']:
            aspect_name = a['aspect'].lower()
            if aspect_name in self.MAJOR_ASPECTS and a['orb'] <= self.MAX_ORB:
                filtered_aspects.append(a)
        aspects_lines = []
        for a in filtered_aspects:
            p1 = translate_planet(a['p1'])
            p2 = translate_planet(a['p2'])
            aspect = translate_aspect(a['aspect'])
            orb = a['orb']
            fmt = texts.get('astro_aspect_format', '  • {p1} {aspect} {p2} (orb: {orb:.2f}°)')
            aspects_lines.append(fmt.format(p1=p1, p2=p2, aspect=aspect, orb=orb))
        aspects_str = "\n".join(aspects_lines)

        cusp_fmt = texts.get('astro_house_cusp', "House {number}: {sign} {degree:.2f}°")
        cusps_lines = []
        for h in chart['houses']:
            sign = translate_sign(h['sign'])
            degree = h['degree']
            cusps_lines.append(cusp_fmt.format(number=h['number'], sign=sign, degree=degree))
        cusps_str = "\n".join(cusps_lines)

        planets_header = texts.get('astro_planets_header', '🪐 Planets in signs and houses:')
        cusps_header = texts.get('astro_cusps_header', '🏠 House cusps:')
        aspects_header = texts.get('astro_aspects_header', '🔮 Major aspects (orb ≤ 5°):')

        lines = []
        if planets_str:
            lines.append("")
            lines.append(planets_header)
            lines.append(planets_str)
        if cusps_str:
            lines.append("")
            lines.append(cusps_header)
            lines.append(cusps_str)
        if aspects_str:
            lines.append("")
            lines.append(aspects_header)
            lines.append(aspects_str)

        # Добавляем транзитные и прогрессивные аспекты, медицинские показатели для администраторов
        transit_str = self._get_transit_aspects_string(lang)
        if transit_str:
            lines.append("")
            lines.append("🌟 Транзитные аспекты на текущий момент:")
            lines.append(transit_str)

        progression_str = self._get_progression_aspects_string(lang)
        if progression_str:
            lines.append("")
            lines.append("🔄 Прогрессивные аспекты:")
            lines.append(progression_str)

        health_str = self._get_health_indicators_string(lang)
        if health_str:
            lines.append("")
            lines.append("🏥 Медицинские показатели (6-й и 8-й дома, Гигиея):")
            lines.append(health_str)

        return "\n".join(lines)

    # ---- Вспомогательные методы для транзитов (используются ранее) ----
    def _get_transit_aspects_string(self, lang: str = 'ru') -> str:
        """Возвращает строку с транзитными аспектами на текущий момент."""
        from .transit_horoscope_calculator import TransitHoroscopeCalculator
        try:
            transit_calc = TransitHoroscopeCalculator(self.user_data, lang)
            data = transit_calc.calculate()
            transit_aspects = data.get('transit_aspects', '')
            if not transit_aspects or transit_aspects.strip() == '':
                return "Нет значимых транзитных аспектов на текущий момент."
            return transit_aspects
        except Exception as e:
            logger.error(f"Ошибка при расчёте транзитов: {e}")
            return "Ошибка при расчёте транзитных аспектов."

    def _get_natal_subject(self) -> AstrologicalSubject:
        """Возвращает натальный субъект (используется для прогрессий)."""
        year, month, day, hour, minute = self._parse_birth_datetime()
        lat, lng, tz_str = self._get_coordinates_and_timezone()
        return AstrologicalSubject(
            name=self.name,
            year=year,
            month=month,
            day=day,
            hour=hour,
            minute=minute,
            lat=lat,
            lng=lng,
            tz_str=tz_str,
        )

    # def _get_house_for_longitude(self, longitude: float, houses: List[Dict]) -> int:
    #     """
    #     Определяет номер дома по долготе планеты на основе куспидов домов.
    #     houses — список словарей с ключами 'number' и 'degree'.
    #     """
    #     if not houses:
    #         return 0
    #     # Сортируем дома по градусу
    #     sorted_houses = sorted(houses, key=lambda h: h['degree'])
    #     # Первый дом начинается с ASC, но для простоты используем цикл
    #     for i, h in enumerate(sorted_houses):
    #         next_house = sorted_houses[(i + 1) % len(sorted_houses)]
    #         # Проверяем, попадает ли долгота в интервал между куспидами
    #         start = h['degree']
    #         end = next_house['degree']
    #         if end < start:  # переход через 0°
    #             if longitude >= start or longitude < end:
    #                 return h['number']
    #         else:
    #             if start <= longitude < end:
    #                 return h['number']
    #     return 0

    def _ask_gemini_for_utc_and_timezone(self, city: str, country: str, lat: float, lng: float,
                                         year: int, month: int, day: int, hour: int, minute: int) -> Optional[
        Dict[str, str]]:
        if not self.__class__.gemini_service:
            return None
        prompt = (
            f"Определи точное UTC время и дату для места с координатами "
            f"широта {lat}, долгота {lng}, населённый пункт {city}, {country}, "
            f"для местной даты {day:02d}.{month:02d}.{year} и времени {hour:02d}:{minute:02d}. "
            f"Учти все исторические переходы на летнее время в этом регионе на указанную дату. "
            f"На основании разницы между вычесленными датой и временем и местной датой {day:02d}.{month:02d}.{year} и временем {hour:02d}:{minute:02d}"
            f"вычисли соответствующий часовой пояс (по стандарту IANA). "
            f"Верни ответ в формате JSON с полями: 'utc_datetime' (в формате YYYY-MM-DD HH:MM:SS) и "
            f"'timezone' (название IANA, например 'Asia/Magadan'). Если точное название неизвестно, "
            f"укажи наиболее вероятное."
        )
        try:
            response = self.__class__.gemini_service.send_raw_prompt(prompt)
            logger.info(f"📥 Ответ Gemini для уточнения таймзоны: {response[:200]}...")  # <-- добавлено
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                if 'utc_datetime' in data and 'timezone' in data:
                    return data
            logger.warning(f"Не удалось распарсить ответ нейросети: {response[:200]}...")
            return None
        except Exception as e:
            logger.error(f"Ошибка при запросе UTC к нейросети: {e}")
            return None

    def _refine_timezone(self, tz_str: str, city: str, country: str, lat: float, lng: float) -> str:
        """
        Уточняет часовой пояс через Gemini (без кеширования).
        Возвращает уточнённую таймзону или исходную, если уточнить не удалось.
        """
        if self.__class__.gemini_service:
            try:
                year, month, day, hour, minute = self._parse_birth_datetime()
                result = self._ask_gemini_for_utc_and_timezone(
                    city, country, lat, lng, year, month, day, hour, minute
                )
                if result:
                    timezone_name = result.get('timezone')
                    if timezone_name and timezone_name in pytz.all_timezones:
                        logger.info(f"✅ Таймзона уточнена через Gemini: {timezone_name} (было: {tz_str})")
                        return timezone_name
            except Exception as e:
                logger.warning(f"⚠️ Ошибка при уточнении таймзоны через Gemini: {e}")
        else:
            logger.warning("⚠️ Gemini сервис недоступен, уточнение таймзоны пропущено")

        # Если не удалось уточнить, возвращаем исходную
        return tz_str