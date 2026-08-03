import os
import requests
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from kerykeion import AstrologicalSubject  # ← правильный импорт
from timezonefinder import TimezoneFinder

logger = logging.getLogger(__name__)


class AstrologyCalculator:
    """
    Класс для расчёта астрологических параметров с помощью kerykeion.
    Все недостающие данные заменяются значениями по умолчанию.
    """

    DEFAULT_LAT = 55.7558
    DEFAULT_LNG = 37.6173
    DEFAULT_TZ = "Europe/Moscow"

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

    def _parse_birth_datetime(self) -> tuple:
        date_str = self.birth_date_str or "01.01.2000"
        time_str = self.birth_time_str or "12:00"
        try:
            dt = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")
            return dt.year, dt.month, dt.day, dt.hour, dt.minute
        except ValueError:
            logger.warning(f"Неверный формат даты/времени: {date_str} {time_str}. Используем 01.01.2000 12:00")
            return 2000, 1, 1, 12, 0

    def _parse_birth_place(self) -> tuple:
        place = self.birth_place.strip()
        if not place:
            logger.warning("Место рождения не указано. Используем 'Москва, Россия'")
            return "Москва", "RU"
        parts = [p.strip() for p in place.split(',') if p.strip()]
        city = parts[0] if parts else "Москва"
        country = parts[1] if len(parts) > 1 else "RU"
        return city, country

    def _get_coordinates(self, city: str, country: str = None) -> Dict[str, float]:
        url = "https://geocoding-api.open-meteo.com/v1/search"
        params = {"name": city, "count": 1, "format": "json", "language": "ru"}
        if country:
            params["countryCode"] = country.upper()
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results")
            if not results:
                logger.warning(f"Город '{city}' не найден. Используем Москву.")
                return {"lat": self.DEFAULT_LAT, "lng": self.DEFAULT_LNG}
            loc = results[0]
            return {"lat": loc["latitude"], "lng": loc["longitude"]}
        except Exception as e:
            logger.error(f"Ошибка геокодирования: {e}. Используем Москву.")
            return {"lat": self.DEFAULT_LAT, "lng": self.DEFAULT_LNG}

    def _get_timezone(self, lat: float, lng: float) -> str:
        try:
            tz_name = self._tf.timezone_at(lat=lat, lng=lng)
            if tz_name:
                return tz_name
            else:
                logger.warning(f"Не удалось определить часовой пояс. Используем {self.DEFAULT_TZ}")
                return self.DEFAULT_TZ
        except Exception as e:
            logger.error(f"Ошибка определения часового пояса: {e}. Используем {self.DEFAULT_TZ}")
            return self.DEFAULT_TZ

    def _calculate_chart(self) -> Dict[str, Any]:
        if self._chart_data is not None:
            return self._chart_data

        year, month, day, hour, minute = self._parse_birth_datetime()
        city, country = self._parse_birth_place()
        coords = self._get_coordinates(city, country)
        self._coords = coords
        tz_str = self._get_timezone(coords['lat'], coords['lng'])
        self._timezone = tz_str

        subject = AstrologicalSubject(
            name=self.name,
            year=year,
            month=month,
            day=day,
            hour=hour,
            minute=minute,
            lat=coords['lat'],
            lng=coords['lng'],
            tz_str=tz_str,
        )

        # Получаем модель как словарь
        model_data = subject.model() if callable(subject.model) else subject.model
        if hasattr(model_data, 'dict'):
            data = model_data.dict()
        elif hasattr(model_data, 'model_dump'):
            data = model_data.model_dump()
        else:
            data = model_data.__dict__

        logger.info(f"Ключи данных: {list(data.keys()) if isinstance(data, dict) else 'не словарь'}")

        # --- Список ключей, которые являются планетами (имеют sign, position, house) ---
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

        # --- Извлечение планет ---
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
                    # если объект с атрибутами
                    if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                        planets.append({
                            "name": key.capitalize(),
                            "sign": getattr(obj, 'sign', 'unknown'),
                            "degree": getattr(obj, 'position', 0.0),
                            "house": getattr(obj, 'house', 0),
                        })
        logger.info(f"Планеты получены: {len(planets)} планет")

        # --- Извлечение домов ---
        houses = []
        for i in range(1, 13):
            key = f"{i}_house" if i != 1 else "first_house"  # но в данных ключи типа "first_house", "second_house"...
            # Используем правильные ключи: first_house, second_house, ..., twelfth_house
            if i == 1:
                key = "first_house"
            elif i == 2:
                key = "second_house"
            elif i == 3:
                key = "third_house"
            elif i == 4:
                key = "fourth_house"
            elif i == 5:
                key = "fifth_house"
            elif i == 6:
                key = "sixth_house"
            elif i == 7:
                key = "seventh_house"
            elif i == 8:
                key = "eighth_house"
            elif i == 9:
                key = "ninth_house"
            elif i == 10:
                key = "tenth_house"
            elif i == 11:
                key = "eleventh_house"
            elif i == 12:
                key = "twelfth_house"

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

        # --- Аспекты (получаем через subject.get_aspects() или subject.aspects) ---
        aspects = []
        if hasattr(subject, 'get_aspects') and callable(subject.get_aspects):
            try:
                raw_aspects = subject.get_aspects()
                if raw_aspects:
                    for a in raw_aspects:
                        orb_val = getattr(a, 'orb', getattr(a, 'orbis', 0.0))
                        aspects.append({
                            "p1": getattr(a, 'p1_name', 'unknown'),
                            "p2": getattr(a, 'p2_name', 'unknown'),
                            "aspect": getattr(a, 'aspect', 'unknown'),
                            "orb": orb_val,
                        })
                    logger.info(f"Аспекты получены через get_aspects(): {len(aspects)} аспектов")
            except Exception as e:
                logger.warning(f"Ошибка при получении аспектов через get_aspects(): {e}")
        elif hasattr(subject, 'aspects') and subject.aspects:
            for a in subject.aspects:
                orb_val = getattr(a, 'orb', getattr(a, 'orbis', 0.0))
                aspects.append({
                    "p1": getattr(a, 'p1_name', 'unknown'),
                    "p2": getattr(a, 'p2_name', 'unknown'),
                    "aspect": getattr(a, 'aspect', 'unknown'),
                    "orb": orb_val,
                })
            logger.info(f"Аспекты получены из subject.aspects: {len(aspects)} аспектов")
        else:
            logger.warning("Не удалось получить аспекты. Они будут пустыми.")

        result = {
            "name": subject.name,
            "datetime": f"{year}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}",
            "timezone": tz_str,
            "location": {"lat": coords['lat'], "lng": coords['lng']},
            "planets": planets,
            "houses": houses,
            "aspects": aspects,
        }

        self._chart_data = result
        return result

    def _load_prompt_template(self) -> Optional[str]:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        filepath = os.path.join(base_dir, 'prompts', 'prompt_astrology.txt')
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            logger.error("Файл prompt_astrology.txt не найден")
            return None

    def build_prompt(self) -> str:
        chart = self._calculate_chart()

        sun_sign = None
        moon_sign = None
        ascendant = None
        for planet in chart['planets']:
            if planet['name'] == 'Sun':
                sun_sign = planet['sign']
            elif planet['name'] == 'Moon':
                moon_sign = planet['sign']
        if chart['houses']:
            ascendant = chart['houses'][0]['sign']

        planets_str = "\n".join(
            f"- {p['name']} в {p['sign']} ({p['degree']:.2f}°) в {p['house']} доме"
            for p in chart['planets']
        )

        aspects_str = ""
        if chart['aspects']:
            aspects_str = "\n".join(
                f"- {a['p1']} {a['aspect']} {a['p2']} (орбис: {a['orb']:.2f}°)" for a in chart['aspects']
            )

        gender_display = "Мужчина" if self.gender == 'M' else "Женщина"
        pronoun = "он" if self.gender == 'M' else "она"
        possessive = "его" if self.gender == 'M' else "её"

        template = self._load_prompt_template()
        if not template:
            return self._build_fallback_prompt(chart)

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
            "extra_info": self.extra_info,
            "pronoun": pronoun,
            "possessive": possessive,
        }

        prompt = template
        for key, value in replacements.items():
            prompt = prompt.replace(f"{{{key}}}", str(value))

        return prompt

    def _build_fallback_prompt(self, chart: dict) -> str:
        planets_str = "\n".join(
            f"- {p['name']} в {p['sign']} ({p['degree']:.2f}°) в {p['house']} доме"
            for p in chart['planets']
        )
        pronoun = "он" if self.gender == 'M' else "она"
        possessive = "его" if self.gender == 'M' else "её"
        return f"""
Ты — профессиональный астролог. Проведи интерпретацию натальной карты для {chart['name']} ({pronoun}).

Данные рождения:
- Дата и время: {chart['datetime']}
- Место: широта {chart['location']['lat']}, долгота {chart['location']['lng']}

Планеты в знаках и домах:
{planets_str}

Опиши характер, эмоции, общение, сильные стороны, зоны роста, таланты и дай практические советы.
"""

    def get_display_parameters(self) -> str:
        chart = self._calculate_chart()

        sun_sign = None
        moon_sign = None
        ascendant = None
        for planet in chart['planets']:
            if planet['name'] == 'Sun':
                sun_sign = planet['sign']
            elif planet['name'] == 'Moon':
                moon_sign = planet['sign']
        if chart['houses']:
            ascendant = chart['houses'][0]['sign']

        planets_str = "\n".join(
            f"  • {p['name']} в {p['sign']} ({p['degree']:.2f}°) в {p['house']} доме"
            for p in chart['planets']
        )

        aspects_str = ""
        if chart['aspects']:
            aspects_str = "\n".join(
                f"  • {a['p1']} {a['aspect']} {a['p2']} (орбис: {a['orb']:.2f}°)" for a in chart['aspects']
            )

        datetime_used = chart['datetime']
        timezone_used = chart['timezone']
        lat = chart['location']['lat']
        lng = chart['location']['lng']
        city, country = self._parse_birth_place()
        place_display = f"{city}, {country}" if city else "не указано (использованы координаты по умолчанию)"

        gender_display = "Мужчина" if self.gender == 'M' else "Женщина"

        lines = [
            "━━━━━━━━━━━━━━━━━━━━━",
            f"👤 Имя: {self.name}",
            f"⚥ Пол: {gender_display}",
            f"📅 Дата и время (UTC): {datetime_used}",
            f"🕒 Часовой пояс: {timezone_used}",
            f"📍 Место: {place_display}",
            f"🌐 Координаты: {lat:.4f}, {lng:.4f}",
            "━━━━━━━━━━━━━━━━━━━━━",
            f"☀️ Солнце: {sun_sign or 'не известно'}",
            f"🌙 Луна: {moon_sign or 'не известно'}",
            f"⬆️ Асцендент: {ascendant or 'не известно'}",
            "",
            "🪐 Планеты в знаках и домах:",
            planets_str,
        ]

        if aspects_str:
            lines.append("")
            lines.append("🔮 Аспекты между планетами:")
            lines.append(aspects_str)

        lines.append("━━━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)