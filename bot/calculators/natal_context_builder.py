import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

from kerykeion import AstrologicalSubject, AspectsFactory

logger = logging.getLogger(__name__)


class NatalContextBuilder:
    """
    Строит текстовый контекст натальной карты для передачи в LLM.
    Использует только натальные данные из Kerykeion, без транзитов и прогнозов.
    """

    # ========== MAPPING ==========
    SIGN_MAP = {
        'Ari': 'Овен', 'Tau': 'Телец', 'Gem': 'Близнецы',
        'Can': 'Рак', 'Leo': 'Лев', 'Vir': 'Дева',
        'Lib': 'Весы', 'Sco': 'Скорпион', 'Sag': 'Стрелец',
        'Cap': 'Козерог', 'Aqu': 'Водолей', 'Pis': 'Рыбы'
    }

    PLANET_MAP = {
        'Sun': 'Солнце', 'Moon': 'Луна', 'Mercury': 'Меркурий',
        'Venus': 'Венера', 'Mars': 'Марс', 'Jupiter': 'Юпитер',
        'Saturn': 'Сатурн', 'Uranus': 'Уран', 'Neptune': 'Нептун',
        'Pluto': 'Плутон',
        'True_North_Lunar_Node': 'Северный узел',
        'True_South_Lunar_Node': 'Южный узел',
        'Chiron': 'Хирон',
        'True_Lilith': 'Лилит'
    }

    TECH_NAME_TO_PLANET_MAP = {
        'sun': 'Sun',
        'moon': 'Moon',
        'mercury': 'Mercury',
        'venus': 'Venus',
        'mars': 'Mars',
        'jupiter': 'Jupiter',
        'saturn': 'Saturn',
        'uranus': 'Uranus',
        'neptune': 'Neptune',
        'pluto': 'Pluto',
        'true_north_lunar_node': 'True_North_Lunar_Node',
        'true_south_lunar_node': 'True_South_Lunar_Node',
        'chiron': 'Chiron',
        'true_lilith': 'True_Lilith'
    }

    ANGLE_NAME_MAP = {
        'Ascendant': 'ASC',
        'Midheaven': 'MC',
        'MediumCoeli': 'MC',
        'Descendant': 'DSC',
        'ImumCoeli': 'IC',
    }

    ASPECT_MAP = {
        'conjunction': 'соединение',
        'opposition': 'оппозиция',
        'trine': 'тригон',
        'square': 'квадрат',
        'sextile': 'секстиль'
    }

    HOUSE_KEY_MAP = {
        'first_house': '1 дом',
        'second_house': '2 дом',
        'third_house': '3 дом',
        'fourth_house': '4 дом',
        'fifth_house': '5 дом',
        'sixth_house': '6 дом',
        'seventh_house': '7 дом',
        'eighth_house': '8 дом',
        'ninth_house': '9 дом',
        'tenth_house': '10 дом',
        'eleventh_house': '11 дом',
        'twelfth_house': '12 дом'
    }

    HOUSE_NUMBER_MAP = {
        'First_House': '1 дом',
        'Second_House': '2 дом',
        'Third_House': '3 дом',
        'Fourth_House': '4 дом',
        'Fifth_House': '5 дом',
        'Sixth_House': '6 дом',
        'Seventh_House': '7 дом',
        'Eighth_House': '8 дом',
        'Ninth_House': '9 дом',
        'Tenth_House': '10 дом',
        'Eleventh_House': '11 дом',
        'Twelfth_House': '12 дом'
    }

    PLANET_ASPECT_ORBS = {
        'conjunction': 8.0,
        'opposition': 8.0,
        'trine': 7.0,
        'square': 7.0,
        'sextile': 5.0
    }

    EXTRA_ASPECT_ORBS = {
        'conjunction': 5.0,
        'opposition': 5.0,
        'trine': 5.0,
        'square': 5.0,
        'sextile': 5.0
    }

    LILITH_ASPECT_ORBS = {
        'conjunction': 3.0,
        'opposition': 3.0,
        'trine': 3.0,
        'square': 3.0,
        'sextile': 3.0
    }

    ALLOWED_ASPECTS = {'conjunction', 'opposition', 'trine', 'square', 'sextile'}

    # Дополнительные объекты для аспектов (канонические имена)
    EXTRA_OBJECTS = {'True_North_Lunar_Node', 'True_South_Lunar_Node',
                     'Chiron', 'True_Lilith', 'ASC', 'MC', 'DSC', 'IC'}

    def __init__(self, subject: AstrologicalSubject, lang: str = 'ru'):
        self.subject = subject
        self.lang = lang
        self._planets = []
        self._houses = []
        self._aspects = {'planetary': [], 'extra': []}
        self._angles = {}
        self._elements = {}
        self._qualities = {}
        self._lunar_phase = None

    def build(self) -> str:
        self._extract_data()
        self._validate()
        return self._format()

    def _extract_data(self):
        model = self.subject.model() if callable(self.subject.model) else self.subject.model
        data = model.dict() if hasattr(model, 'dict') else model.__dict__

        # --- ПЛАНЕТЫ ---
        planet_keys = [
            'sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter', 'saturn',
            'uranus', 'neptune', 'pluto',
            'true_north_lunar_node', 'true_south_lunar_node',
            'chiron', 'true_lilith'
        ]
        self._planets = []
        for key in planet_keys:
            if key in data:
                obj = data[key]
                mapped_name = self.TECH_NAME_TO_PLANET_MAP.get(key, key.capitalize())
                if obj is None:
                    logger.warning(f"Объект {key} отсутствует (None). Пропускаем.")
                    continue
                if isinstance(obj, dict):
                    if 'sign' in obj and 'position' in obj:
                        self._planets.append({
                            'name': mapped_name,
                            'sign': obj.get('sign'),
                            'position': obj.get('position'),
                            'abs_pos': obj.get('abs_pos'),
                            'house': obj.get('house'),
                            'retrograde': obj.get('retrograde', False),
                        })
                else:
                    if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                        self._planets.append({
                            'name': mapped_name,
                            'sign': getattr(obj, 'sign'),
                            'position': getattr(obj, 'position'),
                            'abs_pos': getattr(obj, 'abs_pos'),
                            'house': getattr(obj, 'house'),
                            'retrograde': getattr(obj, 'retrograde', False),
                        })

        # --- ДОМА ---
        self._houses = []
        house_keys = [
            'first_house', 'second_house', 'third_house', 'fourth_house',
            'fifth_house', 'sixth_house', 'seventh_house', 'eighth_house',
            'ninth_house', 'tenth_house', 'eleventh_house', 'twelfth_house'
        ]
        for key in house_keys:
            if key in data:
                obj = data[key]
                if isinstance(obj, dict):
                    if 'sign' in obj and 'position' in obj:
                        self._houses.append({
                            'key': key,
                            'sign': obj.get('sign'),
                            'position': obj.get('position'),
                            'abs_pos': obj.get('abs_pos'),
                        })
                else:
                    if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                        self._houses.append({
                            'key': key,
                            'sign': getattr(obj, 'sign'),
                            'position': getattr(obj, 'position'),
                            'abs_pos': getattr(obj, 'abs_pos'),
                        })

        # --- РАСЧЁТ РАСПРЕДЕЛЕНИЙ ВРУЧНУЮ ---
        self._calculate_distributions()

        # --- ЛУННАЯ ФАЗА ИЗ DATA ---
        if 'lunar_phase' in data and isinstance(data['lunar_phase'], dict):
            phase = data['lunar_phase']
            self._lunar_phase = {
                'name': phase.get('moon_phase_name'),
                'angle': phase.get('degrees_between_s_m')
            }

        # --- АСПЕКТЫ ---
        aspects_raw = []
        try:
            factory = AspectsFactory.single_chart_aspects(self.subject)
            if factory and hasattr(factory, 'aspects'):
                aspects_raw = factory.aspects
        except Exception as e:
            logger.warning(f"AspectsFactory не сработал: {e}, пробуем NatalAspects")
            try:
                from kerykeion import NatalAspects
                na = NatalAspects(self.subject)
                if hasattr(na, 'relevant_aspects'):
                    aspects_raw = na.relevant_aspects
            except Exception as e2:
                logger.warning(f"NatalAspects тоже не сработал: {e2}")

        self._aspects = self._filter_aspects(aspects_raw)

        # --- УГЛЫ ---
        def _extract_angle(obj):
            if obj is None:
                return None
            if isinstance(obj, dict):
                return {'sign': obj.get('sign'), 'position': obj.get('position'), 'abs_pos': obj.get('abs_pos')}
            if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                return {'sign': getattr(obj, 'sign'), 'position': getattr(obj, 'position'), 'abs_pos': getattr(obj, 'abs_pos')}
            return None

        asc = _extract_angle(data.get('ascendant'))
        mc = _extract_angle(data.get('medium_coeli'))
        dsc = _extract_angle(data.get('descendant'))
        ic = _extract_angle(data.get('imum_coeli'))

        if not asc and hasattr(self.subject, 'ascendant'):
            asc = _extract_angle(self.subject.ascendant)
        if not mc and hasattr(self.subject, 'midheaven'):
            mc = _extract_angle(self.subject.midheaven)
        if not dsc and hasattr(self.subject, 'descendant'):
            dsc = _extract_angle(self.subject.descendant)
        if not ic and hasattr(self.subject, 'imum_coeli'):
            ic = _extract_angle(self.subject.imum_coeli)

        if mc is None:
            logger.warning("MC отсутствует. Пробуем взять куспид 10-го дома.")
            tenth_house = next((h for h in self._houses if h['key'] == 'tenth_house'), None)
            if tenth_house:
                mc = {'sign': tenth_house['sign'], 'position': tenth_house['position'], 'abs_pos': tenth_house['abs_pos']}
                logger.info(f"MC взят из куспида 10-го дома: {mc['sign']} {mc['position']:.2f}°")
            else:
                logger.warning("Куспид 10-го дома не найден.")

        self._angles = {
            'ASC': asc,
            'MC': mc,
            'DSC': dsc,
            'IC': ic
        }

    def _calculate_distributions(self):
        """Рассчитывает распределение стихий и качеств на основе планет."""
        if not self._planets:
            return

        elements = {'Огонь': 0, 'Земля': 0, 'Воздух': 0, 'Вода': 0}
        qualities = {'Кардинальный': 0, 'Фиксированный': 0, 'Мутабельный': 0}

        sign_element = {
            'Овен': 'Огонь', 'Лев': 'Огонь', 'Стрелец': 'Огонь',
            'Телец': 'Земля', 'Дева': 'Земля', 'Козерог': 'Земля',
            'Близнецы': 'Воздух', 'Весы': 'Воздух', 'Водолей': 'Воздух',
            'Рак': 'Вода', 'Скорпион': 'Вода', 'Рыбы': 'Вода'
        }
        sign_quality = {
            'Овен': 'Кардинальный', 'Рак': 'Кардинальный', 'Весы': 'Кардинальный', 'Козерог': 'Кардинальный',
            'Телец': 'Фиксированный', 'Лев': 'Фиксированный', 'Скорпион': 'Фиксированный', 'Водолей': 'Фиксированный',
            'Близнецы': 'Мутабельный', 'Дева': 'Мутабельный', 'Стрелец': 'Мутабельный', 'Рыбы': 'Мутабельный'
        }

        main_planets = ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                        'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']
        for p in self._planets:
            if p['name'] not in main_planets:
                continue
            sign = p['sign']
            sign_name = self.SIGN_MAP.get(sign, sign)
            if sign_name in sign_element:
                elements[sign_element[sign_name]] += 1
            if sign_name in sign_quality:
                qualities[sign_quality[sign_name]] += 1

        # Нормализуем в проценты
        total_elem = sum(elements.values())
        if total_elem > 0:
            for k in elements:
                elements[k] = int(round((elements[k] / total_elem) * 100))
            diff = 100 - sum(elements.values())
            if diff != 0:
                first_key = next(iter(elements))
                elements[first_key] += diff

        total_qual = sum(qualities.values())
        if total_qual > 0:
            for k in qualities:
                qualities[k] = int(round((qualities[k] / total_qual) * 100))
            diff = 100 - sum(qualities.values())
            if diff != 0:
                first_key = next(iter(qualities))
                qualities[first_key] += diff

        self._elements = elements
        self._qualities = qualities

    def _filter_aspects(self, raw_aspects) -> Dict[str, List]:
        planetary = []
        extra = []

        seen_planetary = set()
        seen_extra = set()

        main_planets = {'Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                        'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto'}

        # Определим функцию нормализации имён углов
        def normalize_angle(name):
            return self.ANGLE_NAME_MAP.get(name, name)

        for a in raw_aspects:
            p1 = getattr(a, 'p1_name', None)
            p2 = getattr(a, 'p2_name', None)
            aspect = getattr(a, 'aspect', None)
            orbit = getattr(a, 'orbit', getattr(a, 'orb', None))
            movement = getattr(a, 'aspect_movement', None)

            if not p1 or not p2 or not aspect or orbit is None:
                continue

            if aspect.lower() not in self.ALLOWED_ASPECTS:
                continue

            # Нормализуем имена углов
            p1_norm = normalize_angle(p1)
            p2_norm = normalize_angle(p2)

            names = sorted([p1_norm, p2_norm])
            p1_in_main = p1_norm in main_planets
            p2_in_main = p2_norm in main_planets
            p1_in_extra = p1_norm in self.EXTRA_OBJECTS
            p2_in_extra = p2_norm in self.EXTRA_OBJECTS

            if p1_in_main and p2_in_main:
                key = (names[0], names[1], aspect.lower())
                if key in seen_planetary:
                    continue
                seen_planetary.add(key)
                max_orb = self.PLANET_ASPECT_ORBS.get(aspect.lower(), 8.0)
                if orbit <= max_orb:
                    planetary.append({
                        'p1': p1_norm,
                        'p2': p2_norm,
                        'aspect': aspect,
                        'orb': orbit,
                        'movement': movement
                    })
            elif (p1_in_main and p2_in_extra) or (p2_in_main and p1_in_extra):
                if p1_in_main:
                    planet, extra_obj = p1_norm, p2_norm
                else:
                    planet, extra_obj = p2_norm, p1_norm
                key = (planet, extra_obj, aspect.lower())
                if key in seen_extra:
                    continue
                seen_extra.add(key)
                if extra_obj == 'True_Lilith':
                    max_orb = self.LILITH_ASPECT_ORBS.get(aspect.lower(), 3.0)
                else:
                    max_orb = self.EXTRA_ASPECT_ORBS.get(aspect.lower(), 5.0)
                if orbit <= max_orb:
                    extra.append({
                        'p1': planet,
                        'p2': extra_obj,
                        'aspect': aspect,
                        'orb': orbit,
                        'movement': movement
                    })

        return {'planetary': planetary, 'extra': extra}

    def _validate(self):
        checks = {
            'chart_type': True,
            'zodiac_type': True,
            'house_system': True,
            'birth_date': True,
            'birth_time': True,
            'timezone': True,
            'latitude': True,
            'longitude': True,
            'ASC': self._angles.get('ASC') is not None,
            'MC': self._angles.get('MC') is not None,
            'DSC': self._angles.get('DSC') is not None,
            'IC': self._angles.get('IC') is not None,
            'Sun': any(p['name'] == 'Sun' for p in self._planets),
            'Moon': any(p['name'] == 'Moon' for p in self._planets),
            'Mercury': any(p['name'] == 'Mercury' for p in self._planets),
            'Venus': any(p['name'] == 'Venus' for p in self._planets),
            'Mars': any(p['name'] == 'Mars' for p in self._planets),
            'Jupiter': any(p['name'] == 'Jupiter' for p in self._planets),
            'Saturn': any(p['name'] == 'Saturn' for p in self._planets),
            'Uranus': any(p['name'] == 'Uranus' for p in self._planets),
            'Neptune': any(p['name'] == 'Neptune' for p in self._planets),
            'Pluto': any(p['name'] == 'Pluto' for p in self._planets),
            'North_Node': any(p['name'] == 'True_North_Lunar_Node' for p in self._planets),
            'South_Node': any(p['name'] == 'True_South_Lunar_Node' for p in self._planets),
            'Chiron': any(p['name'] == 'Chiron' for p in self._planets),
            # True_Lilith – опционально, не проверяем
            'Mean_Lilith_absent': not any(p['name'] == 'Mean_Lilith' for p in self._planets),
            '12_houses': len(self._houses) == 12,
            'elements_present': bool(self._elements),
            'qualities_present': bool(self._qualities),
            'lunar_phase_present': self._lunar_phase is not None,
            'no_transits': True,
            'no_json': True,
        }
        for key, passed in checks.items():
            if not passed:
                logger.warning(f"Валидация: {key} отсутствует или невалиден. Проверьте данные Kerykeion.")

    def _format(self) -> str:
        lines = []
        lines.append("=== NATAL CHART ===")
        lines.append("")

        # Метаданные
        model = self.subject.model() if callable(self.subject.model) else self.subject.model
        data = model.dict() if hasattr(model, 'dict') else model.__dict__
        zodiac = data.get('zodiac_type', 'Tropical')
        house_system = data.get('house_system', 'Placidus')
        lines.append("Тип карты: Натальная")
        lines.append(f"Зодиак: {zodiac}")
        lines.append(f"Система домов: {house_system}")
        lines.append("Перспектива: Geocentric")
        lines.append("")

        # Рождение
        year = getattr(self.subject, 'year', None)
        month = getattr(self.subject, 'month', None)
        day = getattr(self.subject, 'day', None)
        hour = getattr(self.subject, 'hour', None)
        minute = getattr(self.subject, 'minute', None)
        lat = getattr(self.subject, 'lat', None)
        lng = getattr(self.subject, 'lng', None)
        tz_str = getattr(self.subject, 'tz_str', None)

        lines.append("Рождение:")
        lines.append(f"Дата: {day:02d}.{month:02d}.{year}" if all([day, month, year]) else "Дата: не указана")
        lines.append(f"Время: {hour:02d}:{minute:02d}" if hour is not None and minute is not None else "Время: не указано")
        lines.append(f"Координаты: {lat:.4f}° N, {lng:.4f}° E" if lat and lng else "Координаты: не указаны")
        lines.append(f"Часовой пояс: {tz_str}" if tz_str else "Часовой пояс: не указан")
        lines.append("")

        # Углы
        lines.append("Углы:")
        for angle_name in ['ASC', 'MC', 'DSC', 'IC']:
            angle = self._angles.get(angle_name)
            if angle:
                sign = self.SIGN_MAP.get(angle.get('sign'), angle.get('sign'))
                pos = angle.get('position', 0.0)
                lines.append(f"{angle_name}: {sign} {pos:.2f}°")
            else:
                lines.append(f"{angle_name}: —")
        lines.append("")

        # Планеты
        planet_order = ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                        'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']
        lines.append("Планеты:")
        for name in planet_order:
            planet = next((p for p in self._planets if p['name'] == name), None)
            if planet:
                lines.append(self._format_planet(planet))
        lines.append("")

        # Дополнительные точки
        extra_order = ['True_North_Lunar_Node', 'True_South_Lunar_Node', 'Chiron', 'True_Lilith']
        lines.append("Лунные узлы и дополнительные точки:")
        for name in extra_order:
            point = next((p for p in self._planets if p['name'] == name), None)
            if point:
                lines.append(self._format_planet(point))
        lines.append("")

        # Куспиды домов
        lines.append("Куспиды домов:")
        house_order = ['first_house', 'second_house', 'third_house', 'fourth_house',
                       'fifth_house', 'sixth_house', 'seventh_house', 'eighth_house',
                       'ninth_house', 'tenth_house', 'eleventh_house', 'twelfth_house']
        for key in house_order:
            house = next((h for h in self._houses if h['key'] == key), None)
            if house:
                sign = self.SIGN_MAP.get(house['sign'], house['sign'])
                pos = house['position']
                house_display = self.HOUSE_KEY_MAP.get(key, key)
                lines.append(f"{house_display}: {sign} {pos:.2f}°")
            else:
                house_display = self.HOUSE_KEY_MAP.get(key, key)
                lines.append(f"{house_display}: —")
        lines.append("")

        # Аспекты планет
        planetary_aspects = self._aspects.get('planetary', [])
        if planetary_aspects:
            lines.append("Аспекты планет:")
            for a in planetary_aspects:
                lines.append(self._format_aspect(a))
            lines.append("")
        else:
            lines.append("Аспекты планет: нет")
            lines.append("")

        # Аспекты к дополнительным точкам и углам
        extra_aspects = self._aspects.get('extra', [])
        if extra_aspects:
            lines.append("Аспекты к дополнительным точкам и углам:")
            for a in extra_aspects:
                lines.append(self._format_aspect(a))
            lines.append("")
        else:
            lines.append("Аспекты к дополнительным точкам и углам: нет")
            lines.append("")

        # Распределение стихий
        if self._elements:
            lines.append("Распределение стихий:")
            for elem, value in self._elements.items():
                lines.append(f"{elem}: {value}%")
            lines.append("")
        else:
            lines.append("Распределение стихий: не рассчитано")
            lines.append("")

        # Распределение качеств
        if self._qualities:
            lines.append("Распределение качеств:")
            for qual, value in self._qualities.items():
                lines.append(f"{qual}: {value}%")
            lines.append("")
        else:
            lines.append("Распределение качеств: не рассчитано")
            lines.append("")

        # Лунная фаза
        if self._lunar_phase and self._lunar_phase.get('name') and self._lunar_phase.get('angle') is not None:
            lines.append("Лунная фаза:")
            lines.append(f"{self._lunar_phase['name']}")
            lines.append(f"Угол Солнце–Луна: {self._lunar_phase['angle']:.2f}°")
            lines.append("")
        else:
            lines.append("Лунная фаза: не рассчитана")
            lines.append("")

        return "\n".join(lines)

    def _format_planet(self, planet: Dict) -> str:
        name = self.PLANET_MAP.get(planet['name'], planet['name'])
        sign = self.SIGN_MAP.get(planet['sign'], planet['sign'])
        pos = planet['position']
        house = planet['house']
        retro = planet['retrograde']

        if house is None or house == 0:
            house_display = "неизвестный дом"
        elif isinstance(house, int):
            house_display = f"{house} дом"
        elif isinstance(house, str):
            if house in self.HOUSE_NUMBER_MAP:
                house_display = self.HOUSE_NUMBER_MAP[house]
            elif house.lower() in self.HOUSE_KEY_MAP:
                house_display = self.HOUSE_KEY_MAP[house.lower()]
            else:
                house_display = house
        else:
            house_display = "неизвестный дом"

        if retro:
            return f"{name}: {sign} {pos:.2f}°, {house_display}, ретроградный"
        else:
            return f"{name}: {sign} {pos:.2f}°, {house_display}"

    def _format_aspect(self, aspect: Dict) -> str:
        p1 = self.PLANET_MAP.get(aspect['p1'], aspect['p1'])
        p2 = self.PLANET_MAP.get(aspect['p2'], aspect['p2'])
        aspect_name = self.ASPECT_MAP.get(aspect['aspect'].lower(), aspect['aspect'])
        orb = aspect['orb']
        movement = aspect.get('movement')
        if movement:
            phase = "сходящийся" if 'applying' in movement.lower() else "расходящийся" if 'separating' in movement.lower() else ""
            if phase:
                return f"{p1} — {aspect_name} — {p2}, орб {orb:.2f}°, {phase}"
        return f"{p1} — {aspect_name} — {p2}, орб {orb:.2f}°"