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

    def _create_subject(self, data: Dict[str, Any]) -> AstrologicalSubject:
        """Создаёт AstrologicalSubject из данных пользователя"""
        birth_date = data.get('birth_date')
        birth_time = data.get('birth_time', '00:00')
        birth_place = data.get('birth_place', 'Москва, Россия')

        # Получаем координаты и часовой пояс через AstrologyCalculator
        calc = AstrologyCalculator(data)
        year, month, day, hour, minute = calc._parse_birth_datetime()
        city, country = calc._parse_birth_place()
        coords = calc._get_coordinates(city, country)
        tz_str = calc._get_timezone(coords['lat'], coords['lng'])

        return AstrologicalSubject(
            name=data.get('name', 'Человек'),
            year=year,
            month=month,
            day=day,
            hour=hour,
            minute=minute,
            lat=coords['lat'],
            lng=coords['lng'],
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
        """Получает синастрические аспекты с fallback"""
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

        # Если ничего не сработало, возвращаем пустой список
        logger.warning(
            "Не удалось получить синастрические аспекты. Анализ будет основан на нумерологии и натальных картах.")
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

            "aspects_synastry_list": synastry_str,
            "compatibility_number": self.compatibility_number,
            "compatibility_arcan": self.compatibility_arcan,
            "target_date": self.target_date,
            "lunar_day": self.lunar_day,
        }