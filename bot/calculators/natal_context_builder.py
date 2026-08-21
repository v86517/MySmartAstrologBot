import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

from kerykeion import AstrologicalSubject, AspectsFactory

logger = logging.getLogger(__name__)


class NatalContextBuilder:
    """
    Строит текстовый контекст натальной карты для передачи в LLM.
    Использует только натальные данные из Kerykeion, без транзитов и прогнозов.
    Полностью соответствует ТЗ на доработку генератора.
    """

    # ========== MAPPING ==========
    # Знаки (код → полное название)
    SIGN_MAP = {
        'Ari': 'Овен', 'Tau': 'Телец', 'Gem': 'Близнецы',
        'Can': 'Рак', 'Leo': 'Лев', 'Vir': 'Дева',
        'Lib': 'Весы', 'Sco': 'Скорпион', 'Sag': 'Стрелец',
        'Cap': 'Козерог', 'Aqu': 'Водолей', 'Pis': 'Рыбы'
    }

    # Планеты (техническое имя → русское)
    PLANET_MAP = {
        'Sun': 'Солнце', 'Moon': 'Луна', 'Mercury': 'Меркурий',
        'Venus': 'Венера', 'Mars': 'Марс', 'Jupiter': 'Юпитер',
        'Saturn': 'Сатурн', 'Uranus': 'Уран', 'Neptune': 'Нептун',
        'Pluto': 'Плутон',
        'True_North_Lunar_Node': 'Северный узел',
        'True_South_Lunar_Node': 'Южный узел',
        'Chiron': 'Хирон',
        'True_Lilith': 'Лилит'
        # Mean_Lilith намеренно исключён
    }

    # Аспекты (техническое → русское)
    ASPECT_MAP = {
        'conjunction': 'соединение',
        'opposition': 'оппозиция',
        'trine': 'тригон',
        'square': 'квадрат',
        'sextile': 'секстиль'
    }

    # Дома (техническое → человекочитаемое)
    HOUSE_MAP = {
        'First_House': '1 дом', 'Second_House': '2 дом',
        'Third_House': '3 дом', 'Fourth_House': '4 дом',
        'Fifth_House': '5 дом', 'Sixth_House': '6 дом',
        'Seventh_House': '7 дом', 'Eighth_House': '8 дом',
        'Ninth_House': '9 дом', 'Tenth_House': '10 дом',
        'Eleventh_House': '11 дом', 'Twelfth_House': '12 дом'
    }

    # ========== ОРБЫ АСПЕКТОВ ==========
    # Основные планеты (планета ↔ планета)
    PLANET_ASPECT_ORBS = {
        'conjunction': 8.0,
        'opposition': 8.0,
        'trine': 7.0,
        'square': 7.0,
        'sextile': 5.0
    }

    # Дополнительные точки и углы (узлы, Хирон, Лилит, ASC, MC, DSC, IC)
    EXTRA_ASPECT_ORBS = {
        'conjunction': 5.0,
        'opposition': 5.0,
        'trine': 5.0,
        'square': 5.0,
        'sextile': 5.0
    }
    # Для True Lilith отдельный орб
    LILITH_ASPECT_ORBS = {
        'conjunction': 3.0,
        'opposition': 3.0,
        'trine': 3.0,
        'square': 3.0,
        'sextile': 3.0
    }

    # Разрешённые аспекты (только major)
    ALLOWED_ASPECTS = {'conjunction', 'opposition', 'trine', 'square', 'sextile'}

    def __init__(self, subject: AstrologicalSubject, lang: str = 'ru'):
        self.subject = subject
        self.lang = lang
        self._natal_data = None
        self._planets = []
        self._houses = []
        self._aspects = []
        self._angles = {}
        self._elements = {}
        self._qualities = {}
        self._lunar_phase = None

    def build(self) -> str:
        """Основной метод: возвращает текстовый контекст."""
        self._extract_data()
        self._validate()
        return self._format()

    def _extract_data(self):
        """Извлекает все необходимые данные из Kerykeion."""
        model = self.subject.model() if callable(self.subject.model) else self.subject.model
        data = model.dict() if hasattr(model, 'dict') else model.__dict__

        # --- Планеты (только нужные, исключая Mean Lilith) ---
        planet_keys = [
            'sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter', 'saturn',
            'uranus', 'neptune', 'pluto',
            'true_north_lunar_node', 'true_south_lunar_node',
            'chiron', 'true_lilith'
            # mean_lilith намеренно исключён
        ]
        self._planets = []
        for key in planet_keys:
            if key in data:
                obj = data[key]
                if isinstance(obj, dict):
                    if 'sign' in obj and 'position' in obj:
                        self._planets.append({
                            'name': key.capitalize(),
                            'sign': obj.get('sign'),
                            'position': obj.get('position'),
                            'abs_pos': obj.get('abs_pos'),
                            'house': obj.get('house'),
                            'retrograde': obj.get('retrograde', False),
                        })
                else:
                    if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                        self._planets.append({
                            'name': key.capitalize(),
                            'sign': getattr(obj, 'sign'),
                            'position': getattr(obj, 'position'),
                            'abs_pos': getattr(obj, 'abs_pos'),
                            'house': getattr(obj, 'house'),
                            'retrograde': getattr(obj, 'retrograde', False),
                        })

        # --- Дома (все 12) ---
        house_keys = [
            'first_house', 'second_house', 'third_house', 'fourth_house',
            'fifth_house', 'sixth_house', 'seventh_house', 'eighth_house',
            'ninth_house', 'tenth_house', 'eleventh_house', 'twelfth_house'
        ]
        self._houses = []
        for key in house_keys:
            if key in data:
                obj = data[key]
                if isinstance(obj, dict):
                    if 'sign' in obj and 'position' in obj:
                        self._houses.append({
                            'number': key.capitalize(),
                            'sign': obj.get('sign'),
                            'position': obj.get('position'),
                            'abs_pos': obj.get('abs_pos'),
                        })
                else:
                    if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                        self._houses.append({
                            'number': key.capitalize(),
                            'sign': getattr(obj, 'sign'),
                            'position': getattr(obj, 'position'),
                            'abs_pos': getattr(obj, 'abs_pos'),
                        })

        # --- Аспекты (через AspectsFactory с fallback на NatalAspects) ---
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

        # --- Фильтрация и классификация аспектов ---
        self._aspects = self._filter_aspects(aspects_raw)

        # --- Углы ---
        def _extract_angle(obj):
            if obj is None:
                return None
            if isinstance(obj, dict):
                return {'sign': obj.get('sign'), 'position': obj.get('position'), 'abs_pos': obj.get('abs_pos')}
            if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                return {'sign': getattr(obj, 'sign'), 'position': getattr(obj, 'position'), 'abs_pos': getattr(obj, 'abs_pos')}
            return None

        asc = _extract_angle(data.get('ascendant'))
        mc = _extract_angle(data.get('midheaven'))
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
            logger.warning("MC отсутствует в объекте Kerykeion. Проверьте данные.")

        self._angles = {
            'ASC': asc,
            'MC': mc,
            'DSC': dsc,
            'IC': ic
        }

        # --- Элементы и качества ---
        self._elements = data.get('element_distribution')
        self._qualities = data.get('quality_distribution')

        # --- Лунная фаза ---
        self._lunar_phase = None
        if hasattr(self.subject, 'lunar_phase'):
            phase = self.subject.lunar_phase
            if phase:
                self._lunar_phase = {
                    'name': getattr(phase, 'name', None),
                    'angle': getattr(phase, 'angle', None)
                }

    def _filter_aspects(self, raw_aspects) -> Dict[str, List]:
        """
        Фильтрует аспекты и разделяет на:
        - planetary: планета ↔ планета (только основные 10)
        - extra: планета ↔ узел/Хирон/Лилит/угол
        """
        planetary = []
        extra = []

        # Множества для дедупликации (сохраняем только уникальные комбинации)
        seen_planetary = set()
        seen_extra = set()

        # Основные 10 планет (их имена)
        main_planets = {'Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                        'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto'}

        # Дополнительные объекты
        extra_objects = {'True_North_Lunar_Node', 'True_South_Lunar_Node',
                         'Chiron', 'True_Lilith', 'ASC', 'MC', 'DSC', 'IC'}

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

            # Сортируем имена для нормализации
            names = sorted([p1, p2])

            # Определяем категорию аспекта
            p1_in_main = p1 in main_planets
            p2_in_main = p2 in main_planets
            p1_in_extra = p1 in extra_objects
            p2_in_extra = p2 in extra_objects

            # Планетарный аспект: оба объекта – основные планеты
            if p1_in_main and p2_in_main:
                key = (names[0], names[1], aspect.lower())
                if key in seen_planetary:
                    continue
                seen_planetary.add(key)
                # Проверяем орб
                max_orb = self.PLANET_ASPECT_ORBS.get(aspect.lower(), 8.0)
                if orbit <= max_orb:
                    planetary.append({
                        'p1': p1, 'p2': p2,
                        'aspect': aspect,
                        'orb': orbit,
                        'movement': movement
                    })
            # Аспект к дополнительным точкам/углам: один из объектов – основная планета, другой – extra
            elif (p1_in_main and p2_in_extra) or (p2_in_main and p1_in_extra):
                # Определяем, какая планета, а какая extra
                if p1_in_main:
                    planet, extra_obj = p1, p2
                else:
                    planet, extra_obj = p2, p1
                key = (planet, extra_obj, aspect.lower())
                if key in seen_extra:
                    continue
                seen_extra.add(key)
                # Выбираем орб в зависимости от extra_obj
                if extra_obj == 'True_Lilith':
                    max_orb = self.LILITH_ASPECT_ORBS.get(aspect.lower(), 3.0)
                else:
                    max_orb = self.EXTRA_ASPECT_ORBS.get(aspect.lower(), 5.0)
                if orbit <= max_orb:
                    extra.append({
                        'p1': planet, 'p2': extra_obj,
                        'aspect': aspect,
                        'orb': orbit,
                        'movement': movement
                    })
            # Игнорируем аспекты, где оба объекта – extra (узлы между собой и т.п.)

        return {'planetary': planetary, 'extra': extra}

    def _normalize_distribution(self, dist: Dict) -> Dict:
        """Нормализует распределение стихий/качеств до процентов (сумма = 100)."""
        if not dist:
            return {}
        total = sum(dist.values())
        if total == 0:
            return {k: 0 for k in dist}
        if total == 100:
            return {k: int(round(v)) for k, v in dist.items()}
        # Нормализуем
        normalized = {}
        for k, v in dist.items():
            if total > 0:
                normalized[k] = int(round((v / total) * 100))
        # Корректируем сумму до 100 (из-за округлений)
        diff = 100 - sum(normalized.values())
        if diff != 0:
            # Добавляем/убираем разницу к первому ключу
            first_key = next(iter(normalized))
            normalized[first_key] += diff
        return normalized

    def _validate(self):
        """Проверяет наличие обязательных данных, логирует предупреждения."""
        checks = {
            'chart_type': 'Natal',
            'zodiac_type': True,
            'house_system': True,
            'birth_date': True,  # в данных Kerykeion есть year, month, day
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
            'True_Lilith': any(p['name'] == 'True_Lilith' for p in self._planets),
            'Mean_Lilith_absent': not any(p['name'] == 'Mean_Lilith' for p in self._planets),
            '12_houses': len(self._houses) == 12,
            'elements_present': bool(self._elements),
            'qualities_present': bool(self._qualities),
            'lunar_phase_present': self._lunar_phase is not None,
            'no_transits': True,  # всегда true, т.к. мы не используем транзиты
            'no_json': True,
        }
        # Логируем предупреждения для отсутствующих данных
        for key, passed in checks.items():
            if not passed:
                logger.warning(f"Валидация: {key} отсутствует или невалиден. Проверьте данные Kerykeion.")

    def _format(self) -> str:
        """Формирует финальный текстовый блок."""
        lines = []
        lines.append("=== NATAL CHART ===")
        lines.append("")

        # 1. Метаданные
        model = self.subject.model() if callable(self.subject.model) else self.subject.model
        data = model.dict() if hasattr(model, 'dict') else model.__dict__
        zodiac = data.get('zodiac_type', 'Tropical')
        house_system = data.get('house_system', 'Placidus')
        lines.append("Тип карты: Натальная")
        lines.append(f"Зодиак: {zodiac}")
        lines.append(f"Система домов: {house_system}")
        lines.append("Перспектива: Geocentric")
        lines.append("")

        # 2. Рождение
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
        lines.append("Место: не указано")
        lines.append(f"Координаты: {lat:.4f}° N, {lng:.4f}° E" if lat and lng else "Координаты: не указаны")
        lines.append(f"Часовой пояс: {tz_str}" if tz_str else "Часовой пояс: не указан")
        lines.append("")

        # 3. Углы
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

        # 4. Планеты (в строгом порядке)
        planet_order = ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                        'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']
        lines.append("Планеты:")
        for name in planet_order:
            planet = next((p for p in self._planets if p['name'] == name), None)
            if planet:
                lines.append(self._format_planet(planet))
        lines.append("")

        # 5. Дополнительные точки
        extra_order = ['True_North_Lunar_Node', 'True_South_Lunar_Node', 'Chiron', 'True_Lilith']
        extra_names = ['Северный узел', 'Южный узел', 'Хирон', 'Лилит']
        lines.append("Лунные узлы и дополнительные точки:")
        for i, name in enumerate(extra_order):
            point = next((p for p in self._planets if p['name'] == name), None)
            if point:
                lines.append(self._format_planet(point, extra_names[i]))
        lines.append("")

        # 6. Куспиды домов
        lines.append("Куспиды домов:")
        house_numbers = ['First_House', 'Second_House', 'Third_House', 'Fourth_House',
                         'Fifth_House', 'Sixth_House', 'Seventh_House', 'Eighth_House',
                         'Ninth_House', 'Tenth_House', 'Eleventh_House', 'Twelfth_House']
        for i, key in enumerate(house_numbers, 1):
            house = next((h for h in self._houses if h['number'] == key), None)
            if house:
                sign = self.SIGN_MAP.get(house['sign'], house['sign'])
                pos = house['position']
                lines.append(f"{i} дом: {sign} {pos:.2f}°")
            else:
                lines.append(f"{i} дом: —")
        lines.append("")

        # 7. Аспекты планет
        planetary_aspects = self._aspects.get('planetary', [])
        if planetary_aspects:
            lines.append("Аспекты планет:")
            for a in planetary_aspects:
                lines.append(self._format_aspect(a))
            lines.append("")
        else:
            lines.append("Аспекты планет: нет")
            lines.append("")

        # 8. Аспекты к дополнительным точкам и углам
        extra_aspects = self._aspects.get('extra', [])
        if extra_aspects:
            lines.append("Аспекты к дополнительным точкам и углам:")
            for a in extra_aspects:
                lines.append(self._format_aspect(a))
            lines.append("")
        else:
            lines.append("Аспекты к дополнительным точкам и углам: нет")
            lines.append("")

        # 9. Распределение стихий
        if self._elements:
            norm_elements = self._normalize_distribution(self._elements)
            lines.append("Распределение стихий:")
            for elem, value in norm_elements.items():
                lines.append(f"{elem}: {value}%")
            lines.append("")
        else:
            lines.append("Распределение стихий: не рассчитано")
            lines.append("")

        # 10. Распределение качеств
        if self._qualities:
            norm_qualities = self._normalize_distribution(self._qualities)
            lines.append("Распределение качеств:")
            for qual, value in norm_qualities.items():
                lines.append(f"{qual}: {value}%")
            lines.append("")
        else:
            lines.append("Распределение качеств: не рассчитано")
            lines.append("")

        # 11. Лунная фаза
        if self._lunar_phase and self._lunar_phase.get('name') and self._lunar_phase.get('angle') is not None:
            lines.append("Лунная фаза:")
            lines.append(f"{self._lunar_phase['name']}")
            lines.append(f"Угол Солнце–Луна: {self._lunar_phase['angle']:.2f}°")
            lines.append("")
        else:
            lines.append("Лунная фаза: не рассчитана")
            lines.append("")

        return "\n".join(lines)

    def _format_planet(self, planet: Dict, custom_name: Optional[str] = None) -> str:
        """Форматирует одну планету в строку."""
        name = custom_name or self.PLANET_MAP.get(planet['name'], planet['name'])
        sign = self.SIGN_MAP.get(planet['sign'], planet['sign'])
        pos = planet['position']
        house = planet['house']
        retro = planet['retrograde']

        if retro:
            return f"{name}: {sign} {pos:.2f}°, {house} дом, ретроградный"
        else:
            return f"{name}: {sign} {pos:.2f}°, {house} дом"

    def _format_aspect(self, aspect: Dict) -> str:
        """Форматирует аспект в строку."""
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