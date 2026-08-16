import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
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
    """

    # FIXED: добавлены средние скорости планет (градусов в день)
    AVERAGE_SPEEDS = {
        'Sun': 0.9856,
        'Moon': 13.1764,
        'Mercury': 1.383,
        'Venus': 1.2,
        'Mars': 0.524,
        'Jupiter': 0.083,
        'Saturn': 0.033,
        'Uranus': 0.012,
        'Neptune': 0.006,
        'Pluto': 0.004,
        'Chiron': 0.02,
        'Mean_Lilith': 0.1,
        'True_North_Lunar_Node': -0.05,
        'True_South_Lunar_Node': 0.05,
    }

    def __init__(self, user_data: Dict[str, Any], lang: str = 'ru', natal_calc: Optional[AstrologyCalculator] = None):
        self.user_data = user_data
        self.lang = lang
        self.birth_date = user_data.get('birth_date')
        self.birth_time = user_data.get('birth_time')
        self.birth_place = user_data.get('birth_place')
        self.name = user_data.get('name', 'Человек')
        self.gender = user_data.get('gender', 'M')
        self.timezone_offset = user_data.get('timezone_offset', 3)

        tz_info = TIMEZONE_COORDS.get(self.timezone_offset, TIMEZONE_COORDS[3])
        self.transit_lat = tz_info["lat"]
        self.transit_lng = tz_info["lng"]
        self.transit_tz_str = tz_info["tz"]

        if natal_calc is not None:
            self.natal_calc = natal_calc
        else:
            self.natal_calc = AstrologyCalculator(user_data)
        self.natal_chart = None
        self.transit_subject = None
        self.transit_chart = None
        self.transit_houses = None  # для хранения куспидов домов транзита

    def _get_natal_chart(self) -> Dict[str, Any]:
        if self.natal_chart is None:
            self.natal_chart = self.natal_calc._calculate_chart()
        return self.natal_chart

    def _get_transit_subject(self) -> AstrologicalSubject:
        if self.transit_subject is None:
            tz = pytz.timezone(self.transit_tz_str)
            now = datetime.now(tz)
            lat, lng, tz_str = self.natal_calc._get_coordinates_and_timezone()

            if TransitSubject is not None:
                natal_subject = self.natal_calc._get_natal_subject()
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
        if self.transit_chart is None:
            subject = self._get_transit_subject()
            model = subject.model() if callable(subject.model) else subject.model
            if hasattr(model, 'dict'):
                data = model.dict()
            elif hasattr(model, 'model_dump'):
                data = model.model_dump()
            else:
                data = model.__dict__

            # ---- Извлечение куспидов домов транзита ----
            house_keys = [
                'first_house', 'second_house', 'third_house', 'fourth_house',
                'fifth_house', 'sixth_house', 'seventh_house', 'eighth_house',
                'ninth_house', 'tenth_house', 'eleventh_house', 'twelfth_house'
            ]
            transit_houses = []
            for i, key in enumerate(house_keys, 1):
                if key in data:
                    obj = data[key]
                    if isinstance(obj, dict):
                        if 'position' in obj:
                            degree = obj.get('position', 0.0)
                            transit_houses.append({"number": i, "degree": degree})
                    else:
                        if hasattr(obj, 'position'):
                            degree = getattr(obj, 'position', 0.0)
                            transit_houses.append({"number": i, "degree": degree})
            self.transit_houses = transit_houses
            self.transit_chart = data
        return self.transit_chart

    def _get_transit_house_for_planet(self, longitude: float) -> int:
        """Определяет дом транзитной планеты по долготе и куспидам домов транзита."""
        if not self.transit_houses:
            return 0
        sorted_houses = sorted(self.transit_houses, key=lambda h: h['degree'])
        for i, h in enumerate(sorted_houses):
            next_house = sorted_houses[(i + 1) % len(sorted_houses)]
            start = h['degree']
            end = next_house['degree']
            if end < start:
                if longitude >= start or longitude < end:
                    return h['number']
            else:
                if start <= longitude < end:
                    return h['number']
        return 0


    def _extract_planets_from_chart(self, chart_data: Dict[str, Any]) -> List[Dict]:
        """Извлекает планеты из словаря карты (для транзитной карты)."""
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

    def _get_planet_speed(self, planet: str, is_transit: bool = False, transit_calc=None) -> float:
        try:
            if is_transit and transit_calc is not None:
                transit_subject = transit_calc._get_transit_subject()
                if hasattr(transit_subject, 'planets'):
                    for p in transit_subject.planets:
                        if p.name.lower() == planet.lower():
                            return p.speed if hasattr(p, 'speed') else self.AVERAGE_SPEEDS.get(planet, 0.0)
            else:
                subject = self.natal_calc._get_natal_subject()
                if hasattr(subject, 'planets'):
                    for p in subject.planets:
                        if p.name.lower() == planet.lower():
                            return p.speed if hasattr(p, 'speed') else self.AVERAGE_SPEEDS.get(planet, 0.0)
        except:
            pass
        # Fallback на среднюю скорость
        return self.AVERAGE_SPEEDS.get(planet, 0.0)

    def calculate(self) -> Dict[str, Any]:
        natal_chart = self._get_natal_chart()

        # Используем готовый список планет из натальной карты (уже извлечены в AstrologyCalculator)
        natal_planets = natal_chart.get('planets', [])
        natal_houses = natal_chart.get('houses', [])
        natal_aspects = natal_chart.get('aspects', [])

        # Для транзитной карты извлекаем планеты из модели
        transit_chart = self._get_transit_chart()
        transit_planets = self._extract_planets_from_chart(transit_chart)

        # Рассчитываем транзитные аспекты
        transit_aspects = self._get_transit_aspects_manual(natal_planets, transit_planets)

        # Логирование для отладки
        logger.info(f"Доступные натальные планеты: {[p['name'] for p in natal_planets]}")
        sun = next((p for p in natal_planets if p['name'].lower() == 'sun'), None)
        moon = next((p for p in natal_planets if p['name'].lower() == 'moon'), None)
        logger.info(f"Найден Sun: {sun['sign'] if sun else None}")
        logger.info(f"Найден Moon: {moon['sign'] if moon else None}")

        ascendant = natal_houses[0]['sign'] if natal_houses else 'не известно'

        # Формируем строки для подстановки в промпт
        planets_str = "\n".join(
            f"- {p['name']} в {p['sign']} ({p['degree']:.2f}°) в {p['house']} доме"
            for p in natal_planets
        ) if natal_planets else "не известно"

        aspects_str = "\n".join(
            f"- {a['p1']} {a['aspect']} {a['p2']} (орбис: {a['orb']:.2f}°)" for a in natal_aspects
        ) if natal_aspects else "не известно"

        cusps = []
        for i, h in enumerate(natal_houses, 1):
            cusps.append(f"{i}-й дом: {h['sign']} ({h['degree']:.2f}°)")
        cusps_str = "\n".join(cusps) if cusps else "не известно"

        transit_moon = next((p for p in transit_planets if p['name'].lower() == 'moon'), None)
        transit_moon_sign = transit_moon['sign'] if transit_moon else 'не известно'
        transit_moon_house = transit_moon['house'] if transit_moon else 'не известно'

        moon_aspects = []
        for a in transit_aspects:
            if 'Moon' in a['transit_planet'] or 'Moon' in a['natal_planet']:
                moon_aspects.append(
                    f"Transit {a['transit_planet']} → Natal {a['natal_planet']} → {a['aspect']} → {a['orb']:.2f}°"
                )
        transit_moon_aspects = "\n".join(moon_aspects) if moon_aspects else "Нет значимых аспектов"

        retrograde_list = [p['name'] for p in transit_planets if p.get('retrograde', False)]
        retrograde_planets = ", ".join(
            [f"{p} ℞" for p in retrograde_list]) if retrograde_list else "Нет ретроградных планет"

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

        # Локализованный пол
        if self.lang == 'en':
            gender_text = "Male" if self.gender == 'M' else "Female"
        else:
            gender_text = "Мужчина" if self.gender == 'M' else "Женщина"

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
            "sun_sign": sun['sign'] if sun else "не известно",
            "moon_sign": moon['sign'] if moon else "не известно",
            "ascendant": ascendant,
            "planets_list": planets_str,
            "aspects_list": aspects_str,
            "cusps_list": cusps_str,
            "transit_moon_sign": transit_moon_sign,
            "transit_moon_house": transit_moon_house,
            "transit_moon_aspects": transit_moon_aspects,
            "retrograde_planets": retrograde_planets,
            "transit_aspects": "\n".join(
                f"Transit {a['transit_planet']} → Natal {a['natal_planet']} → {a['aspect']} → {a['orb']:.2f}°" for a in
                transit_aspects
            ) if transit_aspects else "Нет значимых транзитных аспектов",
            "pronoun": "он" if self.gender == 'M' else "она",
            "possessive": "его" if self.gender == 'M' else "её",
        }

        return data