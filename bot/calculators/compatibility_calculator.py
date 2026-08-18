#bot\calculators\compatibility_calculator.py
import logging
from typing import Dict, Any, List
from datetime import datetime
from kerykeion import AstrologicalSubject, AspectsFactory, NatalAspects
from .base_calculator import BaseCalculator
from .astrology_calculator import AstrologyCalculator
from .astrology_utils import calculate_aspects_manual, extract_planets_from_subject

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
        planets1 = extract_planets_from_subject(self.subject1)
        planets2 = extract_planets_from_subject(self.subject2)
        self.synastry_aspects = calculate_aspects_manual(planets1, planets2)

    def get_synastry_aspects(self, direction: str = 'both') -> List[Dict[str, Any]]:
        """
        Возвращает синастрические аспекты между планетами двух людей.
        direction: 'a_to_b', 'b_to_a', 'both'
        """
        if not hasattr(self, '_synastry_aspects'):
            self._synastry_aspects = self._calculate_synastry_aspects()
        if direction == 'both':
            return self._synastry_aspects
        elif direction == 'a_to_b':
            return [a for a in self._synastry_aspects if a['direction'] == 'a_to_b']
        else:  # b_to_a
            return [a for a in self._synastry_aspects if a['direction'] == 'b_to_a']

    def _calculate_synastry_aspects(self) -> List[Dict[str, Any]]:
        """Расчёт синастрических аспектов (A→B и B→A)."""
        planets1 = extract_planets_from_subject(self.subject1)
        planets2 = extract_planets_from_subject(self.subject2)
        aspects = []

        # Определяем орбы (можно взять из констант)
        ASPECT_ORBS = {'conjunction': 8, 'opposition': 8, 'trine': 6,
                       'square': 6, 'sextile': 5, 'quincunx': 4,
                       'semisextile': 3, 'sesquiquadrate': 4,
                       'quintile': 3, 'biquintile': 3}

        for p1 in planets1:
            for p2 in planets2:
                # A→B
                aspect_type, orb = get_aspect_type(p1['degree'], p2['degree'], ASPECT_ORBS)
                if aspect_type:
                    weight1 = self.PLANET_WEIGHTS.get(p1['name'], 5)
                    weight2 = self.PLANET_WEIGHTS.get(p2['name'], 5)
                    aspect_weight = {'conjunction': 10, 'opposition': 9, 'trine': 8,
                                     'square': 7, 'sextile': 6, 'quincunx': 5,
                                     'semisextile': 4, 'sesquiquadrate': 4,
                                     'quintile': 3, 'biquintile': 3}.get(aspect_type, 5)
                    score = calculate_score(weight1, weight2, aspect_weight, orb)
                    confidence = calculate_confidence(score, orb)
                    themes = self._get_aspect_themes(p1['name'], p2['name'], aspect_type)
                    aspects.append({
                        "person_a_planet": p1['name'],
                        "person_b_planet": p2['name'],
                        "aspect": aspect_type,
                        "orb": round(orb, 2),
                        "exact_angle": round(orb, 2),
                        "a_planet_sign": p1['sign'],
                        "a_planet_house": p1['house'],
                        "b_planet_sign": p2['sign'],
                        "b_planet_house": p2['house'],
                        "score": round(score, 2),
                        "confidence": round(confidence, 2),
                        "themes": themes,
                        "direction": "a_to_b"
                    })
                # B→A (аспекты симметричны, но для полноты можно добавить)
                # Поскольку аспект тот же, но направление другое, можно просто дублировать с пометкой b_to_a
                # Или оставить только один, но в ТЗ просят оба направления.
                # Чтобы не дублировать, сделаем отдельный список для b_to_a (те же планеты, но наоборот)
                aspect_type2, orb2 = get_aspect_type(p2['degree'], p1['degree'], ASPECT_ORBS)
                if aspect_type2:
                    # Используем те же веса, что и выше
                    score2 = calculate_score(weight2, weight1, aspect_weight, orb2)
                    confidence2 = calculate_confidence(score2, orb2)
                    themes2 = self._get_aspect_themes(p2['name'], p1['name'], aspect_type2)
                    aspects.append({
                        "person_a_planet": p2['name'],  # меняем местами
                        "person_b_planet": p1['name'],
                        "aspect": aspect_type2,
                        "orb": round(orb2, 2),
                        "exact_angle": round(orb2, 2),
                        "a_planet_sign": p2['sign'],
                        "a_planet_house": p2['house'],
                        "b_planet_sign": p1['sign'],
                        "b_planet_house": p1['house'],
                        "score": round(score2, 2),
                        "confidence": round(confidence2, 2),
                        "themes": themes2,
                        "direction": "b_to_a"
                    })
        return aspects

    def get_planets_in_houses(self) -> Dict[str, List[Dict]]:
        """Возвращает планеты каждого человека в домах другого."""
        # Получаем дома из карт
        houses1 = self.chart1.get('houses', [])
        houses2 = self.chart2.get('houses', [])
        planets1 = self._extract_planets(self.subject1)
        planets2 = self._extract_planets(self.subject2)

        def planets_in_houses(planets, houses):
            result = []
            for p in planets:
                # Определяем дом по долготе
                house = get_house_for_longitude(p['degree'], houses)
                if house:
                    result.append({
                        "planet": p['name'],
                        "house": house,
                        "sign": p['sign'],
                        "degree": p['degree']
                    })
            return result

        return {
            "a_in_b_houses": planets_in_houses(planets1, houses2),
            "b_in_a_houses": planets_in_houses(planets2, houses1)
        }

    def get_synastry_angle_aspects(self) -> List[Dict[str, Any]]:
        """Аспекты планет одного человека к углам другого."""
        angles1 = self.chart1.get('angles', {})
        angles2 = self.chart2.get('angles', {})
        if not angles1 or not angles2:
            # Получить углы через get_angles
            from .astrology_utils import get_angles
            angles1 = get_angles(self.subject1)
            angles2 = get_angles(self.subject2)

        planets1 = self._extract_planets(self.subject1)
        planets2 = self._extract_planets(self.subject2)
        ASPECT_ORBS = {'conjunction': 8, 'opposition': 8, 'trine': 6,
                       'square': 6, 'sextile': 5}
        aspects = []

        for p1 in planets1:
            for angle_name, angle_deg in angles2.items():
                if angle_deg == 0:
                    continue
                aspect_type, orb = get_aspect_type(p1['degree'], angle_deg, ASPECT_ORBS)
                if aspect_type:
                    weight = self.PLANET_WEIGHTS.get(p1['name'], 5)
                    angle_weight = 10
                    aspect_weight = {'conjunction': 10, 'opposition': 9, 'trine': 8,
                                     'square': 7, 'sextile': 6}.get(aspect_type, 5)
                    score = calculate_score(weight, angle_weight, aspect_weight, orb)
                    confidence = calculate_confidence(score, orb)
                    aspects.append({
                        "person_planet": p1['name'],
                        "person_sign": p1['sign'],
                        "person_house": p1['house'],
                        "other_angle": angle_name,
                        "aspect": aspect_type,
                        "orb": round(orb, 2),
                        "score": round(score, 2),
                        "confidence": round(confidence, 2),
                        "direction": "a_to_b_angles"
                    })
        # Аналогично для планет 2 к углам 1
        for p2 in planets2:
            for angle_name, angle_deg in angles1.items():
                if angle_deg == 0:
                    continue
                aspect_type, orb = get_aspect_type(p2['degree'], angle_deg, ASPECT_ORBS)
                if aspect_type:
                    weight = self.PLANET_WEIGHTS.get(p2['name'], 5)
                    angle_weight = 10
                    aspect_weight = {'conjunction': 10, 'opposition': 9, 'trine': 8,
                                     'square': 7, 'sextile': 6}.get(aspect_type, 5)
                    score = calculate_score(weight, angle_weight, aspect_weight, orb)
                    confidence = calculate_confidence(score, orb)
                    aspects.append({
                        "person_planet": p2['name'],
                        "person_sign": p2['sign'],
                        "person_house": p2['house'],
                        "other_angle": angle_name,
                        "aspect": aspect_type,
                        "orb": round(orb, 2),
                        "score": round(score, 2),
                        "confidence": round(confidence, 2),
                        "direction": "b_to_a_angles"
                    })
        return aspects

    def get_mutual_receptions(self) -> List[Dict[str, Any]]:
        """Определяет взаимные рецепции между планетами двух людей."""
        # Упрощённо: если планета A находится в знаке, которым управляет планета B, и наоборот.
        # Используем управителей знаков
        sign_rulers = {
            'Aries': 'Mars', 'Taurus': 'Venus', 'Gemini': 'Mercury',
            'Cancer': 'Moon', 'Leo': 'Sun', 'Virgo': 'Mercury',
            'Libra': 'Venus', 'Scorpio': 'Pluto', 'Sagittarius': 'Jupiter',
            'Capricorn': 'Saturn', 'Aquarius': 'Uranus', 'Pisces': 'Neptune'
        }
        receptions = []
        planets1 = self._extract_planets(self.subject1)
        planets2 = self._extract_planets(self.subject2)

        for p1 in planets1:
            for p2 in planets2:
                # Проверяем рецепцию: p1 в знаке, которым управляет p2, и p2 в знаке, которым управляет p1
                if p2['name'] == sign_rulers.get(p1['sign'], '') and p1['name'] == sign_rulers.get(p2['sign'], ''):
                    receptions.append({
                        "planet_a": p1['name'],
                        "planet_b": p2['name'],
                        "theme": "mutual_reception",
                        "strength": 8.0  # можно вычислить по весам
                    })
        return receptions

    def get_compatibility_themes(self) -> Dict[str, Any]:
        """Агрегирует темы из всех синастрических данных."""
        themes = {}
        # Из аспектов
        for asp in self.get_synastry_aspects():
            for theme in asp.get('themes', []):
                if theme not in themes:
                    themes[theme] = {"evidence": [], "score": 0, "count": 0}
                themes[theme]["evidence"].append({
                    "type": "synastry",
                    "source": f"{asp['person_a_planet']} {asp['aspect']} {asp['person_b_planet']}",
                    "score": asp['score'],
                    "confidence": asp['confidence']
                })
                themes[theme]["count"] += 1
                themes[theme]["score"] += asp['score']
        # Из планет в домах
        houses_data = self.get_planets_in_houses()
        for item in houses_data['a_in_b_houses']:
            theme = f"planet_{item['planet']}_in_house_{item['house']}"
            if theme not in themes:
                themes[theme] = {"evidence": [], "score": 0, "count": 0}
            themes[theme]["evidence"].append({
                "type": "planet_in_house",
                "source": f"{item['planet']} in {item['house']} house",
                "score": 6.0,
                "confidence": 0.8
            })
            themes[theme]["count"] += 1
            themes[theme]["score"] += 6.0
        # Усредняем
        for theme in themes:
            themes[theme]["score"] = round(themes[theme]["score"] / themes[theme]["count"], 2)
            themes[theme]["confidence"] = round(
                sum(e['confidence'] for e in themes[theme]["evidence"]) / themes[theme]["count"], 2
            )
            themes[theme]["evidence"] = themes[theme]["evidence"][:5]
        return themes

    def get_full_synastry_data(self) -> Dict[str, Any]:
        """Возвращает все данные для нового промпта совместимости."""
        return {
            "synastry_aspects_a_to_b": [a for a in self.get_synastry_aspects() if a['direction'] == 'a_to_b'],
            "synastry_aspects_b_to_a": [a for a in self.get_synastry_aspects() if a['direction'] == 'b_to_a'],
            "planets_in_houses": self.get_planets_in_houses(),
            "synastry_angle_aspects": self.get_synastry_angle_aspects(),
            "mutual_receptions": self.get_mutual_receptions(),
            "compatibility_themes": self.get_compatibility_themes(),
        }

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