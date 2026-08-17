#bot\calculators\compatibility_calculator.py
import logging
from typing import Dict, Any, List
from datetime import datetime
from kerykeion import AstrologicalSubject, AspectsFactory, NatalAspects
from .base_calculator import BaseCalculator
from .astrology_calculator import AstrologyCalculator

logger = logging.getLogger(__name__)


class CompatibilityCalculator(BaseCalculator):
    """
    Класс для расчёта совместимости двух людей с использованием астрологических данных.
    """

    def __init__(self, person1_data: Dict[str, Any], person2_data: Dict[str, Any]):
        self.person1_data = person1_data
        self.person2_data = person2_data
        self.target_date = datetime.now().strftime("%d.%m.%Y")

        # Создаём астрологические калькуляторы для каждого человека
        self.calc1 = AstrologyCalculator(person1_data)
        self.calc2 = AstrologyCalculator(person2_data)

        # Получаем натальные карты (словари с планетами, домами, аспектами)
        self.chart1 = self.calc1._calculate_chart()
        self.chart2 = self.calc2._calculate_chart()

        # Создаём субъекты для синастрии
        self.subject1 = self._create_subject(person1_data)
        self.subject2 = self._create_subject(person2_data)

        # Базовые нумерологические расчёты
        self.life_path1 = self.calculate_life_path_number(person1_data['birth_date'])
        self.life_path2 = self.calculate_life_path_number(person2_data['birth_date'])
        self.compatibility_number = self.calculate_compatibility_number(
            person1_data['birth_date'], person2_data['birth_date']
        )
        self.compatibility_arcan = self.calculate_compatibility_arcan(
            person1_data['birth_date'], person2_data['birth_date']
        )
        self.lunar_day = self.get_lunar_day(self.target_date)
        self.moon_illumination = self.moon_phase_percent(self.target_date)
        self.target_weekday = self.week_day_name(self.target_date)

        # Получаем синастрические аспекты (ручной расчёт)
        self.synastry_aspects = self._get_synastry_aspects_manual(self.subject1, self.subject2)

    def _create_subject(self, data: Dict[str, Any]) -> AstrologicalSubject:
        """Создаёт AstrologicalSubject из данных пользователя"""
        birth_date = data.get('birth_date')
        birth_time = data.get('birth_time', '00:00')
        birth_place = data.get('birth_place', 'Москва, Россия')

        calc = AstrologyCalculator(data)
        year, month, day, hour, minute = calc._parse_birth_datetime()
        city, country = calc._parse_birth_place()
        lat, lng, tz_str = calc._get_coordinates_and_timezone()

        return AstrologicalSubject(
            name=data.get('name', 'Человек'),
            year=year,
            month=month,
            day=day,
            hour=hour,
            minute=minute,
            lat=lat,
            lng=lng,
            tz_str=tz_str,
        )

    def _format_planets(self, chart: dict) -> str:
        """Форматирует список планет из натальной карты"""
        planets = chart.get('planets', [])
        if not planets:
            return "не известно"
        lines = []
        for p in planets:
            lines.append(f"  • {p['name']} в {p['sign']} ({p['degree']:.2f}°) в {p['house']} доме")
        return "\n".join(lines)

    def _format_aspects(self, chart: dict) -> str:
        """Форматирует список аспектов из натальной карты"""
        aspects = chart.get('aspects', [])
        if not aspects:
            return "не известно"
        lines = []
        for a in aspects:
            lines.append(f"  • {a['p1']} {a['aspect']} {a['p2']} (орбис: {a['orb']:.2f}°)")
        return "\n".join(lines)

    def _format_cusps(self, chart: dict) -> str:
        """Форматирует куспиды домов из натальной карты"""
        houses = chart.get('houses', [])
        if not houses:
            return "не известно"
        lines = []
        for h in houses:
            lines.append(f"  • {h['number']}-й дом: {h['sign']} ({h['degree']:.2f}°)")
        return "\n".join(lines)

    def get_prompt_data(self) -> Dict[str, Any]:
        """Возвращает данные для подстановки в промпт"""
        p1 = self.person1_data
        p2 = self.person2_data

        # Извлекаем знаки, элементы, качества
        zodiac1 = self.get_zodiac_sign(
            int(p1['birth_date'].split('.')[0]),
            int(p1['birth_date'].split('.')[1])
        )
        zodiac2 = self.get_zodiac_sign(
            int(p2['birth_date'].split('.')[0]),
            int(p2['birth_date'].split('.')[1])
        )

        element1 = self.get_zodiac_element(zodiac1)
        element2 = self.get_zodiac_element(zodiac2)
        quality1 = self.get_zodiac_quality(zodiac1)
        quality2 = self.get_zodiac_quality(zodiac2)

        # Форматируем планеты, аспекты, куспиды из натальных карт
        planets_str1 = self._format_planets(self.chart1)
        planets_str2 = self._format_planets(self.chart2)
        aspects_str1 = self._format_aspects(self.chart1)
        aspects_str2 = self._format_aspects(self.chart2)
        cusps_str1 = self._format_cusps(self.chart1)
        cusps_str2 = self._format_cusps(self.chart2)

        # Синастрические аспекты
        synastry_str = self._format_synastry_aspects()

        # Солнце, Луна, Асцендент из карт
        sun1 = next((p for p in self.chart1.get('planets', []) if p['name'].lower() == 'sun'), None)
        moon1 = next((p for p in self.chart1.get('planets', []) if p['name'].lower() == 'moon'), None)
        asc1 = self.chart1.get('houses', [{}])[0].get('sign', 'не известно') if self.chart1.get('houses') else 'не известно'

        sun2 = next((p for p in self.chart2.get('planets', []) if p['name'].lower() == 'sun'), None)
        moon2 = next((p for p in self.chart2.get('planets', []) if p['name'].lower() == 'moon'), None)
        asc2 = self.chart2.get('houses', [{}])[0].get('sign', 'не известно') if self.chart2.get('houses') else 'не известно'

        return {
            "p1_name": p1.get('name', 'Не указано'),
            "p1_gender_text": "Мужчина" if p1.get('gender') == 'M' else "Женщина",
            "p1_birth_date": p1.get('birth_date', 'не указана'),
            "p1_birth_time": p1.get('birth_time', 'не указано'),
            "p1_birth_place": p1.get('birth_place', 'не указано'),
            "p1_zodiac": zodiac1,
            "p1_element": element1,
            "p1_quality": quality1,
            "p1_life_path": self.life_path1,
            "p1_planets_list": planets_str1,
            "p1_aspects_list": aspects_str1,
            "p1_cusps_list": cusps_str1,
            "p1_sun_sign": sun1['sign'] if sun1 else "не известно",
            "p1_moon_sign": moon1['sign'] if moon1 else "не известно",
            "p1_ascendant": asc1,

            "p2_name": p2.get('name', 'Не указано'),
            "p2_gender_text": "Мужчина" if p2.get('gender') == 'M' else "Женщина",
            "p2_birth_date": p2.get('birth_date', 'не указана'),
            "p2_birth_time": p2.get('birth_time', 'не указано'),
            "p2_birth_place": p2.get('birth_place', 'не указано'),
            "p2_zodiac": zodiac2,
            "p2_element": element2,
            "p2_quality": quality2,
            "p2_life_path": self.life_path2,
            "p2_planets_list": planets_str2,
            "p2_aspects_list": aspects_str2,
            "p2_cusps_list": cusps_str2,
            "p2_sun_sign": sun2['sign'] if sun2 else "не известно",
            "p2_moon_sign": moon2['sign'] if moon2 else "не известно",
            "p2_ascendant": asc2,

            "aspects_synastry_list": synastry_str,
            "compatibility_number": self.compatibility_number,
            "compatibility_arcan": self.compatibility_arcan,
            "target_date": self.target_date,
            "target_weekday": self.target_weekday,
            "lunar_day": self.lunar_day,
            "moon_illumination": self.moon_illumination,
        }

    def _format_synastry_aspects(self) -> str:
        """Форматирует синастрические аспекты в строку"""
        if not self.synastry_aspects:
            return "не известно"
        lines = []
        for a in self.synastry_aspects:
            lines.append(f"  • {a['p1']} {a['aspect']} {a['p2']} (орбис: {a['orb']:.2f}°)")
        return "\n".join(lines)

    def _get_synastry_aspects_manual(self, subj1: AstrologicalSubject, subj2: AstrologicalSubject) -> List[Dict]:
        """
        Ручной расчёт синастрических аспектов между планетами двух людей.
        Используется, если библиотечные методы не работают.
        """
        planets1 = self._extract_planets(subj1)
        planets2 = self._extract_planets(subj2)

        if not planets1 or not planets2:
            logger.warning("Не удалось извлечь планеты для ручного расчёта синастрии")
            return []

        aspects = []
        aspect_types = {
            'conjunction': 8,
            'opposition': 8,
            'trine': 6,
            'square': 6,
            'sextile': 5,
        }

        for p1 in planets1:
            for p2 in planets2:
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

        logger.info(f"Синастрические аспекты (ручной расчёт): {len(aspects)}")
        return aspects

    def _extract_planets(self, subject: AstrologicalSubject) -> List[Dict]:
        """Извлекает список планет с их градусами из субъекта"""
        planets = []
        if hasattr(subject, 'planets') and subject.planets:
            for p in subject.planets:
                planets.append({"name": p.name, "degree": p.position})
        elif hasattr(subject, 'model'):
            model = subject.model() if callable(subject.model) else subject.model
            data = model.dict() if hasattr(model, 'dict') else model.__dict__
            planet_keys = ['sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter', 'saturn',
                           'uranus', 'neptune', 'pluto', 'chiron', 'mean_lilith', 'true_lilith']
            for key in planet_keys:
                if key in data:
                    obj = data[key]
                    if isinstance(obj, dict):
                        if 'position' in obj:
                            planets.append({"name": key.capitalize(), "degree": obj['position']})
                    else:
                        if hasattr(obj, 'position'):
                            planets.append({"name": key.capitalize(), "degree": obj.position})
        return planets