import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import pytz

from kerykeion import AstrologicalSubject
try:
    from kerykeion.transit import TransitSubject
except ImportError:
    TransitSubject = None
from .astrology_calculator import AstrologyCalculator
from .timezone_coords import TIMEZONE_COORDS
from .base_calculator import BaseCalculator

logger = logging.getLogger(__name__)


class TransitHoroscopeCalculator(BaseCalculator):
    """
    Класс для расчёта гороскопа на сегодня с учётом транзитов.
    Использует AstrologyCalculator для получения натальных данных.
    """

    def __init__(self, user_data: Dict[str, Any]):
        self.user_data = user_data
        self.birth_date = user_data.get('birth_date')
        self.birth_time = user_data.get('birth_time')
        self.birth_place = user_data.get('birth_place')
        self.name = user_data.get('name', 'Человек')
        self.gender = user_data.get('gender', 'M')
        self.timezone_offset = user_data.get('timezone_offset', 3)

        # Координаты для транзитов (по часовому поясу пользователя)
        tz_info = TIMEZONE_COORDS.get(self.timezone_offset, TIMEZONE_COORDS[3])
        self.transit_lat = tz_info["lat"]
        self.transit_lng = tz_info["lng"]
        self.transit_tz_str = tz_info["tz"]

        # Натальный калькулятор (используем его для получения всех данных)
        self.natal_calc = AstrologyCalculator(user_data)
        self.natal_chart = None
        self.transit_subject = None
        self.transit_chart = None

    def _get_natal_chart(self) -> Dict[str, Any]:
        """Возвращает натальную карту в виде словаря (через AstrologyCalculator)."""
        if self.natal_chart is None:
            self.natal_chart = self.natal_calc._calculate_chart()
        return self.natal_chart

    def _get_transit_subject(self) -> AstrologicalSubject:
        """Создаёт транзитный субъект на текущий момент в таймзоне пользователя."""
        if self.transit_subject is None:
            tz = pytz.timezone(self.transit_tz_str)
            now = datetime.now(tz)

            # Получаем координаты и таймзону для натальной карты
            lat, lng, tz_str = self.natal_calc._get_coordinates_and_timezone()

            if TransitSubject is not None:
                # Пытаемся использовать TransitSubject (если доступен)
                natal_subject = self.natal_calc._get_natal_subject()  # это метод AstrologyCalculator
                self.transit_subject = TransitSubject(
                    natal_subject,
                    year=now.year,
                    month=now.month,
                    day=now.day,
                    hour=now.hour,
                    minute=now.minute,
                    lat=self.transit_lat,
                    lng=self.transit_lng,
                    tz_str=self.transit_tz_str,
                )
            else:
                # Fallback: создаём обычный AstrologicalSubject для текущего времени
                self.transit_subject = AstrologicalSubject(
                    name="Transit",
                    year=now.year,
                    month=now.month,
                    day=now.day,
                    hour=now.hour,
                    minute=now.minute,
                    lat=self.transit_lat,
                    lng=self.transit_lng,
                    tz_str=self.transit_tz_str,
                )
        return self.transit_subject

    def _get_transit_chart(self) -> Dict[str, Any]:
        """Возвращает транзитную карту в виде словаря (из модели)."""
        if self.transit_chart is None:
            subject = self._get_transit_subject()
            model = subject.model() if callable(subject.model) else subject.model
            if hasattr(model, 'dict'):
                data = model.dict()
            elif hasattr(model, 'model_dump'):
                data = model.model_dump()
            else:
                data = model.__dict__
            self.transit_chart = data
        return self.transit_chart

    def _extract_planets_from_chart(self, chart_data: Dict[str, Any]) -> List[Dict]:
        """Извлекает список планет из словаря карты (аналогично AstrologyCalculator)."""
        planet_keys = [
            'sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter', 'saturn',
            'uranus', 'neptune', 'pluto', 'chiron', 'mean_lilith', 'true_lilith',
            'ceres', 'pallas', 'juno', 'vesta', 'eris', 'sedna', 'haumea', 'makemake',
            'mean_north_lunar_node', 'true_north_lunar_node',
            'mean_south_lunar_node', 'true_south_lunar_node'
        ]
        planets = []
        for key in planet_keys:
            if key in chart_data:
                obj = chart_data[key]
                if isinstance(obj, dict):
                    if 'sign' in obj and 'position' in obj:
                        planets.append({
                            "name": key.capitalize(),
                            "sign": obj.get('sign', 'unknown'),
                            "degree": obj.get('position', 0.0),
                            "house": obj.get('house', 0),
                            "retrograde": obj.get('retrograde', False),
                        })
                else:
                    if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                        planets.append({
                            "name": key.capitalize(),
                            "sign": getattr(obj, 'sign', 'unknown'),
                            "degree": getattr(obj, 'position', 0.0),
                            "house": getattr(obj, 'house', 0),
                            "retrograde": getattr(obj, 'retrograde', False),
                        })
        return planets

    def _get_transit_aspects_manual(self, natal_planets: List[Dict], transit_planets: List[Dict]) -> List[Dict]:
        """Ручной расчёт аспектов между натальными и транзитными планетами."""
        aspects = []
        aspect_types = {
            'conjunction': 8,
            'opposition': 8,
            'trine': 6,
            'square': 6,
            'sextile': 5,
        }

        for n_planet in natal_planets:
            n_deg = n_planet['degree']
            for t_planet in transit_planets:
                t_deg = t_planet['degree']
                diff = abs(n_deg - t_deg) % 360
                if diff > 180:
                    diff = 360 - diff

                for aspect_name, orb in aspect_types.items():
                    if aspect_name == 'conjunction' and diff <= orb:
                        aspects.append({
                            'transit_planet': t_planet['name'],
                            'natal_planet': n_planet['name'],
                            'aspect': aspect_name,
                            'orb': diff,
                        })
                        break
                    elif aspect_name == 'opposition' and abs(diff - 180) <= orb:
                        aspects.append({
                            'transit_planet': t_planet['name'],
                            'natal_planet': n_planet['name'],
                            'aspect': aspect_name,
                            'orb': abs(diff - 180),
                        })
                        break
                    elif aspect_name == 'trine' and abs(diff - 120) <= orb:
                        aspects.append({
                            'transit_planet': t_planet['name'],
                            'natal_planet': n_planet['name'],
                            'aspect': aspect_name,
                            'orb': abs(diff - 120),
                        })
                        break
                    elif aspect_name == 'square' and abs(diff - 90) <= orb:
                        aspects.append({
                            'transit_planet': t_planet['name'],
                            'natal_planet': n_planet['name'],
                            'aspect': aspect_name,
                            'orb': abs(diff - 90),
                        })
                        break
                    elif aspect_name == 'sextile' and abs(diff - 60) <= orb:
                        aspects.append({
                            'transit_planet': t_planet['name'],
                            'natal_planet': n_planet['name'],
                            'aspect': aspect_name,
                            'orb': abs(diff - 60),
                        })
                        break

        return aspects

    def calculate(self) -> Dict[str, Any]:
        """
        Выполняет все расчёты и возвращает данные для промпта.
        """
        # 1. Получаем натальную карту
        natal_chart = self._get_natal_chart()
        natal_planets = self._extract_planets_from_chart(natal_chart)
        natal_houses = natal_chart.get('houses', [])

        # 2. Получаем транзитную карту
        transit_chart = self._get_transit_chart()
        transit_planets = self._extract_planets_from_chart(transit_chart)

        # 3. Вычисляем транзитные аспекты (ручной расчёт)
        transit_aspects = self._get_transit_aspects_manual(natal_planets, transit_planets)

        # 4. Определяем Солнце, Луну, Асцендент из натальной карты
        sun = next((p for p in natal_planets if p['name'].lower() == 'sun'), None)
        moon = next((p for p in natal_planets if p['name'].lower() == 'moon'), None)
        ascendant = natal_houses[0]['sign'] if natal_houses else 'не известно'

        # 5. Формируем строки для планет и аспектов
        planets_str = "\n".join(
            f"- {p['name']} в {p['sign']} ({p['degree']:.2f}°) в {p['house']} доме"
            for p in natal_planets
        )
        # Натальные аспекты (можно взять из natal_chart)
        natal_aspects = natal_chart.get('aspects', [])
        aspects_str = "\n".join(
            f"- {a['p1']} {a['aspect']} {a['p2']} (орбис: {a['orb']:.2f}°)" for a in natal_aspects
        ) if natal_aspects else "не известно"

        # 6. Куспиды домов
        cusps = []
        for i, h in enumerate(natal_houses, 1):
            cusps.append(f"{i}-й дом: {h['sign']} ({h['degree']:.2f}°)")
        cusps_str = "\n".join(cusps) if cusps else "не известно"

        # 7. Транзитная Луна
        transit_moon = next((p for p in transit_planets if p['name'] == 'Moon'), None)
        transit_moon_sign = transit_moon['sign'] if transit_moon else 'не известно'
        transit_moon_house = transit_moon['house'] if transit_moon else 'не известно'

        # 8. Аспекты транзитной Луны (выбираем из транзитных аспектов, где участвует Луна)
        moon_aspects = []
        for a in transit_aspects:
            if 'Moon' in a['transit_planet'] or 'Moon' in a['natal_planet']:
                moon_aspects.append(
                    f"{a['transit_planet']} {a['aspect']} {a['natal_planet']} (орбис: {a['orb']:.2f}°)"
                )
        transit_moon_aspects = "\n".join(moon_aspects) if moon_aspects else "Нет значимых аспектов"

        # 9. Ретроградные планеты (из транзитной карты)
        retrograde_list = [p['name'] for p in transit_planets if p.get('retrograde', False)]
        retrograde_planets = ", ".join([f"{p} ℞" for p in retrograde_list]) if retrograde_list else "Нет ретроградных планет"

        # 10. Базовые нумерологические и астрономические расчёты
        target_date = datetime.now(pytz.timezone(self.transit_tz_str)).strftime("%d.%m.%Y")
        birth_date = self.birth_date or "01.01.2000"

        age = self.calculate_age(birth_date, target_date)
        life_path = self.calculate_life_path_number(birth_date)
        personal_day = self.calculate_personal_day_number(birth_date, target_date)
        personal_year = self.calculate_personal_year(birth_date, target_date)
        matrix = self.calculate_matrix_arcans(birth_date)
        transit_arcan = self.calculate_transit_arcan(birth_date, target_date)
        moon_illumination = self.moon_phase_percent(target_date)
        lunar_day = self.get_lunar_day(target_date)
        week_day = self.week_day_name(target_date)
        birth_weekday = self.week_day_name(birth_date)
        days_to_birthday = self.days_until_birthday(birth_date, target_date)

        zodiac = self.get_zodiac_sign(int(birth_date.split('.')[0]), int(birth_date.split('.')[1]))
        element = self.get_zodiac_element(zodiac)
        quality = self.get_zodiac_quality(zodiac)

        gender_text = "Мужчина" if self.gender == 'M' else "Женщина"

        # 11. Собираем все данные в словарь
        data = {
            "name": self.name,
            "gender_text": gender_text,
            "gender_display": gender_text,
            "birth_date": birth_date,
            "birth_weekday": birth_weekday,
            "birth_time": self.birth_time or "не указано",
            "birth_place": self.birth_place or "не указано",
            "target_date": target_date,
            "target_weekday": week_day,
            "age": age,
            "zodiac_sign": zodiac,
            "zodiac_element": element,
            "zodiac_quality": quality,
            "life_path_number": life_path,
            "personal_day_number": personal_day,
            "personal_year": personal_year,
            "matrix_center": matrix['sz'],
            "transit_arcan": transit_arcan,
            "moon_illumination": moon_illumination,
            "lunar_day": lunar_day,
            "days_to_birthday": days_to_birthday,
            "is_birthday_today": days_to_birthday == 0,
            "birthday_note": "СЕГОДНЯ ДЕНЬ РОЖДЕНИЯ! 🎂" if days_to_birthday == 0 else f"До дня рождения: {days_to_birthday} дней",
            "birthday_congrats": "ОБЯЗАТЕЛЬНО поздравь с Днем Рождения и дай мощный энергетический заряд!" if days_to_birthday == 0 else "",
            # Натальные данные
            "sun_sign": sun['sign'] if sun else "не известно",
            "moon_sign": moon['sign'] if moon else "не известно",
            "ascendant": ascendant,
            "planets_list": planets_str,
            "aspects_list": aspects_str,
            "cusps_list": cusps_str,
            # Транзитные данные
            "transit_moon_sign": transit_moon_sign,
            "transit_moon_house": transit_moon_house,
            "transit_moon_aspects": transit_moon_aspects,
            "retrograde_planets": retrograde_planets,
            "transit_aspects": "\n".join(
                f"- {a['transit_planet']} {a['aspect']} {a['natal_planet']} (орбис: {a['orb']:.2f}°)" for a in transit_aspects
            ) if transit_aspects else "Нет значимых транзитных аспектов",
            # Местоимения
            "pronoun": "он" if self.gender == 'M' else "она",
            "possessive": "его" if self.gender == 'M' else "её",
        }

        return data