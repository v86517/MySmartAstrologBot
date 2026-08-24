import logging
import zoneinfo
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Tuple, Set
from pathlib import Path
import math

from kerykeion import AstrologicalSubject, ChartDataFactory

from bot.calculators.astrology_calculator import AstrologyCalculator
from bot.calculators.natal_context_builder import NatalContextBuilder
from bot.utils.place_resolver import PlaceResolver

logger = logging.getLogger(__name__)


class TransitCalculator:
    """
    Новый калькулятор гороскопа (день/месяц/год) на основе сканирования позиций.
    """

    # Орбы для транзитов к натальным планетам
    PLANET_ORBS = {
        'conjunction': 3.0,
        'opposition': 3.0,
        'trine': 3.0,
        'square': 3.0,
        'sextile': 2.0,
    }

    # Орбы для транзитов к углам
    ANGLE_ORBS = {
        'conjunction': 2.0,
        'opposition': 2.0,
        'trine': 2.0,
        'square': 2.0,
        'sextile': 1.5,
    }

    # Орбы для узлов и Хирона
    EXTRA_ORBS = {
        'conjunction': 2.0,
        'opposition': 2.0,
        'trine': 2.0,
        'square': 2.0,
        'sextile': 1.5,
    }

    # Лунный орб
    MOON_ORB = 1.0

    # Группы планет для фильтрации
    GROUP_A = {'Saturn', 'Uranus', 'Neptune', 'Pluto', 'Jupiter'}
    GROUP_B = {'Mars', 'Venus', 'Mercury', 'Sun'}
    GROUP_C = {'Moon'}

    # Разрешённые аспекты
    ALLOWED_ASPECTS = {'conjunction', 'opposition', 'trine', 'square', 'sextile'}

    # Приоритеты планет для сортировки
    PLANET_PRIORITY = {
        'Pluto': 10, 'Neptune': 9, 'Uranus': 9, 'Saturn': 8,
        'Jupiter': 7, 'Mars': 6, 'Venus': 5, 'Mercury': 5,
        'Sun': 5, 'Moon': 4
    }

    def __init__(self, user_data: Dict[str, Any], lang: str = 'ru',
                 telegram_id: Optional[int] = None,
                 coords: Optional[Tuple[float, float, str]] = None,
                 emulation_mode: bool = False):
        self.user_data = user_data
        self.lang = lang
        self.telegram_id = telegram_id
        self.coords = coords
        self.emulation_mode = emulation_mode

        # Получаем натальную карту
        self.astro_calc = AstrologyCalculator(
            user_data, lang=lang, telegram_id=telegram_id, coords=coords,
            emulation_mode=False
        )
        self.natal_data = self.astro_calc._build_natal_chart()
        self.subject = self.astro_calc._subject

        # Сохраняем натальные планеты и углы
        self.natal_planets = self.natal_data['planets']
        self.natal_angles = self.natal_data['angles']
        self.natal_houses = self.natal_data['houses']

        # Список натальных целей (с унифицированным ключом 'position')
        self.natal_targets = []

        # Основные планеты
        main_names = {'Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                      'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto'}
        for p in self.natal_planets:
            if p['name'] in main_names:
                target = dict(p)
                target['position'] = p.get('degree', 0.0)  # добавляем position из degree
                self.natal_targets.append(target)

        # Углы
        angle_names = ['ASC', 'MC', 'DSC', 'IC']
        for name in angle_names:
            if name in self.natal_angles and self.natal_angles[name] is not None:
                angle_data = self.natal_angles[name]
                if isinstance(angle_data, dict) and 'position' in angle_data:
                    self.natal_targets.append({
                        'name': name,
                        'sign': angle_data.get('sign'),
                        'position': angle_data['position'],
                        'house': None,
                        'retrograde': False,
                        'is_angle': True
                    })

        # Дополнительные точки (узлы, Хирон, True_Lilith)
        extra_names = {'True_North_Lunar_Node', 'True_South_Lunar_Node', 'Chiron', 'True_Lilith'}
        for p in self.natal_planets:
            if p['name'] in extra_names:
                if 'degree' in p:
                    target = dict(p)
                    target['position'] = p['degree']
                    self.natal_targets.append(target)

        # Кеш для транзитных позиций
        self._position_cache = {}

    # ---------- ПОЛУЧЕНИЕ ТРАНЗИТНЫХ ПОЗИЦИЙ ----------

    def _get_transit_subject(self, date: datetime) -> AstrologicalSubject:
        lat = self.natal_data['location']['lat']
        lng = self.natal_data['location']['lng']
        return AstrologicalSubject(
            name="Transit",
            year=date.year,
            month=date.month,
            day=date.day,
            hour=date.hour,
            minute=date.minute,
            lat=lat,
            lng=lng,
            tz_str="UTC"
        )

    def _get_transit_positions(self, date: datetime) -> Dict[str, Dict]:
        key = date.strftime('%Y-%m-%d')
        if key in self._position_cache:
            return self._position_cache[key]

        subject = self._get_transit_subject(date)
        model = subject.model() if callable(subject.model) else subject.model
        data = model.dict() if hasattr(model, 'dict') else model.__dict__

        planets = {}
        for name in ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                     'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']:
            key_name = name.lower()
            if key_name in data:
                obj = data[key_name]
                if isinstance(obj, dict):
                    if 'position' in obj and 'sign' in obj:
                        planets[name] = {
                            'longitude': obj['position'],
                            'sign': obj['sign'],
                            'retrograde': obj.get('retrograde', False),
                            'speed': obj.get('speed', 0.0),
                            'house': self._get_transit_house(obj['position'])
                        }
                else:
                    if hasattr(obj, 'position') and hasattr(obj, 'sign'):
                        planets[name] = {
                            'longitude': getattr(obj, 'position'),
                            'sign': getattr(obj, 'sign'),
                            'retrograde': getattr(obj, 'retrograde', False),
                            'speed': getattr(obj, 'speed', 0.0),
                            'house': self._get_transit_house(getattr(obj, 'position'))
                        }

        self._position_cache[key] = planets
        return planets

    def _get_transit_house(self, longitude: float) -> int:
        if not self.natal_houses:
            return 0
        sorted_houses = sorted(self.natal_houses, key=lambda h: h['degree'])
        for i, h in enumerate(sorted_houses):
            next_house = sorted_houses[(i + 1) % len(sorted_houses)]
            start = h['degree']
            end = next_house['degree']
            if end < start:
                if longitude >= start or longitude < end:
                    return i + 1
            else:
                if start <= longitude < end:
                    return i + 1
        return 0

    # ---------- РАСЧЁТ АСПЕКТОВ ----------

    def _calculate_aspect(self, lon1: float, lon2: float) -> Optional[Tuple[str, float]]:
        diff = abs(lon1 - lon2) % 360
        if diff > 180:
            diff = 360 - diff
        targets = {
            'conjunction': 0,
            'opposition': 180,
            'trine': 120,
            'square': 90,
            'sextile': 60,
        }
        for aspect, angle in targets.items():
            orb = abs(diff - angle)
            if orb <= 5.0:
                return aspect, orb
        return None

    def _get_aspects_for_day(self, date: datetime) -> List[Dict]:
        transit_positions = self._get_transit_positions(date)
        aspects = []
        for t_planet, t_data in transit_positions.items():
            t_lon = t_data['longitude']
            t_house = t_data['house']
            t_retro = t_data['retrograde']

            for target in self.natal_targets:
                if 'position' not in target:
                    continue
                n_lon = target['position']
                aspect_info = self._calculate_aspect(t_lon, n_lon)
                if not aspect_info:
                    continue
                aspect_type, orb = aspect_info

                # Определяем орб
                if target.get('is_angle'):
                    max_orb = self.ANGLE_ORBS.get(aspect_type, 2.0)
                elif target['name'] in ('True_North_Lunar_Node', 'True_South_Lunar_Node', 'Chiron'):
                    max_orb = self.EXTRA_ORBS.get(aspect_type, 2.0)
                else:
                    max_orb = self.PLANET_ORBS.get(aspect_type, 3.0)

                if t_planet == 'Moon':
                    max_orb = self.MOON_ORB

                if orb > max_orb:
                    continue

                aspects.append({
                    'transit_planet': t_planet,
                    'natal_target': target['name'],
                    'aspect': aspect_type,
                    'orb': orb,
                    'transit_house': t_house,
                    'natal_house': target.get('house'),
                    'transit_retrograde': t_retro,
                    'target_is_angle': target.get('is_angle', False),
                    'date': date,
                })
        return aspects

    def _scan_period(self, start: datetime, end: datetime, period_type: str) -> List[Dict]:
        daily_aspects = []
        current = start
        while current <= end:
            aspects = self._get_aspects_for_day(current)
            for a in aspects:
                a['date'] = current
                daily_aspects.append(a)
            current += timedelta(days=1)

        groups = {}
        for a in daily_aspects:
            key = (a['transit_planet'], a['natal_target'], a['aspect'])
            if key not in groups:
                groups[key] = []
            groups[key].append(a)

        events = []
        for key, items in groups.items():
            if not items:
                continue
            t_planet, n_target, aspect = key
            items_sorted = sorted(items, key=lambda x: x['date'])
            first = items_sorted[0]
            if first['target_is_angle']:
                max_orb = self.ANGLE_ORBS.get(aspect, 2.0)
            elif n_target in ('True_North_Lunar_Node', 'True_South_Lunar_Node', 'Chiron'):
                max_orb = self.EXTRA_ORBS.get(aspect, 2.0)
            else:
                max_orb = self.PLANET_ORBS.get(aspect, 3.0)
            if t_planet == 'Moon':
                max_orb = self.MOON_ORB

            segments = []
            current_segment = []
            for i, item in enumerate(items_sorted):
                if item['orb'] <= max_orb:
                    if not current_segment:
                        current_segment.append(item)
                    else:
                        prev = current_segment[-1]
                        if (item['date'] - prev['date']).days <= 1:
                            current_segment.append(item)
                        else:
                            if len(current_segment) >= 2:
                                segments.append(current_segment)
                            current_segment = [item]
                else:
                    if len(current_segment) >= 2:
                        segments.append(current_segment)
                    current_segment = []
            if len(current_segment) >= 2:
                segments.append(current_segment)

            for seg in segments:
                if len(seg) < 2:
                    continue
                min_orb_item = min(seg, key=lambda x: x['orb'])
                exact_date = min_orb_item['date']
                entry_date = seg[0]['date']
                exit_date = seg[-1]['date']

                # Определяем фазу упрощённо
                phase = 'applying'
                if len(seg) >= 3:
                    idx = seg.index(min_orb_item)
                    if idx > 0 and idx < len(seg) - 1:
                        before = seg[idx-1]['orb']
                        after = seg[idx+1]['orb']
                        if before > after:
                            phase = 'applying'
                        elif after > before:
                            phase = 'separating'
                        else:
                            phase = 'stationary'

                events.append({
                    'transit_planet': t_planet,
                    'natal_target': n_target,
                    'aspect': aspect,
                    'entry_date': entry_date,
                    'exact_date': exact_date,
                    'exit_date': exit_date,
                    'transit_house': min_orb_item['transit_house'],
                    'natal_house': min_orb_item['natal_house'],
                    'orb_min': min_orb_item['orb'],
                    'phase': phase,
                    'transit_retrograde': min_orb_item.get('transit_retrograde', False),
                })

        return events

    def _filter_events(self, events: List[Dict], period_type: str, target_date: datetime = None) -> List[Dict]:
        if period_type == 'today':
            filtered = []
            for ev in events:
                if ev['entry_date'] <= target_date <= ev['exit_date']:
                    filtered.append(ev)
            return filtered

        elif period_type == 'month':
            filtered = []
            for ev in events:
                planet = ev['transit_planet']
                if planet in self.GROUP_A or planet in self.GROUP_B:
                    filtered.append(ev)
                elif planet in self.GROUP_C:
                    if ev['orb_min'] <= 0.5 or ev['natal_target'] in ('Sun', 'Moon', 'ASC', 'MC'):
                        filtered.append(ev)
            return filtered

        else:  # year
            filtered = []
            for ev in events:
                planet = ev['transit_planet']
                if planet in self.GROUP_A:
                    filtered.append(ev)
                elif planet in self.GROUP_B:
                    if ev['orb_min'] <= 0.5 and ev['natal_target'] in ('Sun', 'Moon', 'ASC', 'MC'):
                        filtered.append(ev)
            return filtered

    def build_context(self, period: str = 'today',
                      start_date: Optional[datetime] = None,
                      end_date: Optional[datetime] = None,
                      target_date: Optional[datetime] = None) -> str:
        if not start_date or not end_date or not target_date:
            if period == 'today':
                target_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                start_date = target_date - timedelta(days=1)
                end_date = target_date + timedelta(days=1)
            elif period == 'month':
                now = datetime.now(timezone.utc)
                target_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                start_date = target_date
                next_month = target_date + timedelta(days=32)
                end_date = next_month.replace(day=1) - timedelta(seconds=1)
            else:
                now = datetime.now(timezone.utc)
                target_date = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
                start_date = target_date
                end_date = target_date.replace(month=12, day=31, hour=23, minute=59, second=59)

        all_events = self._scan_period(start_date, end_date, period)
        filtered_events = self._filter_events(all_events, period, target_date)

        lines = []

        if period == 'today':
            lines.append(f"### Прогноз на день")
            lines.append(f"Дата: {target_date.strftime('%d.%m.%Y')}")
        elif period == 'month':
            lines.append(f"### Прогноз на месяц")
            lines.append(f"Период: {target_date.strftime('%B %Y')}")
        else:
            lines.append(f"### Прогноз на год")
            lines.append(f"Год: {target_date.year}")
        lines.append("")

        # Натальные данные
        lines.append("### Натальные данные")
        lines.append("")
        for angle_name in ['ASC', 'MC', 'DSC', 'IC']:
            angle = self.natal_angles.get(angle_name)
            if angle and isinstance(angle, dict) and 'position' in angle:
                sign = NatalContextBuilder.SIGN_MAP.get(angle.get('sign'), angle.get('sign'))
                pos = angle.get('position', 0.0)
                lines.append(f"{angle_name}: {sign} {pos:.2f}°")
        lines.append("")
        planet_order = ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                        'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']
        for name in planet_order:
            planet = next((p for p in self.natal_planets if p['name'] == name), None)
            if planet:
                sign = NatalContextBuilder.SIGN_MAP.get(planet['sign'], planet['sign'])
                pos = planet['degree']  # Используем degree
                house = planet['house']
                retro = planet['retrograde']
                line = f"{name}: {sign} {pos:.2f}°, {house} дом"
                if retro:
                    line += ", ретроградный"
                lines.append(line)
        lines.append("")

        if not filtered_events:
            lines.append("### Активные транзиты")
            lines.append("")
            lines.append("Нет значимых транзитов в указанный период.")
            lines.append("")
        else:
            filtered_events.sort(key=lambda x: (self.PLANET_PRIORITY.get(x['transit_planet'], 0),
                                                x['exact_date']), reverse=True)

            lines.append("### Основные транзиты")
            lines.append("")
            for ev in filtered_events:
                t_planet = ev['transit_planet']
                n_target = ev['natal_target']
                aspect = ev['aspect']
                orb = ev['orb_min']
                phase = ev['phase']
                transit_house = ev['transit_house']
                natal_house = ev['natal_house']

                aspect_name = NatalContextBuilder.ASPECT_MAP.get(aspect, aspect)
                phase_text = "сходящийся" if phase == 'applying' else "расходящийся" if phase == 'separating' else ""

                line = f"{t_planet} транзитный — {aspect_name} — натальное {n_target}"
                if phase_text:
                    line += f", орб {orb:.2f}°, {phase_text}"
                else:
                    line += f", орб {orb:.2f}°"
                lines.append(line)
                if transit_house:
                    lines.append(f"Транзитная планета активирует {transit_house} дом")
                if natal_house:
                    lines.append(f"Натальный {n_target} находится в {natal_house} доме")
                if ev['entry_date'] and ev['exit_date']:
                    lines.append(f"Период: {ev['entry_date'].strftime('%d.%m.%Y')} – {ev['exit_date'].strftime('%d.%m.%Y')}")
                if ev['exact_date']:
                    lines.append(f"Точная дата: {ev['exact_date'].strftime('%d.%m.%Y')}")
                lines.append("")

        return "\n".join(lines)