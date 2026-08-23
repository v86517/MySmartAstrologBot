import logging
import zoneinfo
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple

from kerykeion import AstrologicalSubject, ChartDataFactory

from bot.utils.place_resolver import PlaceResolver

logger = logging.getLogger(__name__)


class CompatibilityCalculator:
    """
    Генерирует текстовый контекст для анализа совместимости двух людей.
    Использует штатный механизм Kerykeion для синастрии.
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

    ASPECT_MAP = {
        'conjunction': 'соединение',
        'opposition': 'оппозиция',
        'trine': 'тригон',
        'square': 'квадрат',
        'sextile': 'секстиль'
    }

    PHASE_MAP = {
        'applying': 'сходящийся',
        'separating': 'расходящийся'
    }

    HOUSE_MAP = {
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

    # ========== ОРБЫ ==========
    SYNASTRY_ASPECT_ORBS = {
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
    MAIN_PLANETS = {'Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                    'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto'}
    EXTRA_OBJECTS = {'True_North_Lunar_Node', 'True_South_Lunar_Node',
                     'Chiron', 'True_Lilith', 'ASC', 'MC', 'DSC', 'IC'}

    def __init__(self, person_a_data: Dict[str, Any], person_b_data: Dict[str, Any],
                 lang: str = 'ru',
                 telegram_id: Optional[int] = None,
                 save_for_person_a: bool = False):
        self.person_a_data = person_a_data
        self.person_b_data = person_b_data
        self.lang = lang
        self.telegram_id = telegram_id
        self.save_for_person_a = save_for_person_a

        self._computed_coords = None
        self._computed_for_user = None

        self.subject_a = self._create_subject(person_a_data, '1', save_to_db=save_for_person_a)
        self.subject_b = self._create_subject(person_b_data, '2', save_to_db=False)

        self.synastry_data = self._get_synastry_data()

        self.person_a = {}
        self.person_b = {}
        self._aspects = {'planetary': [], 'extra': []}
        self._planets_in_houses = {}

    def _create_subject(self, data: Dict[str, Any], label: str, save_to_db: bool = False) -> AstrologicalSubject:
        # ... (без изменений, как в предыдущей версии)
        pass  # замените на ваш код

    def _parse_place(self, place: str) -> Tuple[str, str]:
        # ... (без изменений)
        pass

    def _get_synastry_data(self) -> Any:
        # ... (без изменений)
        pass

    def _extract_person_data(self, subject: AstrologicalSubject, label: str, raw_data: Dict[str, Any]) -> Dict:
        """Извлекает данные одной карты + дату/время/координаты из raw_data."""
        model = subject.model() if callable(subject.model) else subject.model
        data = model.dict() if hasattr(model, 'dict') else model.__dict__

        result = {
            'label': label,
            'name': subject.name,
            'birth_date': raw_data.get('birth_date'),
            'birth_time': raw_data.get('birth_time'),
            'birth_place': raw_data.get('birth_place'),
            'lat': raw_data.get('birth_lat'),
            'lng': raw_data.get('birth_lng'),
            'timezone': raw_data.get('birth_timezone'),
            'planets': [],
            'angles': {},
            'houses': []
        }

        # Планеты
        planet_keys = ['sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter',
                       'saturn', 'uranus', 'neptune', 'pluto']
        for key in planet_keys:
            if key in data:
                obj = data[key]
                if isinstance(obj, dict):
                    if 'sign' in obj and 'position' in obj:
                        result['planets'].append({
                            'name': key.capitalize(),
                            'sign': obj.get('sign'),
                            'position': obj.get('position'),
                            'abs_pos': obj.get('abs_pos'),
                            'house': obj.get('house'),
                            'retrograde': obj.get('retrograde', False),
                        })
                else:
                    if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                        result['planets'].append({
                            'name': key.capitalize(),
                            'sign': getattr(obj, 'sign'),
                            'position': getattr(obj, 'position'),
                            'abs_pos': getattr(obj, 'abs_pos'),
                            'house': getattr(obj, 'house'),
                            'retrograde': getattr(obj, 'retrograde', False),
                        })

        # Дополнительные точки (только True_Lilith, без Mean_Lilith)
        extra_keys = [
            ('true_north_lunar_node', 'True_North_Lunar_Node'),
            ('true_south_lunar_node', 'True_South_Lunar_Node'),
            ('chiron', 'Chiron'),
            ('true_lilith', 'True_Lilith')
        ]
        for key, name in extra_keys:
            if key in data and data[key] is not None:
                obj = data[key]
                if isinstance(obj, dict):
                    if 'sign' in obj and 'position' in obj:
                        result['planets'].append({
                            'name': name,
                            'sign': obj.get('sign'),
                            'position': obj.get('position'),
                            'abs_pos': obj.get('abs_pos'),
                            'house': obj.get('house'),
                            'retrograde': obj.get('retrograde', False),
                        })
                else:
                    if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                        result['planets'].append({
                            'name': name,
                            'sign': getattr(obj, 'sign'),
                            'position': getattr(obj, 'position'),
                            'abs_pos': getattr(obj, 'abs_pos'),
                            'house': getattr(obj, 'house'),
                            'retrograde': getattr(obj, 'retrograde', False),
                        })

        # Если True_Lilith отсутствует, логируем предупреждение (уже есть)

        # Углы
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

        if not asc and hasattr(subject, 'ascendant'):
            asc = _extract_angle(subject.ascendant)
        if not mc and hasattr(subject, 'midheaven'):
            mc = _extract_angle(subject.midheaven)

        result['angles'] = {
            'ASC': asc,
            'MC': mc,
            'DSC': dsc,
            'IC': ic
        }

        # Дома
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
                        result['houses'].append({
                            'key': key,
                            'sign': obj.get('sign'),
                            'position': obj.get('position'),
                            'abs_pos': obj.get('abs_pos'),
                        })
                else:
                    if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                        result['houses'].append({
                            'key': key,
                            'sign': getattr(obj, 'sign'),
                            'position': getattr(obj, 'position'),
                            'abs_pos': getattr(obj, 'abs_pos'),
                        })

        return result

    def _filter_aspects(self) -> None:
        # ... (этот метод уже работает корректно, но убедитесь, что Mean_Lilith не проходит фильтр)
        # В текущей реализации Mean_Lilith не входит ни в MAIN_PLANETS, ни в EXTRA_OBJECTS,
        # поэтому аспекты с Mean_Lilith пропускаются. Оставляем как есть.
        pass  # замените на ваш код (он уже был обновлён ранее)

    def _get_planets_in_houses(self) -> Dict:
        """Извлекает попадание планет одного человека в дома другого.
        Исключает Mean_Lilith и углы (ASC, MC, DSC, IC)."""
        result = {'a_in_b': [], 'b_in_a': []}

        if not self.synastry_data:
            return result

        if not hasattr(self.synastry_data, 'house_comparison'):
            return result

        hc = self.synastry_data.house_comparison

        # Разрешённые объекты: 10 планет + узлы + Chiron + True_Lilith
        allowed_objects = set(self.MAIN_PLANETS)
        allowed_objects.add('True_North_Lunar_Node')
        allowed_objects.add('True_South_Lunar_Node')
        allowed_objects.add('Chiron')
        allowed_objects.add('True_Lilith')

        def is_allowed(point_name):
            return point_name in allowed_objects

        if hasattr(hc, 'first_points_in_second_houses') and hc.first_points_in_second_houses:
            for item in hc.first_points_in_second_houses:
                if isinstance(item, dict):
                    point_name = item.get('point_name')
                    house = item.get('projected_house_number')
                else:
                    point_name = getattr(item, 'point_name', None)
                    house = getattr(item, 'projected_house_number', None)
                if point_name and house and is_allowed(point_name):
                    result['a_in_b'].append({'planet': point_name, 'house': house})

        if hasattr(hc, 'second_points_in_first_houses') and hc.second_points_in_first_houses:
            for item in hc.second_points_in_first_houses:
                if isinstance(item, dict):
                    point_name = item.get('point_name')
                    house = item.get('projected_house_number')
                else:
                    point_name = getattr(item, 'point_name', None)
                    house = getattr(item, 'projected_house_number', None)
                if point_name and house and is_allowed(point_name):
                    result['b_in_a'].append({'planet': point_name, 'house': house})

        logger.info(f"Планеты 1 в домах 2: {len(result['a_in_b'])}, Планеты 2 в домах 1: {len(result['b_in_a'])}")
        return result

    def build(self) -> str:
        self.person_a = self._extract_person_data(self.subject_a, '1', self.person_a_data)
        self.person_b = self._extract_person_data(self.subject_b, '2', self.person_b_data)

        self._filter_aspects()
        self._planets_in_houses = self._get_planets_in_houses()

        return self._format()

    def _format(self) -> str:
        # ... (без изменений, использует _format_person, _format_aspect)
        pass

    def _format_person(self, person: Dict, label: str) -> List[str]:
        lines = []
        lines.append(f"=== ЧЕЛОВЕК {label} ===")
        lines.append("")
        lines.append("Рождение:")
        lines.append(f"Имя: {person['name']}")
        # Дата и время
        birth_date = person.get('birth_date', 'не указана')
        birth_time = person.get('birth_time', 'не указано')
        lines.append(f"Дата: {birth_date}")
        lines.append(f"Время: {birth_time}")
        # Координаты и часовой пояс
        lat = person.get('lat')
        lng = person.get('lng')
        if lat is not None and lng is not None:
            lines.append(f"Координаты: {lat:.4f}° N, {lng:.4f}° E")
        else:
            lines.append("Координаты: не указаны")
        timezone = person.get('timezone')
        lines.append(f"Часовой пояс: {timezone if timezone else 'не указан'}")
        lines.append("")

        # Углы
        lines.append("Углы:")
        for angle_name in ['ASC', 'MC', 'DSC', 'IC']:
            angle = person['angles'].get(angle_name)
            if angle:
                sign = self.SIGN_MAP.get(angle.get('sign'), angle.get('sign'))
                pos = angle.get('position', 0.0)
                lines.append(f"{angle_name}: {sign} {pos:.2f}°")
            else:
                lines.append(f"{angle_name}: —")
        lines.append("")

        # Планеты (основные)
        planet_order = ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                        'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']
        lines.append("Планеты:")
        for name in planet_order:
            planet = next((p for p in person['planets'] if p['name'] == name), None)
            if planet:
                lines.append(self._format_planet(planet))
        lines.append("")

        # Дополнительные точки (только True_Lilith, если есть)
        extra_order = ['True_North_Lunar_Node', 'True_South_Lunar_Node', 'Chiron', 'True_Lilith']
        lines.append("Дополнительные точки:")
        has_extra = False
        for name in extra_order:
            point = next((p for p in person['planets'] if p['name'] == name), None)
            if point:
                lines.append(self._format_planet(point))
                has_extra = True
        if not has_extra:
            lines.append("Нет дополнительных точек")
        lines.append("")

        # Куспиды домов
        lines.append("Куспиды домов:")
        house_order = ['first_house', 'second_house', 'third_house', 'fourth_house',
                       'fifth_house', 'sixth_house', 'seventh_house', 'eighth_house',
                       'ninth_house', 'tenth_house', 'eleventh_house', 'twelfth_house']
        for key in house_order:
            house = next((h for h in person['houses'] if h['key'] == key), None)
            if house:
                sign = self.SIGN_MAP.get(house['sign'], house['sign'])
                pos = house['position']
                house_display = self.HOUSE_MAP.get(self._house_key_to_standard(key), key)
                lines.append(f"{house_display}: {sign} {pos:.2f}°")
            else:
                house_display = self.HOUSE_MAP.get(self._house_key_to_standard(key), key)
                lines.append(f"{house_display}: —")
        lines.append("")

        return lines

    def _house_key_to_standard(self, key: str) -> str:
        return key.replace('_', ' ').title().replace(' ', '_')

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
            house_display = self.HOUSE_MAP.get(house, house)
        else:
            house_display = "неизвестный дом"

        if retro:
            return f"{name}: {sign} {pos:.2f}°, {house_display}, ретроградный"
        return f"{name}: {sign} {pos:.2f}°, {house_display}"

    def _format_aspect(self, aspect: Dict) -> str:
        p1 = aspect['p1']
        p2 = aspect['p2']
        owner1 = aspect.get('owner1', '?')
        owner2 = aspect.get('owner2', '?')

        p1_display = self._get_display_name(p1, owner1)
        p2_display = self._get_display_name(p2, owner2)

        aspect_name = self.ASPECT_MAP.get(aspect['aspect'].lower(), aspect['aspect'])
        orb = aspect['orb']
        movement = aspect.get('movement')

        if movement:
            phase = self.PHASE_MAP.get(movement.lower(), '')
            if phase:
                return f"{p1_display} — {aspect_name} — {p2_display}, орб {orb:.2f}°, {phase}"

        return f"{p1_display} — {aspect_name} — {p2_display}, орб {orb:.2f}°"

    def _get_display_name(self, name: str, label: str) -> str:
        display = self.PLANET_MAP.get(name, name)
        if label and label != '?':
            return f"{display} {label}"
        return display