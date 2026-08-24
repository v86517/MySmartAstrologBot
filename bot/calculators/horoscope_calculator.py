import logging
import zoneinfo
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Tuple, Set
from pathlib import Path
import math

from kerykeion import AstrologicalSubject

from bot.calculators.astrology_calculator import AstrologyCalculator
from bot.calculators.natal_context_builder import NatalContextBuilder

logger = logging.getLogger(__name__)


class HoroscopeCalculator:
    """
    Калькулятор гороскопа (день/месяц/год) с корректной астрологической геометрией.
    Все координаты хранятся в абсолютной долготе (0-360°).
    Поддерживает скоринг и фильтрацию по значимости.
    """

    # Маппинг знаков → начальная долгота
    SIGN_START = {
        'Aries': 0, 'Taurus': 30, 'Gemini': 60, 'Cancer': 90,
        'Leo': 120, 'Virgo': 150, 'Libra': 180, 'Scorpio': 210,
        'Sagittarius': 240, 'Capricorn': 270, 'Aquarius': 300, 'Pisces': 330
    }

    # Максимальные орбы для транзитов
    ORBS = {
        'conjunction': 3.0,
        'opposition': 3.0,
        'trine': 3.0,
        'square': 3.0,
        'sextile': 2.0,
    }
    MOON_ORB = 1.0
    ANGLE_ORB = 2.0
    NODE_ORB = 2.0
    CHIRON_ORB = 2.0

    # Группы планет для фильтрации
    GROUP_A = {'Saturn', 'Uranus', 'Neptune', 'Pluto', 'Jupiter'}
    GROUP_B = {'Mars', 'Venus', 'Mercury', 'Sun'}
    GROUP_C = {'Moon'}

    # Веса планет для скоринга
    PLANET_WEIGHT = {
        'Pluto': 10, 'Neptune': 9, 'Uranus': 9, 'Saturn': 8,
        'Jupiter': 7, 'Mars': 6, 'Venus': 5, 'Mercury': 5,
        'Sun': 5, 'Moon': 4
    }

    # Веса натальных объектов для скоринга
    TARGET_WEIGHT = {
        'Sun': 10, 'Moon': 10, 'ASC': 10, 'MC': 9,
        'Mercury': 8, 'Venus': 8, 'Mars': 8,
        'Jupiter': 6, 'Saturn': 6, 'Uranus': 5,
        'Neptune': 5, 'Pluto': 5
    }

    # Веса аспектов
    ASPECT_WEIGHT = {
        'conjunction': 1.0,
        'opposition': 0.95,
        'trine': 0.90,
        'square': 0.85,
        'sextile': 0.75
    }

    # Порог для включения быстрых планет в разные прогнозы
    FAST_PLANET_DAY_ORB = 1.0
    FAST_PLANET_MONTH_ORB = 1.5
    FAST_PLANET_YEAR_ORB = 0.5

    # Максимальное количество событий для вывода
    MAX_EVENTS_DAY = 7
    MAX_EVENTS_MONTH = 15
    MAX_EVENTS_YEAR = 20

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

        # Сохраняем натальные данные
        self.natal_planets = self.natal_data['planets']
        self.natal_angles = self.natal_data['angles']
        self.natal_houses = self.natal_data['houses']

        # Строим список натальных целей с абсолютными долготами
        self.natal_targets = []
        # Основные планеты
        main_names = {'Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                      'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto'}
        for p in self.natal_planets:
            if p['name'] in main_names:
                lon_abs = self._sign_to_abs(p['sign'], p['degree'])
                self.natal_targets.append({
                    'name': p['name'],
                    'longitude': lon_abs,
                    'house': p['house'],
                    'is_angle': False,
                    'extra_type': None,
                    'weight': self.TARGET_WEIGHT.get(p['name'], 5)
                })
        # Углы
        angle_names = ['ASC', 'MC', 'DSC', 'IC']
        for angle in angle_names:
            if angle in self.natal_angles and self.natal_angles[angle] is not None:
                a = self.natal_angles[angle]
                lon_abs = self._sign_to_abs(a['sign'], a['position'])
                self.natal_targets.append({
                    'name': angle,
                    'longitude': lon_abs,
                    'house': None,
                    'is_angle': True,
                    'extra_type': 'angle',
                    'weight': self.TARGET_WEIGHT.get(angle, 9)
                })
        # Дополнительные точки (узлы, Хирон, Лилит)
        extra_names = ['True_North_Lunar_Node', 'True_South_Lunar_Node', 'Chiron', 'True_Lilith']
        for p in self.natal_planets:
            if p['name'] in extra_names:
                lon_abs = self._sign_to_abs(p['sign'], p['degree'])
                extra_type = 'node' if 'Node' in p['name'] else 'chiron' if p['name'] == 'Chiron' else 'lilith'
                self.natal_targets.append({
                    'name': p['name'],
                    'longitude': lon_abs,
                    'house': p.get('house'),
                    'is_angle': False,
                    'extra_type': extra_type,
                    'weight': 3  # меньший вес
                })

        # Кеш транзитных позиций
        self._transit_cache = {}  # date_str -> dict planet -> abs_longitude

    # ---------- УТИЛИТЫ ----------

    def _sign_to_abs(self, sign: str, degree: float) -> float:
        """Преобразует знак и градус в абсолютную долготу (0-360)."""
        start = self.SIGN_START.get(sign, 0)
        # Если degree >= 30, значит это уже абсолютное значение (может быть при некорректных данных)
        # Нормализуем
        if degree >= 30:
            return degree % 360
        return start + degree

    def _angle_between(self, lon1: float, lon2: float) -> float:
        """Возвращает минимальное угловое расстояние между двумя долготами."""
        diff = abs(lon1 - lon2) % 360
        if diff > 180:
            diff = 360 - diff
        return diff

    def _aspect_info(self, angle: float) -> Tuple[str, float]:
        """
        Определяет тип аспекта и орб по угловому расстоянию.
        Возвращает (aspect_type, orb).
        """
        targets = {
            'conjunction': 0,
            'opposition': 180,
            'trine': 120,
            'square': 90,
            'sextile': 60,
        }
        best_aspect = None
        best_orb = 360.0
        for aspect, target in targets.items():
            orb = abs(angle - target)
            if orb < best_orb:
                best_orb = orb
                best_aspect = aspect
        return best_aspect, best_orb

    def _max_orb(self, aspect: str, target: Dict, planet: str) -> float:
        """Возвращает максимальный орб для данного аспекта, цели и планеты."""
        if target['is_angle']:
            return self.ANGLE_ORB
        if target['extra_type'] == 'node':
            return self.NODE_ORB
        if target['extra_type'] == 'chiron':
            return self.CHIRON_ORB
        if planet == 'Moon':
            return self.MOON_ORB
        return self.ORBS.get(aspect, 3.0)

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

    def _get_transit_positions(self, date: datetime) -> Dict[str, float]:
        """Возвращает абсолютные долготы транзитных планет на указанную дату."""
        key = date.strftime('%Y-%m-%d')
        if key in self._transit_cache:
            return self._transit_cache[key]

        subject = self._get_transit_subject(date)
        model = subject.model() if callable(subject.model) else subject.model
        data = model.dict() if hasattr(model, 'dict') else model.__dict__

        positions = {}
        for planet in ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                       'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']:
            p_key = planet.lower()
            if p_key in data:
                obj = data[p_key]
                if isinstance(obj, dict):
                    sign = obj.get('sign', '')
                    degree = obj.get('position', 0.0)
                    if sign:
                        positions[planet] = self._sign_to_abs(sign, degree)
                else:
                    if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                        sign = getattr(obj, 'sign', '')
                        degree = getattr(obj, 'position', 0.0)
                        if sign:
                            positions[planet] = self._sign_to_abs(sign, degree)

        self._transit_cache[key] = positions
        return positions

    def _get_transit_house(self, date: datetime, planet: str) -> int:
        """Определяет натальный дом транзитной планеты."""
        positions = self._get_transit_positions(date)
        if planet not in positions or not self.natal_houses:
            return 0
        lon = positions[planet]
        sorted_houses = sorted(self.natal_houses, key=lambda h: h['degree'])
        for i, h in enumerate(sorted_houses):
            next_house = sorted_houses[(i + 1) % len(sorted_houses)]
            start = h['degree']
            end = next_house['degree']
            if end < start:
                if lon >= start or lon < end:
                    return i + 1
            else:
                if start <= lon < end:
                    return i + 1
        return 0

    def _is_retrograde(self, date: datetime, planet: str) -> bool:
        """Определяет ретроградность транзитной планеты (упрощённо)."""
        # В реальности нужно проверять скорость, но для простоты можно получить из данных
        # Для точности можно вычислять по изменению позиции на соседних днях.
        # Пока оставим заглушку.
        return False

    # ---------- СКАНИРОВАНИЕ ПЕРИОДА ----------

    def _scan_period(self, start: datetime, end: datetime) -> List[Dict]:
        """
        Сканирует период с шагом 1 день и собирает все транзитные аспекты.
        Возвращает список событий с полной информацией.
        """
        events = []
        # Соберём позиции для всех дней
        days = []
        current = start
        while current <= end:
            positions = self._get_transit_positions(current)
            days.append({
                'date': current,
                'positions': positions
            })
            current += timedelta(days=1)

        if len(days) < 2:
            return events

        # Для каждой пары транзитная планета × натальная цель
        for target in self.natal_targets:
            t_lon = target['longitude']
            for planet in ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                           'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']:
                # Соберём временной ряд орбов для этого аспекта
                orb_series = []
                for day in days:
                    if planet in day['positions']:
                        p_lon = day['positions'][planet]
                        angle = self._angle_between(p_lon, t_lon)
                        aspect, orb = self._aspect_info(angle)
                        orb_series.append({
                            'date': day['date'],
                            'angle': angle,
                            'aspect': aspect,
                            'orb': orb,
                            'transit_lon': p_lon
                        })

                if not orb_series:
                    continue

                # Разобьём на сегменты по типу аспекта
                segments = []
                current_seg = []
                last_aspect = None
                for item in orb_series:
                    if last_aspect is None:
                        last_aspect = item['aspect']
                        current_seg.append(item)
                    elif item['aspect'] == last_aspect:
                        current_seg.append(item)
                    else:
                        if len(current_seg) > 1:
                            segments.append(current_seg)
                        current_seg = [item]
                        last_aspect = item['aspect']
                if len(current_seg) > 1:
                    segments.append(current_seg)

                for seg in segments:
                    if len(seg) < 2:
                        continue
                    aspect_type = seg[0]['aspect']
                    max_orb = self._max_orb(aspect_type, target, planet)

                    # Находим подпоследовательности, где орб <= max_orb
                    active_segments = []
                    current_active = []
                    for item in seg:
                        if item['orb'] <= max_orb:
                            if not current_active:
                                current_active.append(item)
                            else:
                                prev = current_active[-1]
                                if (item['date'] - prev['date']).days <= 1:
                                    current_active.append(item)
                                else:
                                    if len(current_active) >= 2:
                                        active_segments.append(current_active)
                                    current_active = [item]
                        else:
                            if len(current_active) >= 2:
                                active_segments.append(current_active)
                            current_active = []
                    if len(current_active) >= 2:
                        active_segments.append(current_active)

                    for act in active_segments:
                        if len(act) < 2:
                            continue
                        # Находим точку с минимальным орбом
                        min_item = min(act, key=lambda x: x['orb'])
                        exact_date = min_item['date']
                        entry_date = act[0]['date']
                        exit_date = act[-1]['date']

                        # Определяем фазу
                        phase = 'applying'
                        if len(act) >= 3:
                            idx = act.index(min_item)
                            if idx > 0 and idx < len(act) - 1:
                                before = act[idx-1]['orb']
                                after = act[idx+1]['orb']
                                if before > after:
                                    phase = 'applying'
                                elif after > before:
                                    phase = 'separating'
                                else:
                                    phase = 'exact'
                        elif len(act) == 2:
                            if act[0]['orb'] > act[1]['orb']:
                                phase = 'applying'
                            else:
                                phase = 'separating'

                        events.append({
                            'transit_planet': planet,
                            'natal_target': target['name'],
                            'aspect': aspect_type,
                            'orb_min': min_item['orb'],
                            'angle_at_exact': min_item['angle'],
                            'transit_lon_at_exact': min_item['transit_lon'],
                            'entry_date': entry_date,
                            'exact_date': exact_date,
                            'exit_date': exit_date,
                            'phase': phase,
                            'transit_house': self._get_transit_house(exact_date, planet),
                            'natal_house': target['house'],
                            'is_angle': target['is_angle'],
                            'extra_type': target['extra_type'],
                            'retrograde': self._is_retrograde(exact_date, planet),
                            'target_weight': target['weight'],
                            'planet_weight': self.PLANET_WEIGHT.get(planet, 5),
                            'aspect_weight': self.ASPECT_WEIGHT.get(aspect_type, 0.7),
                        })

        return events

    # ---------- СКОРИНГ И ФИЛЬТРАЦИЯ ----------

    def _score_event(self, ev: Dict, target_date: datetime) -> float:
        """Вычисляет score для события."""
        # Базовая значимость аспекта
        base_score = ev['planet_weight'] * ev['aspect_weight'] * ev['target_weight'] / 100

        # Учитываем орб: чем меньше орб, тем выше коэффициент
        orb_factor = max(0.2, 1 - ev['orb_min'] / 5.0)

        # Учитываем фазу: сходящийся важнее расходящегося
        phase_factor = 1.2 if ev['phase'] == 'applying' else 0.9

        # Учитываем, активен ли сегодня (для дневного прогноза)
        is_active_today = ev['entry_date'] <= target_date <= ev['exit_date']
        active_factor = 1.0
        if is_active_today:
            # Если точная дата сегодня, бонус
            if ev['exact_date'] == target_date:
                active_factor = 1.5
            else:
                active_factor = 1.2

        # Если аспект к углу – бонус
        angle_factor = 1.2 if ev['is_angle'] else 1.0

        score = base_score * orb_factor * phase_factor * active_factor * angle_factor
        return score

    def _filter_events(self, events: List[Dict], period_type: str, target_date: datetime) -> List[Dict]:
        """
        Фильтрует события по группам и скорингу.
        Возвращает отсортированный список с оценкой значимости.
        """
        # Сначала оставляем только те, которые попадают в нужный период
        if period_type == 'today':
            filtered = []
            for ev in events:
                # Событие должно быть активным сегодня
                if not (ev['entry_date'] <= target_date <= ev['exit_date']):
                    continue
                # Проверяем группу
                planet = ev['transit_planet']
                if planet in self.GROUP_A:
                    filtered.append(ev)
                elif planet in self.GROUP_B:
                    if ev['orb_min'] <= self.FAST_PLANET_DAY_ORB or ev['natal_target'] in ['Sun', 'Moon', 'ASC', 'MC']:
                        filtered.append(ev)
                elif planet in self.GROUP_C:
                    if ev['orb_min'] <= 0.5 and ev['natal_target'] in ['Sun', 'Moon', 'ASC', 'MC']:
                        filtered.append(ev)
        elif period_type == 'month':
            filtered = []
            for ev in events:
                planet = ev['transit_planet']
                if planet in self.GROUP_A:
                    filtered.append(ev)
                elif planet in self.GROUP_B:
                    if ev['orb_min'] <= self.FAST_PLANET_MONTH_ORB:
                        filtered.append(ev)
                # Луну не включаем
        else:  # year
            filtered = []
            for ev in events:
                planet = ev['transit_planet']
                if planet in self.GROUP_A:
                    filtered.append(ev)
                elif planet in self.GROUP_B:
                    if ev['orb_min'] <= self.FAST_PLANET_YEAR_ORB and ev['natal_target'] in ['Sun', 'Moon', 'ASC', 'MC']:
                        filtered.append(ev)

        # Вычисляем score для каждого события
        for ev in filtered:
            ev['score'] = self._score_event(ev, target_date)

        # Сортируем по убыванию score
        filtered.sort(key=lambda x: x['score'], reverse=True)

        # Ограничиваем количество
        if period_type == 'today':
            max_events = self.MAX_EVENTS_DAY
        elif period_type == 'month':
            max_events = self.MAX_EVENTS_MONTH
        else:
            max_events = self.MAX_EVENTS_YEAR

        return filtered[:max_events]

    # ---------- ГРУППИРОВКА ОСЕЙ ----------

    def _group_axis_events(self, events: List[Dict]) -> List[Dict]:
        """
        Группирует события для осей ASC/DSC и MC/IC.
        Возвращает список событий, где для осей создаётся одно событие с пометкой 'axis'.
        """
        # Реализуем позже, если потребуется
        # Пока просто возвращаем как есть, но в выводе можно будет объединить
        return events

    # ---------- ПОСТРОЕНИЕ КОНТЕКСТА ----------

    def build_context(self, period: str = 'today',
                      target_date: Optional[datetime] = None) -> str:
        if target_date is None:
            target_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        if period == 'today':
            start = target_date - timedelta(days=1)
            end = target_date + timedelta(days=1)
        elif period == 'month':
            start = target_date.replace(day=1)
            next_month = start + timedelta(days=32)
            end = next_month.replace(day=1) - timedelta(seconds=1)
        else:  # year
            start = target_date.replace(month=1, day=1)
            end = target_date.replace(month=12, day=31)

        # Сканируем
        all_events = self._scan_period(start, end)

        # Фильтруем и сортируем
        filtered = self._filter_events(all_events, period, target_date)

        # Группируем оси
        filtered = self._group_axis_events(filtered)

        # Формируем текст
        lines = []

        # Заголовок
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
        for angle in ['ASC', 'MC', 'DSC', 'IC']:
            if angle in self.natal_angles:
                a = self.natal_angles[angle]
                if a:
                    sign = NatalContextBuilder.SIGN_MAP.get(a['sign'], a['sign'])
                    pos = a['position']
                    lines.append(f"{angle}: {sign} {pos:.2f}°")
        lines.append("")
        for p in self.natal_planets:
            if p['name'] in ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                             'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']:
                sign = NatalContextBuilder.SIGN_MAP.get(p['sign'], p['sign'])
                pos = p['degree']
                house = p['house']
                retro = p['retrograde']
                line = f"{p['name']}: {sign} {pos:.2f}°, {house} дом"
                if retro:
                    line += ", ретроградный"
                lines.append(line)
        lines.append("")

        # Транзиты
        if not filtered:
            lines.append("### Основные транзиты")
            lines.append("")
            lines.append("Нет значимых транзитов в указанный период.")
        else:
            lines.append("### Основные транзиты")
            lines.append("")
            for ev in filtered:
                planet = ev['transit_planet']
                target = ev['natal_target']
                aspect = ev['aspect']
                orb = ev['orb_min']
                phase = ev['phase']
                transit_house = ev['transit_house']
                natal_house = ev['natal_house']

                # Переводим названия
                aspect_name = NatalContextBuilder.ASPECT_MAP.get(aspect, aspect)
                phase_text = "сходящийся" if phase == 'applying' else "расходящийся" if phase == 'separating' else ""

                line = f"{planet} транзитный — {aspect_name} — натальное {target}"
                if phase_text:
                    line += f", орб {orb:.2f}°, {phase_text}"
                else:
                    line += f", орб {orb:.2f}°"
                lines.append(line)

                if transit_house:
                    lines.append(f"Транзитная планета активирует {transit_house} дом")
                if natal_house:
                    lines.append(f"Натальный {target} находится в {natal_house} доме")

                # Проверяем, активен ли сегодня (для дневного прогноза)
                if period == 'today':
                    is_active_today = ev['entry_date'] <= target_date <= ev['exit_date']
                    if is_active_today and ev['exact_date'] == target_date:
                        lines.append(f"Пик влияния: сегодня")
                    elif is_active_today:
                        days_to_exact = (ev['exact_date'] - target_date).days
                        if days_to_exact >= 0:
                            lines.append(f"Пик влияния: через {days_to_exact} дн.")
                        else:
                            lines.append(f"Пик влияния: был {abs(days_to_exact)} дн. назад")
                else:
                    if ev['entry_date'] and ev['exit_date']:
                        lines.append(f"Период: {ev['entry_date'].strftime('%d.%m.%Y')} – {ev['exit_date'].strftime('%d.%m.%Y')}")
                    if ev['exact_date']:
                        lines.append(f"Точная дата: {ev['exact_date'].strftime('%d.%m.%Y')}")
                lines.append("")

        return "\n".join(lines)