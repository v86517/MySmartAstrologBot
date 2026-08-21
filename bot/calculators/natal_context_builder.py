import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

from kerykeion import AstrologicalSubject, AspectsFactory
from kerykeion.models import AspectModel

logger = logging.getLogger(__name__)


class NatalContextBuilder:
    """
    Строит текстовый контекст натальной карты для передачи в LLM.
    Использует только данные из Kerykeion, без транзитов и прогнозов.
    """

    # Маппинг знаков (код → полное название)
    SIGN_MAP = {
        'Ari': 'Овен', 'Tau': 'Телец', 'Gem': 'Близнецы',
        'Can': 'Рак', 'Leo': 'Лев', 'Vir': 'Дева',
        'Lib': 'Весы', 'Sco': 'Скорпион', 'Sag': 'Стрелец',
        'Cap': 'Козерог', 'Aqu': 'Водолей', 'Pis': 'Рыбы'
    }

    # Маппинг планет (техническое имя → русское)
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

    # Маппинг аспектов
    ASPECT_MAP = {
        'conjunction': 'соединение',
        'opposition': 'оппозиция',
        'trine': 'тригон',
        'square': 'квадрат',
        'sextile': 'секстиль',
        'quincunx': 'квинконкс'
    }

    # Разрешённые аспекты (major + quincunx)
    ALLOWED_ASPECTS = {'conjunction', 'opposition', 'trine', 'square', 'sextile', 'quincunx'}

    def __init__(self, subject: AstrologicalSubject, lang: str = 'ru'):
        self.subject = subject
        self.lang = lang
        self._chart_data = None
        self._aspects = None
        self._elements = None
        self._qualities = None
        self._lunar_phase = None

    def build(self) -> str:
        """Основной метод: возвращает текстовый контекст."""
        lines = []
        lines.append("=== NATAL CHART ===\n")

        # 1. Chart metadata
        lines.extend(self._get_metadata())

        # 2. Birth data
        lines.extend(self._get_birth_data())

        # 3. Angles
        lines.extend(self._get_angles())

        # 4. Planets
        lines.extend(self._get_planets())

        # 5. Nodes / Chiron / Lilith
        lines.extend(self._get_extra_points())

        # 6. House cusps
        lines.extend(self._get_house_cusps())

        # 7. Aspects
        lines.extend(self._get_aspects())

        # 8. Element distribution
        lines.extend(self._get_element_distribution())

        # 9. Quality distribution
        lines.extend(self._get_quality_distribution())

        # 10. Lunar phase
        lines.extend(self._get_lunar_phase())

        return "\n".join(lines)

    def _get_metadata(self) -> List[str]:
        """Метаданные карты (тип, зодиак, система домов)."""
        model = self.subject.model() if callable(self.subject.model) else self.subject.model
        data = model.dict() if hasattr(model, 'dict') else model.__dict__

        zodiac = data.get('zodiac_type', 'Tropical')
        house_system = data.get('house_system', 'Placidus')
        perspective = 'Geocentric'  # Kerykeion всегда геоцентрический

        return [
            "Тип карты: Натальная",
            f"Зодиак: {zodiac}",
            f"Система домов: {house_system}",
            f"Перспектива: {perspective}",
            ""
        ]

    def _get_birth_data(self) -> List[str]:
        """Данные рождения: дата, время, место, координаты, часовой пояс."""
        # Извлекаем из subject
        year = getattr(self.subject, 'year', None)
        month = getattr(self.subject, 'month', None)
        day = getattr(self.subject, 'day', None)
        hour = getattr(self.subject, 'hour', None)
        minute = getattr(self.subject, 'minute', None)
        lat = getattr(self.subject, 'lat', None)
        lng = getattr(self.subject, 'lng', None)
        tz_str = getattr(self.subject, 'tz_str', None)

        # Место рождения – берём из user_data, но у нас нет доступа к user_data здесь.
        # Можно добавить параметр в конструктор, но для простоты пока опустим.
        # Позже передадим через дополнительный аргумент.
        place = "не указано"
        # Временно заглушка

        lines = [
            "Рождение:",
            f"Дата: {day:02d}.{month:02d}.{year}" if all([day, month, year]) else "Дата: не указана",
            f"Время: {hour:02d}:{minute:02d}" if hour is not None and minute is not None else "Время: не указано",
            f"Место: {place}",
            f"Координаты: {lat:.4f}° N, {lng:.4f}° E" if lat and lng else "Координаты: не указаны",
            f"Часовой пояс: {tz_str}" if tz_str else "Часовой пояс: не указан",
            ""
        ]
        return lines

    def _get_angles(self) -> List[str]:
        """Углы: ASC, MC, DSC, IC."""
        model = self.subject.model() if callable(self.subject.model) else self.subject.model
        data = model.dict() if hasattr(model, 'dict') else model.__dict__

        # Извлекаем углы
        asc = data.get('ascendant')
        mc = data.get('midheaven')
        dsc = data.get('descendant')
        ic = data.get('imum_coeli')

        # Если нет в data, пробуем через subject
        if not asc and hasattr(self.subject, 'ascendant'):
            asc = self.subject.ascendant
        if not mc and hasattr(self.subject, 'midheaven'):
            mc = self.subject.midheaven
        if not dsc and hasattr(self.subject, 'descendant'):
            dsc = self.subject.descendant
        if not ic and hasattr(self.subject, 'imum_coeli'):
            ic = self.subject.imum_coeli

        def format_angle(angle):
            if not angle:
                return "—"
            # angle может быть KerykeionPointModel или dict
            if isinstance(angle, dict):
                sign = angle.get('sign')
                position = angle.get('position')
            else:
                sign = getattr(angle, 'sign', None)
                position = getattr(angle, 'position', None)
            if sign and position is not None:
                sign_name = self.SIGN_MAP.get(sign, sign)
                return f"{sign_name} {position:.2f}°"
            return "—"

        lines = [
            "Углы:",
            f"ASC: {format_angle(asc)}",
            f"MC: {format_angle(mc)}",
            f"DSC: {format_angle(dsc)}",
            f"IC: {format_angle(ic)}",
            ""
        ]
        return lines

    def _get_planets(self) -> List[str]:
        """Основные планеты (10)."""
        planets = self._get_planet_list()
        lines = ["Планеты:"]
        for p in planets:
            lines.append(self._format_planet(p))
        lines.append("")
        return lines

    def _get_extra_points(self) -> List[str]:
        """Дополнительные точки: узлы, Хирон, Лилит."""
        all_planets = self._get_planet_list()
        extra_names = ['True_North_Lunar_Node', 'True_South_Lunar_Node', 'Chiron', 'True_Lilith']
        extra = [p for p in all_planets if p['name'] in extra_names]
        if extra:
            lines = ["Лунные узлы и дополнительные точки:"]
            for p in extra:
                lines.append(self._format_planet(p))
            lines.append("")
            return lines
        return []

    def _get_planet_list(self) -> List[Dict]:
        """Возвращает список всех планет из карты с извлечёнными полями."""
        model = self.subject.model() if callable(self.subject.model) else self.subject.model
        data = model.dict() if hasattr(model, 'dict') else model.__dict__

        # Kerykeion хранит планеты в data как ключи с именами в нижнем регистре
        # но мы будем искать по имени из PLANET_MAP
        planets = []
        for tech_name in self.PLANET_MAP.keys():
            key = tech_name.lower()
            if key in data:
                obj = data[key]
                if isinstance(obj, dict):
                    if 'sign' in obj and 'position' in obj:
                        planets.append({
                            'name': tech_name,
                            'sign': obj.get('sign'),
                            'position': obj.get('position'),
                            'abs_pos': obj.get('abs_pos'),
                            'house': obj.get('house'),
                            'retrograde': obj.get('retrograde', False),
                        })
                else:
                    # может быть KerykeionPointModel
                    if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                        planets.append({
                            'name': tech_name,
                            'sign': getattr(obj, 'sign'),
                            'position': getattr(obj, 'position'),
                            'abs_pos': getattr(obj, 'abs_pos'),
                            'house': getattr(obj, 'house'),
                            'retrograde': getattr(obj, 'retrograde', False),
                        })
        return planets

    def _format_planet(self, p: Dict) -> str:
        """Форматирует одну планету в строку."""
        name = self.PLANET_MAP.get(p['name'], p['name'])
        sign = self.SIGN_MAP.get(p['sign'], p['sign'])
        pos = p['position']
        house = p['house']
        retro = p['retrograde']

        if retro:
            return f"{name}: {sign} {pos:.2f}°, {house} дом, ретроградный"
        else:
            return f"{name}: {sign} {pos:.2f}°, {house} дом"

    def _get_house_cusps(self) -> List[str]:
        """Куспиды 12 домов."""
        model = self.subject.model() if callable(self.subject.model) else self.subject.model
        data = model.dict() if hasattr(model, 'dict') else model.__dict__

        house_keys = [
            'first_house', 'second_house', 'third_house', 'fourth_house',
            'fifth_house', 'sixth_house', 'seventh_house', 'eighth_house',
            'ninth_house', 'tenth_house', 'eleventh_house', 'twelfth_house'
        ]
        lines = ["Куспиды домов:"]
        for i, key in enumerate(house_keys, 1):
            if key in data:
                obj = data[key]
                if isinstance(obj, dict):
                    sign = obj.get('sign')
                    position = obj.get('position')
                else:
                    sign = getattr(obj, 'sign', None)
                    position = getattr(obj, 'position', None)
                if sign and position is not None:
                    sign_name = self.SIGN_MAP.get(sign, sign)
                    lines.append(f"{i} дом: {sign_name} {position:.2f}°")
                else:
                    lines.append(f"{i} дом: —")
            else:
                lines.append(f"{i} дом: —")
        lines.append("")
        return lines

    def _get_aspects(self) -> List[str]:
        """Аспекты с применением/расхождением."""
        # Пытаемся получить через AspectsFactory
        aspects = []
        try:
            factory = AspectsFactory.single_chart_aspects(self.subject)
            if factory and hasattr(factory, 'aspects'):
                for a in factory.aspects:
                    aspects.append(a)
        except Exception as e:
            logger.warning(f"AspectsFactory не сработал: {e}, пробуем NatalAspects")
            try:
                from kerykeion import NatalAspects
                na = NatalAspects(self.subject)
                if hasattr(na, 'relevant_aspects'):
                    aspects = na.relevant_aspects
            except Exception as e2:
                logger.warning(f"NatalAspects тоже не сработал: {e2}. Аспекты будут пустыми.")

        if not aspects:
            return ["Аспекты: нет значимых аспектов.", ""]

        lines = ["Аспекты:"]
        for a in aspects:
            # Извлекаем данные
            p1 = getattr(a, 'p1_name', None)
            p2 = getattr(a, 'p2_name', None)
            aspect = getattr(a, 'aspect', None)
            orbit = getattr(a, 'orbit', getattr(a, 'orb', None))
            movement = getattr(a, 'aspect_movement', None)  # Kerykeion может давать 'Applying'/'Separating'

            if not p1 or not p2 or not aspect or orbit is None:
                continue

            # Фильтруем только разрешённые аспекты
            if aspect.lower() not in self.ALLOWED_ASPECTS:
                continue

            # Переводы
            p1_name = self.PLANET_MAP.get(p1, p1)
            p2_name = self.PLANET_MAP.get(p2, p2)
            aspect_name = self.ASPECT_MAP.get(aspect.lower(), aspect)

            # Определяем фазу
            if movement:
                phase = "сходящийся" if 'applying' in movement.lower() else "расходящийся" if 'separating' in movement.lower() else ""
            else:
                # fallback: по скоростям (если есть)
                phase = ""
                # можно попробовать извлечь p1_speed, p2_speed
                # но мы не будем усложнять, лучше оставить пустым

            if phase:
                lines.append(f"{p1_name} — {aspect_name} — {p2_name}, орб {orbit:.2f}°, {phase}")
            else:
                lines.append(f"{p1_name} — {aspect_name} — {p2_name}, орб {orbit:.2f}°")

        lines.append("")
        return lines

    def _get_element_distribution(self) -> List[str]:
        """Распределение стихий из Kerykeion."""
        model = self.subject.model() if callable(self.subject.model) else self.subject.model
        data = model.dict() if hasattr(model, 'dict') else model.__dict__

        elements = data.get('element_distribution')
        if elements:
            lines = ["Распределение стихий:"]
            # elements может быть словарем {'Fire': 25, 'Earth': 30, ...}
            for elem, value in elements.items():
                lines.append(f"{elem}: {value}%")
            lines.append("")
            return lines
        return []

    def _get_quality_distribution(self) -> List[str]:
        """Распределение качеств из Kerykeion."""
        model = self.subject.model() if callable(self.subject.model) else self.subject.model
        data = model.dict() if hasattr(model, 'dict') else model.__dict__

        qualities = data.get('quality_distribution')
        if qualities:
            lines = ["Распределение качеств:"]
            # qualities может быть {'Cardinal': 30, 'Fixed': 45, 'Mutable': 25}
            for qual, value in qualities.items():
                lines.append(f"{qual}: {value}%")
            lines.append("")
            return lines
        return []

    def _get_lunar_phase(self) -> List[str]:
        """Лунная фаза."""
        # Kerykeion имеет LunarPhaseModel, но как его получить из субъекта?
        # Есть метод subject.lunar_phase, если он существует
        try:
            if hasattr(self.subject, 'lunar_phase'):
                phase = self.subject.lunar_phase
                if phase:
                    name = getattr(phase, 'name', None)
                    angle = getattr(phase, 'angle', None)
                    if name and angle is not None:
                        return [f"Лунная фаза: {name}, угол Солнце–Луна: {angle:.1f}°", ""]
        except Exception as e:
            logger.warning(f"Не удалось получить лунную фазу: {e}")
        return []