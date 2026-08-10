import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import pytz

from kerykeion import AstrologicalSubject
try:
    from kerykeion.transit import TransitSubject
except ImportError:
    # Если модуль transit не существует, используем другой способ
    TransitSubject = None
from .astrology_calculator import AstrologyCalculator
from .timezone_coords import TIMEZONE_COORDS
from .base_calculator import BaseCalculator

logger = logging.getLogger(__name__)

class TransitHoroscopeCalculator(BaseCalculator):
    """
    Класс для расчёта гороскопа на сегодня с учётом транзитов.
    """

    def __init__(self, user_data: Dict[str, Any]):
        self.user_data = user_data
        self.birth_date = user_data.get('birth_date')
        self.birth_time = user_data.get('birth_time')
        self.birth_place = user_data.get('birth_place')
        self.name = user_data.get('name', 'Человек')
        self.gender = user_data.get('gender', 'M')
        self.timezone_offset = user_data.get('timezone_offset', 3)  # по умолчанию UTC+3

        # Получаем координаты для таймзоны
        tz_info = TIMEZONE_COORDS.get(self.timezone_offset, TIMEZONE_COORDS[3])
        self.transit_lat = tz_info["lat"]
        self.transit_lng = tz_info["lng"]
        self.transit_tz_str = tz_info["tz"]

        # Натальный калькулятор
        self.natal_calc = AstrologyCalculator(user_data)
        self.natal_subject = None
        self.transit_subject = None
        self.aspects = []

    def _get_natal_subject(self) -> AstrologicalSubject:
        """Создаёт натальный субъект"""
        if self.natal_subject is None:
            # Получаем координаты и часовой пояс через единый метод
            lat, lng, tz_str = self.natal_calc._get_coordinates_and_timezone()
            year, month, day, hour, minute = self.natal_calc._parse_birth_datetime()

            self.natal_subject = AstrologicalSubject(
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
        return self.natal_subject

    def _get_transit_subject(self):
        """Создаёт транзитный субъект на текущий момент в таймзоне пользователя"""
        if self.transit_subject is None:
            natal = self._get_natal_subject()
            tz = pytz.timezone(self.transit_tz_str)
            now = datetime.now(tz)

            if TransitSubject is not None:
                self.transit_subject = TransitSubject(
                    natal,
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

    def _get_transit_aspects(self):
        if self.aspects:
            return self.aspects

        natal = self._get_natal_subject()
        transit = self._get_transit_subject()

        # Извлекаем планеты из натального субъекта
        natal_planets = []
        if hasattr(natal, 'planets') and natal.planets:
            for p in natal.planets:
                natal_planets.append({"name": p.name, "degree": p.position})
        else:
            # Если нет атрибута planets, пробуем через модель
            model = natal.model() if callable(natal.model) else natal.model
            data = model.dict() if hasattr(model, 'dict') else model.__dict__
            planet_keys = ['sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter', 'saturn',
                           'uranus', 'neptune', 'pluto', 'chiron', 'mean_lilith', 'true_lilith']
            for key in planet_keys:
                if key in data:
                    obj = data[key]
                    if isinstance(obj, dict):
                        if 'position' in obj:
                            natal_planets.append({"name": key.capitalize(), "degree": obj['position']})
                    else:
                        if hasattr(obj, 'position'):
                            natal_planets.append({"name": key.capitalize(), "degree": obj.position})

        # Извлекаем транзитные планеты
        transit_planets = []
        if hasattr(transit, 'planets') and transit.planets:
            for p in transit.planets:
                transit_planets.append({"name": p.name, "degree": p.position})
        else:
            model = transit.model() if callable(transit.model) else transit.model
            data = model.dict() if hasattr(model, 'dict') else model.__dict__
            planet_keys = ['sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter', 'saturn',
                           'uranus', 'neptune', 'pluto', 'chiron', 'mean_lilith', 'true_lilith']
            for key in planet_keys:
                if key in data:
                    obj = data[key]
                    if isinstance(obj, dict):
                        if 'position' in obj:
                            transit_planets.append({"name": key.capitalize(), "degree": obj['position']})
                    else:
                        if hasattr(obj, 'position'):
                            transit_planets.append({"name": key.capitalize(), "degree": obj.position})

        logger.info(f"Натальные планеты для транзитов: {len(natal_planets)}")
        logger.info(f"Транзитные планеты: {len(transit_planets)}")

        # Вычисляем аспекты вручную
        aspects = self._get_transit_aspects_manual(natal_planets, transit_planets)
        logger.info(f"✅ Транзитные аспекты (ручной расчёт): {len(aspects)}")

        self.aspects = aspects
        return aspects

    def calculate(self) -> Dict[str, Any]:
        """
        Выполняет все расчёты и возвращает данные для промпта.
        """
        # 1. Получаем натальный субъект
        natal = self._get_natal_subject()

        # 2. Получаем транзитный субъект и транзитные аспекты
        transit = self._get_transit_subject()
        transit_aspects = self._get_transit_aspects()

        # 3. Получаем натальные астрологические данные (планеты, дома, аспекты, Солнце, Луна, Асцендент)
        natal_chart_data = self._get_natal_chart_data()

        # 4. Базовые нумерологические и астрономические расчёты
        birth_date = self.birth_date or "01.01.2000"
        target_date = datetime.now(pytz.timezone(self.transit_tz_str)).strftime("%d.%m.%Y")

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

        # 5. Форматируем транзитные аспекты в строку
        transit_aspects_str = ""
        if transit_aspects:
            transit_aspects_str = "\n".join(
                f"- {a['transit_planet']} {a['aspect']} {a['natal_planet']} (орбис: {a['orb']:.2f}°)" for a in
                transit_aspects
            )

        gender_text = "Мужчина" if self.gender == 'M' else "Женщина"

        # 6. Собираем все данные в один словарь
        data = {
            "name": self.name,
            "gender_text": gender_text,
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
            "transit_aspects": transit_aspects_str,
        }

        # 7. Добавляем натальные астрологические данные (солнце, луна, асцендент, планеты, аспекты)
        data.update(natal_chart_data)

        return data

    def _get_natal_chart_data(self) -> Dict[str, Any]:
        """Извлекает из натального субъекта планеты, дома и аспекты (натальные)"""
        subject = self._get_natal_subject()

        # Планеты
        planets = []
        if hasattr(subject, 'planets') and subject.planets:
            for p in subject.planets:
                planets.append({
                    "name": p.name,
                    "sign": p.sign,
                    "degree": p.position,
                    "house": p.house,
                })
        elif hasattr(subject, 'model'):
            model = subject.model() if callable(subject.model) else subject.model
            data = model.dict() if hasattr(model, 'dict') else model.__dict__
            planet_keys = ['sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter', 'saturn',
                           'uranus', 'neptune', 'pluto', 'chiron', 'mean_lilith', 'true_lilith',
                           'ceres', 'pallas', 'juno', 'vesta', 'eris', 'sedna', 'haumea', 'makemake',
                           'mean_north_lunar_node', 'true_north_lunar_node',
                           'mean_south_lunar_node', 'true_south_lunar_node']
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
        logger.info(f"Натальные планеты: {len(planets)} планет")

        # Дома
        houses = []
        house_keys = ['first_house', 'second_house', 'third_house', 'fourth_house',
                      'fifth_house', 'sixth_house', 'seventh_house', 'eighth_house',
                      'ninth_house', 'tenth_house', 'eleventh_house', 'twelfth_house']
        if hasattr(subject, 'houses') and subject.houses:
            for h in subject.houses:
                houses.append({"number": h.number, "sign": h.sign, "degree": h.position})
        else:
            model = subject.model() if callable(subject.model) else subject.model
            data = model.dict() if hasattr(model, 'dict') else model.__dict__
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
        logger.info(f"Натальные дома: {len(houses)} домов")

        # Аспекты натальной карты (внутренние)
        aspects = []
        try:
            from kerykeion import NatalAspects
            aspects_obj = NatalAspects(subject)
            if hasattr(aspects_obj, 'relevant_aspects'):
                for a in aspects_obj.relevant_aspects:
                    orb = getattr(a, 'orb', getattr(a, 'orbis', 0.0))
                    aspects.append({
                        "p1": getattr(a, 'p1_name', 'unknown'),
                        "p2": getattr(a, 'p2_name', 'unknown'),
                        "aspect": getattr(a, 'aspect', 'unknown'),
                        "orb": orb,
                    })
                logger.info(f"Натальные аспекты: {len(aspects)} аспектов")
        except Exception as e:
            logger.warning(f"Не удалось получить натальные аспекты: {e}")

        # Определяем Солнце, Луну, Асцендент
        sun_sign = None
        moon_sign = None
        ascendant = None
        for p in planets:
            if p['name'].lower() == 'sun':
                sun_sign = p['sign']
            elif p['name'].lower() == 'moon':
                moon_sign = p['sign']
        if houses:
            ascendant = houses[0]['sign']

        planets_str = "\n".join(
            f"- {p['name']} в {p['sign']} ({p['degree']:.2f}°) в {p['house']} доме"
            for p in planets
        )

        aspects_str = ""
        if aspects:
            aspects_str = "\n".join(
                f"- {a['p1']} {a['aspect']} {a['p2']} (орбис: {a['orb']:.2f}°)" for a in aspects
            )

        return {
            "sun_sign": sun_sign or "не известно",
            "moon_sign": moon_sign or "не известно",
            "ascendant": ascendant or "не известно",
            "planets_list": planets_str,
            "aspects_list": aspects_str,
        }

    def _get_transit_aspects_manual(self, natal_planets: list, transit_planets: list) -> list:
        """
        Ручной расчёт аспектов между натальными и транзитными планетами.
        """
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