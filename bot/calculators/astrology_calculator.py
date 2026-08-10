import os
import requests
import json
import logging
import re
from datetime import datetime
from typing import Dict, Any, Optional, Tuple

from kerykeion import AstrologicalSubject
from timezonefinder import TimezoneFinder
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable

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

    # Статическая переменная для доступа к нейросети (устанавливается из main.py)
    gemini_service = None

    def __init__(self, user_data: Dict[str, Any]):
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
        Определяет координаты и часовой пояс для места рождения.
        Возвращает (lat, lng, tz_str).
        """
        city, country = self._parse_birth_place()
        if not city:  # если место не указано вообще
            logger.warning("Место рождения не указано. Используем Москву")
            return self.DEFAULT_LAT, self.DEFAULT_LNG, self.DEFAULT_TZ

        # 1. Пробуем геокодеры
        coords = self._get_coordinates_geocoder(city, country)
        if coords:
            lat, lng = coords['lat'], coords['lng']
            tz_str = self._get_timezone_from_coords(lat, lng)
            if tz_str:
                logger.info(f"✅ Найдено через геокодер: {city}, {country} ({lat}, {lng}, {tz_str})")
                return lat, lng, tz_str

        # 2. Если геокодеры не нашли – пробуем нейросеть
        if self.__class__.gemini_service:
            logger.info(f"🌐 Геокодер не нашёл {city}, {country}. Пробуем нейросеть...")
            result = self._ask_gemini_for_coords(city, country)
            if result and 'lat' in result and 'lng' in result and 'timezone' in result:
                lat, lng, tz_str = result['lat'], result['lng'], result['timezone']
                logger.info(f"✅ Найдено через нейросеть: {city}, {country} ({lat}, {lng}, {tz_str})")
                return lat, lng, tz_str
            else:
                logger.warning(f"❌ Нейросеть не дала координат для {city}, {country}")
        else:
            logger.warning("⚠️ Gemini сервис не доступен для определения координат")

        # 3. Если нейросеть не помогла, пробуем найти столицу страны через геокодер
        if country and country != "RU":
            logger.info(f"🌐 Пробуем найти столицу страны {country} через геокодер...")
            capital_coords = self._get_capital_coords(country)
            if capital_coords:
                lat, lng = capital_coords['lat'], capital_coords['lng']
                tz_str = self._get_timezone_from_coords(lat, lng)
                if tz_str:
                    logger.info(f"✅ Найдена столица {country}: ({lat}, {lng}, {tz_str})")
                    return lat, lng, tz_str

        # 4. Всё провалилось – Москва
        logger.warning(f"❌ Не удалось определить координаты для {city}, {country}. Используем Москву.")
        return self.DEFAULT_LAT, self.DEFAULT_LNG, self.DEFAULT_TZ

    def _get_coordinates_geocoder(self, city: str, country: str = None) -> Optional[Dict[str, float]]:
        """Пытается получить координаты через Nominatim и Open-Meteo."""
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
        """Пытается найти координаты столицы страны через Nominatim."""
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

    def _calculate_chart(self) -> Dict[str, Any]:
        if self._chart_data is not None:
            return self._chart_data

        year, month, day, hour, minute = self._parse_birth_datetime()
        city, country = self._parse_birth_place()

        lat, lng, tz_str = self._get_coordinates_and_timezone()
        self._coords = {"lat": lat, "lng": lng}
        self._timezone = tz_str

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

        model_data = subject.model() if callable(subject.model) else subject.model
        if hasattr(model_data, 'dict'):
            data = model_data.dict()
        elif hasattr(model_data, 'model_dump'):
            data = model_data.model_dump()
        else:
            data = model_data.__dict__

        logger.info(f"Ключи данных: {list(data.keys()) if isinstance(data, dict) else 'не словарь'}")

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
            'vertex', 'anti_vertex'
        ]

        planets = []
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
        logger.info(f"Планеты получены: {len(planets)} планет")

        houses = []
        house_keys = [
            'first_house', 'second_house', 'third_house', 'fourth_house',
            'fifth_house', 'sixth_house', 'seventh_house', 'eighth_house',
            'ninth_house', 'tenth_house', 'eleventh_house', 'twelfth_house'
        ]
        for i, key in enumerate(house_keys, 1):
            if key in data:
                obj = data[key]
                if isinstance(obj, dict):
                    if 'sign' in obj and 'position' in obj:
                        houses.append({
                            "number": i,
                            "sign": obj.get('sign', 'unknown'),
                            "degree": obj.get('position', 0.0),
                        })
                else:
                    if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                        houses.append({
                            "number": i,
                            "sign": getattr(obj, 'sign', 'unknown'),
                            "degree": getattr(obj, 'position', 0.0),
                        })
        logger.info(f"Дома получены: {len(houses)} домов")

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
                logger.info(f"Аспекты получены через AspectsFactory: {len(aspects)} аспектов")
        except Exception as e:
            logger.warning(f"Ошибка при AspectsFactory: {e}")

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
                    logger.info(f"Аспекты получены через NatalAspects: {len(aspects)} аспектов")
            except Exception as e:
                logger.warning(f"Ошибка при NatalAspects: {e}")

        if not aspects:
            logger.warning("Не удалось получить аспекты. Они будут пустыми.")

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
        }

        self._chart_data = result
        return result

    def _get_house_cusps_string(self, lang: str = 'ru') -> str:
        """Возвращает отформатированную строку с куспидами домов на нужном языке."""
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

        # Фильтрация аспектов
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

        # Куспиды домов
        cusps_str = self._get_house_cusps_string(lang)

        gender_display = "Мужчина" if self.gender == 'M' else "Женщина"
        pronoun = "он" if self.gender == 'M' else "она"
        possessive = "его" if self.gender == 'M' else "её"

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
            "cusps_list": cusps_str,   # <-- добавляем
            "extra_info": self.extra_info,
            "pronoun": pronoun,
            "possessive": possessive,
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

Опиши характер, эмоции, общение, сильные стороны, зоны роста, таланты и дай практические советы.
"""

    def get_display_parameters(self, lang: str = 'ru') -> str:
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

        # Куспиды домов
        cusp_fmt = texts.get('astro_house_cusp', "House {number}: {sign} {degree:.2f}°")
        cusps_lines = []
        for h in chart['houses']:
            sign = translate_sign(h['sign'])
            degree = h['degree']
            cusps_lines.append(cusp_fmt.format(number=h['number'], sign=sign, degree=degree))
        cusps_str = "\n".join(cusps_lines)

        # Локализованные заголовки
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
        planets_header = texts.get('astro_planets_header', '🪐 Planets in signs and houses:')
        aspects_header = texts.get('astro_aspects_header', '🔮 Major aspects (orb ≤ 5°):')
        cusps_header = texts.get('astro_cusps_header', '🏠 House cusps:')

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
            "",
            planets_header,
            planets_str,
        ]

        if cusps_str:
            lines.append("")
            lines.append(cusps_header)
            lines.append(cusps_str)

        if aspects_str:
            lines.append("")
            lines.append(aspects_header)
            lines.append(aspects_str)

        lines.append("━━━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)

    def get_basic_parameters(self, lang: str = 'ru') -> str:
        """
        Возвращает только базовые параметры (имя, пол, время, место, координаты, Солнце, Луна, Асцендент).
        Используется для всех пользователей.
        """
        chart = self._calculate_chart()
        from bot.locales import TEXTS
        texts = TEXTS.get(lang, TEXTS['ru'])

        sign_abbr = texts.get('astro_sign_abbr', {})

        def translate_sign(sign):
            return sign_abbr.get(sign, sign)

        # Определяем Солнце, Луну, Асцендент
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

        # Локализованные заголовки
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
        """
        Возвращает дополнительные данные: планеты, куспиды, аспекты.
        Используется только для разрешённых пользователей.
        """
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

        # Планеты
        planets_lines = []
        for p in chart['planets']:
            planet_name = translate_planet(p['name'])
            sign = translate_sign(p['sign'])
            house = translate_house(p['house'])
            degree = p['degree']
            fmt = texts.get('astro_planet_format', '  • {planet} in {sign} ({degree:.2f}°) in {house} house')
            planets_lines.append(fmt.format(planet=planet_name, sign=sign, degree=degree, house=house))
        planets_str = "\n".join(planets_lines)

        # Куспиды домов
        cusp_fmt = texts.get('astro_house_cusp', "House {number}: {sign} {degree:.2f}°")
        cusps_lines = []
        for h in chart['houses']:
            sign = translate_sign(h['sign'])
            degree = h['degree']
            cusps_lines.append(cusp_fmt.format(number=h['number'], sign=sign, degree=degree))
        cusps_str = "\n".join(cusps_lines)

        # Аспекты (фильтруем мажорные)
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

        # Собираем
        lines = []
        planets_header = texts.get('astro_planets_header', '🪐 Planets in signs and houses:')
        cusps_header = texts.get('astro_cusps_header', '🏠 House cusps:')
        aspects_header = texts.get('astro_aspects_header', '🔮 Major aspects (orb ≤ 5°):')

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

        return "\n".join(lines)