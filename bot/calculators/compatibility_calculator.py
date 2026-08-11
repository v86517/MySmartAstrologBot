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

        # Создаём натальные субъекты
        self.subject1 = self._create_subject(person1_data)
        self.subject2 = self._create_subject(person2_data)

        # Получаем натальные аспекты для каждого
        self.aspects1 = self._get_natal_aspects(self.subject1)
        self.aspects2 = self._get_natal_aspects(self.subject2)

        # Получаем синастрические аспекты
        self.synastry_aspects = self._get_synastry_aspects(self.subject1, self.subject2)

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

    def _get_natal_aspects(self, subject: AstrologicalSubject) -> List[Dict]:
        """Извлекает натальные аспекты"""
        aspects = []
        try:
            natal_aspects = NatalAspects(subject)
            if hasattr(natal_aspects, 'relevant_aspects'):
                for a in natal_aspects.relevant_aspects:
                    orb = getattr(a, 'orb', getattr(a, 'orbis', 0.0))
                    aspects.append({
                        "p1": getattr(a, 'p1_name', 'unknown'),
                        "p2": getattr(a, 'p2_name', 'unknown'),
                        "aspect": getattr(a, 'aspect', 'unknown'),
                        "orb": orb,
                    })
            logger.info(f"Натальные аспекты для {subject.name}: {len(aspects)}")
        except Exception as e:
            logger.warning(f"Не удалось получить натальные аспекты: {e}")
        return aspects

    def _get_synastry_aspects(self, subj1: AstrologicalSubject, subj2: AstrologicalSubject) -> List[Dict]:
        """Получает синастрические аспекты с fallback на ручной расчёт"""
        aspects = []

        # Способ 1: dual_chart_aspects
        try:
            synastry = AspectsFactory.dual_chart_aspects(subj1, subj2)
            if hasattr(synastry, 'aspects'):
                for a in synastry.aspects:
                    orb = getattr(a, 'orbit', getattr(a, 'orb', getattr(a, 'orbis', 0.0)))
                    aspects.append({
                        "p1": getattr(a, 'p1_name', 'unknown'),
                        "p2": getattr(a, 'p2_name', 'unknown'),
                        "aspect": getattr(a, 'aspect', 'unknown'),
                        "orb": orb,
                    })
                logger.info(f"Синастрические аспекты (dual_chart_aspects): {len(aspects)}")
                return aspects
        except Exception as e:
            logger.warning(f"dual_chart_aspects не сработал: {e}")

        # Способ 2: synastry_aspects (резерв)
        try:
            synastry = AspectsFactory.synastry_aspects(subj1, subj2)
            if hasattr(synastry, 'aspects'):
                for a in synastry.aspects:
                    orb = getattr(a, 'orbit', getattr(a, 'orb', getattr(a, 'orbis', 0.0)))
                    aspects.append({
                        "p1": getattr(a, 'p1_name', 'unknown'),
                        "p2": getattr(a, 'p2_name', 'unknown'),
                        "aspect": getattr(a, 'aspect', 'unknown'),
                        "orb": orb,
                    })
                logger.info(f"Синастрические аспекты (synastry_aspects): {len(aspects)}")
                return aspects
        except Exception as e:
            logger.warning(f"synastry_aspects не сработал: {e}")

        # Способ 3: ручной расчёт
        aspects = self._get_synastry_aspects_manual(subj1, subj2)
        if aspects:
            logger.info(f"Синастрические аспекты (ручной расчёт): {len(aspects)}")
            return aspects

        logger.warning("Не удалось получить синастрические аспекты ни одним способом.")
        return aspects

    def _format_planets(self, subject: AstrologicalSubject) -> str:
        """Форматирует список планет для промпта"""
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
                           'uranus', 'neptune', 'pluto', 'chiron', 'mean_lilith', 'true_lilith']
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
        if not planets:
            return "неизвестно"
        return "\n".join(
            f"  • {p['name']} в {p['sign']} ({p['degree']:.2f}°) в {p['house']} доме"
            for p in planets
        )

    def _format_aspects(self, aspects: List[Dict]) -> str:
        """Форматирует список аспектов для промпта"""
        if not aspects:
            return "неизвестно"
        return "\n".join(
            f"  • {a['p1']} {a['aspect']} {a['p2']} (орбис: {a['orb']:.2f}°)" for a in aspects
        )

    def get_prompt_data(self) -> Dict[str, Any]:
        """Возвращает данные для подстановки в промпт"""
        p1 = self.person1_data
        p2 = self.person2_data

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

        planets_str1 = self._format_planets(self.subject1)
        planets_str2 = self._format_planets(self.subject2)
        aspects_str1 = self._format_aspects(self.aspects1)
        aspects_str2 = self._format_aspects(self.aspects2)
        synastry_str = self._format_aspects(self.synastry_aspects)

        # ---- Новые данные для каждого человека (Солнце, Луна, Асцендент, куспиды) ----
        # Человек 1
        sun1 = next((p for p in self.subject1.planets if p.name == "Sun"), None)
        moon1 = next((p for p in self.subject1.planets if p.name == "Moon"), None)
        asc1 = self.subject1.first_house.sign if self.subject1.first_house else "не известно"
        cusps1 = []
        for i in range(1, 13):
            house = getattr(self.subject1, f"{i}_house", None)
            if house:
                cusps1.append(f"{i}-й дом: {house.sign} ({house.position:.2f}°)")
        cusps1_str = "\n".join(cusps1) if cusps1 else "не известно"

        # Человек 2
        sun2 = next((p for p in self.subject2.planets if p.name == "Sun"), None)
        moon2 = next((p for p in self.subject2.planets if p.name == "Moon"), None)
        asc2 = self.subject2.first_house.sign if self.subject2.first_house else "не известно"
        cusps2 = []
        for i in range(1, 13):
            house = getattr(self.subject2, f"{i}_house", None)
            if house:
                cusps2.append(f"{i}-й дом: {house.sign} ({house.position:.2f}°)")
        cusps2_str = "\n".join(cusps2) if cusps2 else "не известно"

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
            "p1_sun_sign": sun1.sign if sun1 else "не известно",
            "p1_moon_sign": moon1.sign if moon1 else "не известно",
            "p1_ascendant": asc1,
            "p1_cusps_list": cusps1_str,

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
            "p2_sun_sign": sun2.sign if sun2 else "не известно",
            "p2_moon_sign": moon2.sign if moon2 else "не известно",
            "p2_ascendant": asc2,
            "p2_cusps_list": cusps2_str,

            "aspects_synastry_list": synastry_str,
            "compatibility_number": self.compatibility_number,
            "compatibility_arcan": self.compatibility_arcan,
            "target_date": self.target_date,
            "target_weekday": self.target_weekday,
            "lunar_day": self.lunar_day,
            "moon_illumination": self.moon_illumination,
        }

    def _get_synastry_aspects_manual(self, subj1: AstrologicalSubject, subj2: AstrologicalSubject) -> List[Dict]:
        """
        Ручной расчёт синастрических аспектов между планетами двух людей.
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