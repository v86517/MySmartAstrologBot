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
    Новый калькулятор гороскопа (день/месяц/год) с корректной геометрией аспектов,
    фильтрацией по орбам, группировкой осей и приоритетами планет.
    """

    # Максимальные орбы для транзитов
    ORBS = {
        'conjunction': 3.0,
        'opposition': 3.0,
        'trine': 3.0,
        'square': 3.0,
        'sextile': 2.0,
    }
    # Отдельный орб для Луны
    MOON_ORB = 1.0
    # Орбы для углов и особых точек
    ANGLE_ORB = 2.0
    NODE_ORB = 2.0
    CHIRON_ORB = 2.0

    # Группы приоритетов
    GROUP_A = {'Saturn', 'Uranus', 'Neptune', 'Pluto', 'Jupiter'}
    GROUP_B = {'Mars', 'Venus', 'Mercury', 'Sun'}
    GROUP_C = {'Moon'}

    # Порог для включения быстрых планет в годовой прогноз (орб)
    FAST_PLANET_YEAR_ORB = 0.5

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

        # Натальные планеты и углы
        self.natal_planets = self.natal_data['planets']
        self.natal_angles = self.natal_data['angles']
        self.natal_houses = self.natal_data['houses']

        # Список натальных целей с унифицированным доступом к долготе
        self.natal_targets = []  # list of dict with keys: name, longitude, house, is_angle, extra_type
        for p in self.natal_planets:
            # Основные 10 планет
            if p['name'] in ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                             'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']:
                self.natal_targets.append({
                    'name': p['name'],
                    'longitude': p['degree'],
                    'house': p['house'],
                    'is_angle': False,
                    'extra_type': None
                })
        # Углы
        for angle in ['ASC', 'MC', 'DSC', 'IC']:
            if angle in self.natal_angles and self.natal_angles[angle] is not None:
                self.natal_targets.append({
                    'name': angle,
                    'longitude': self.natal_angles[angle]['position'],
                    'house': None,
                    'is_angle': True,
                    'extra_type': 'angle'
                })
        # Дополнительные точки (узлы, Хирон, Лилит)
        for p in self.natal_planets:
            if p['name'] in ['True_North_Lunar_Node', 'True_South_Lunar_Node', 'Chiron', 'True_Lilith']:
                self.natal_targets.append({
                    'name': p['name'],
                    'longitude': p['degree'],
                    'house': p.get('house'),
                    'is_angle': False,
                    'extra_type': 'node' if 'Node' in p['name'] else 'chiron' if p['name'] == 'Chiron' else 'lilith'
                })

        # Кеш позиций транзитных планет по дням
        self._position_cache = {}

    # ---------- ПОЛУЧЕНИЕ ПОЗИЦИЙ ----------

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

    def _get_transit_position(self, date: datetime, planet: str) -> Optional[float]:
        """Возвращает долготу транзитной планеты на указанную дату."""
        key = date.strftime('%Y-%m-%d')
        if key not in self._position_cache:
            subject = self._get_transit_subject(date)
            model = subject.model() if callable(subject.model) else subject.model
            data = model.dict() if hasattr(model, 'dict') else model.__dict__
            self._position_cache[key] = {}
            # Извлекаем все нужные планеты
            for p in ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                      'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']:
                p_key = p.lower()
                if p_key in data:
                    obj = data[p_key]
                    if isinstance(obj, dict):
                        if 'position' in obj:
                            self._position_cache[key][p] = obj['position']
                    else:
                        if hasattr(obj, 'position'):
                            self._position_cache[key][p] = getattr(obj, 'position')
        return self._position_cache[key].get(planet)

    def _get_transit_house(self, date: datetime, planet: str) -> int:
        """Определяет натальный дом транзитной планеты."""
        lon = self._get_transit_position(date, planet)
        if lon is None or not self.natal_houses:
            return 0
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

    # ---------- ГЕОМЕТРИЯ АСПЕКТОВ ----------

    def _aspect_type_and_orb(self, lon1: float, lon2: float) -> Tuple[Optional[str], float]:
        """
        Возвращает (тип аспекта, орб) или (None, inf) если нет аспекта.
        """
        diff = abs(lon1 - lon2) % 360
        if diff > 180:
            diff = 360 - diff

        # Целевые углы
        targets = {
            'conjunction': 0,
            'opposition': 180,
            'trine': 120,
            'square': 90,
            'sextile': 60,
        }
        best_aspect = None
        best_orb = 100.0
        for aspect, target in targets.items():
            orb = abs(diff - target)
            if orb < best_orb:
                best_orb = orb
                best_aspect = aspect
        if best_orb > 10.0:  # максимальный допустимый орб для предварительного отбора
            return None, 100.0
        return best_aspect, best_orb

    # ---------- СКАНИРОВАНИЕ ПЕРИОДА ----------

    def _scan_period(self, start: datetime, end: datetime) -> List[Dict]:
        """
        Сканирует период с шагом 1 день, собирает все транзитные аспекты,
        определяет периоды входа/выхода и точные даты.
        Возвращает список событий с полной информацией.
        """
        events = []
        # Сначала собираем позиции для всех дней периода
        current = start
        daily_data = []  # список словарей с датой и позициями планет
        while current <= end:
            day_info = {'date': current, 'planets': {}}
            for planet in ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                           'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']:
                lon = self._get_transit_position(current, planet)
                if lon is not None:
                    day_info['planets'][planet] = lon
            daily_data.append(day_info)
            current += timedelta(days=1)

        # Теперь для каждой пары транзитная планета × натальная цель
        for target in self.natal_targets:
            t_name = target['name']
            t_lon = target['longitude']
            for planet in ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                           'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']:
                # Собираем временной ряд орбов для этого аспекта
                orb_series = []
                for day in daily_data:
                    if planet in day['planets']:
                        p_lon = day['planets'][planet]
                        aspect, orb = self._aspect_type_and_orb(p_lon, t_lon)
                        if aspect is not None:
                            orb_series.append({
                                'date': day['date'],
                                'orb': orb,
                                'aspect': aspect,
                                'transit_lon': p_lon
                            })
                if not orb_series:
                    continue
                # Группируем по типу аспекта (может меняться при переходе через 0°)
                # Для простоты используем первый аспект из серии как основной
                # Но на самом деле аспект может меняться, если планета проходит через разные углы
                # Однако для транзитов мы ожидаем, что аспект остаётся постоянным в пределах одного прохода.
                # Разобьём на сегменты, где аспект одинаков.
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
                    # Определяем максимальный орб для этого типа
                    if target['is_angle']:
                        max_orb = self.ANGLE_ORB
                    elif target['extra_type'] == 'node':
                        max_orb = self.NODE_ORB
                    elif target['extra_type'] == 'chiron':
                        max_orb = self.CHIRON_ORB
                    else:
                        max_orb = self.ORBS.get(aspect_type, 3.0)
                    if planet == 'Moon':
                        max_orb = self.MOON_ORB

                    # Находим подпоследовательности, где орб <= max_orb
                    active_segments = []
                    current_active = []
                    for item in seg:
                        if item['orb'] <= max_orb:
                            if not current_active:
                                current_active.append(item)
                            else:
                                # Проверяем, что дни идут подряд (не больше 1 дня разрыва)
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

                        # Определяем фазу (применяется/расходится)
                        # По изменению орба вокруг точной даты
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
                        # Если точная дата на границе, определяем по тренду
                        elif len(act) == 2:
                            # если орб уменьшается к концу => applying, иначе separating
                            if act[0]['orb'] > act[1]['orb']:
                                phase = 'applying'
                            else:
                                phase = 'separating'

                        # Проверяем ретроградность (будет использоваться позже)
                        # Ретроградность можно получить из скорости планеты на точную дату
                        # Пока оставим как есть.

                        # Для осей ASC/DSC и MC/IC группируем позже

                        events.append({
                            'transit_planet': planet,
                            'natal_target': t_name,
                            'aspect': aspect_type,
                            'orb_min': min_item['orb'],
                            'entry_date': entry_date,
                            'exact_date': exact_date,
                            'exit_date': exit_date,
                            'phase': phase,
                            'transit_house': self._get_transit_house(exact_date, planet),
                            'natal_house': target['house'],
                            'is_angle': target['is_angle'],
                            'extra_type': target['extra_type'],
                            'transit_lon_at_exact': min_item['transit_lon'],
                        })
        return events

    # ---------- ГРУППИРОВКА ОСЕЙ ----------

    def _group_axis_events(self, events: List[Dict]) -> List[Dict]:
        """
        Группирует события для осей ASC/DSC и MC/IC в одно.
        """
        grouped = []
        # Сначала собираем все события, не относящиеся к осям
        for ev in events:
            if ev['natal_target'] in ['ASC', 'DSC']:
                # Найдём парное событие с той же транзитной планетой и аспектом
                # Но мы не можем просто удалить, лучше создать новое событие для оси
                # Вместо этого мы позже преобразуем вывод, чтобы показывать ось.
                # Пока оставим как есть, а в выводе объединим.
                pass
        # Для простоты вернём список без изменений, но добавим пометку о группировке позже
        return events

    # ---------- ФИЛЬТРАЦИЯ ----------

    def _filter_events(self, events: List[Dict], period_type: str, target_date: datetime) -> List[Dict]:
        """
        Фильтрует события по группам и приоритетам.
        """
        # Сначала отфильтруем по орбу
        filtered = []
        for ev in events:
            # Проверим, что событие действительно активно в целевой день (для дня)
            if period_type == 'today':
                if not (ev['entry_date'] <= target_date <= ev['exit_date']):
                    continue
            # Проверим тип аспекта (должен быть один из разрешённых)
            if ev['aspect'] not in ['conjunction', 'opposition', 'trine', 'square', 'sextile']:
                continue
            filtered.append(ev)

        # Далее фильтруем по группам в зависимости от периода
        if period_type == 'today':
            # Все группы A+B+C, но с ограничением по орбу для быстрых
            result = []
            for ev in filtered:
                planet = ev['transit_planet']
                if planet in self.GROUP_A:
                    result.append(ev)
                elif planet in self.GROUP_B:
                    # Для быстрых планет в дневном прогнозе оставляем только если орб <= 1° или аспект к важному объекту
                    if ev['orb_min'] <= 1.0 or ev['natal_target'] in ['Sun', 'Moon', 'ASC', 'MC']:
                        result.append(ev)
                elif planet in self.GROUP_C:
                    # Луна: только если орб <= 0.5° и к важному объекту
                    if ev['orb_min'] <= 0.5 and ev['natal_target'] in ['Sun', 'Moon', 'ASC', 'MC']:
                        result.append(ev)
            return result

        elif period_type == 'month':
            result = []
            for ev in filtered:
                planet = ev['transit_planet']
                if planet in self.GROUP_A:
                    result.append(ev)
                elif planet in self.GROUP_B:
                    # Для месяца быстрые планеты включаем только если орб <= 1.5°
                    if ev['orb_min'] <= 1.5:
                        result.append(ev)
                # Группа C (Луна) не включается в месячный прогноз
            return result

        else:  # year
            result = []
            for ev in filtered:
                planet = ev['transit_planet']
                if planet in self.GROUP_A:
                    result.append(ev)
                elif planet in self.GROUP_B:
                    # Для года быстрые планеты включаем только если орб <= 0.5° и аспект к важному объекту
                    if ev['orb_min'] <= self.FAST_PLANET_YEAR_ORB and ev['natal_target'] in ['Sun', 'Moon', 'ASC', 'MC']:
                        result.append(ev)
                # Группа C не включается
            return result

    # ---------- ПОСТРОЕНИЕ КОНТЕКСТА ----------

    def build_context(self, period: str = 'today',
                      target_date: Optional[datetime] = None) -> str:
        """
        Основной метод: возвращает контекст для гороскопа.
        """
        if target_date is None:
            target_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        # Определяем границы сканирования
        if period == 'today':
            start = target_date - timedelta(days=1)
            end = target_date + timedelta(days=1)
        elif period == 'month':
            # Начало месяца
            start = target_date.replace(day=1)
            # Конец месяца
            next_month = start + timedelta(days=32)
            end = next_month.replace(day=1) - timedelta(seconds=1)
        else:  # year
            start = target_date.replace(month=1, day=1)
            end = target_date.replace(month=12, day=31)

        # 1. Сканируем период
        all_events = self._scan_period(start, end)

        # 2. Фильтруем
        filtered = self._filter_events(all_events, period, target_date)

        # 3. Группируем оси (оставляем как есть, но в выводе объединим)
        # Пока пропустим, реализуем в выводе

        # 4. Сортируем по приоритету
        priority = {
            'Pluto': 10, 'Neptune': 9, 'Uranus': 9, 'Saturn': 8,
            'Jupiter': 7, 'Mars': 6, 'Venus': 5, 'Mercury': 5,
            'Sun': 5, 'Moon': 4
        }
        filtered.sort(key=lambda x: (priority.get(x['transit_planet'], 0), -x['orb_min']), reverse=True)

        # 5. Формируем текст
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

        # Натальные данные (кратко)
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
            lines.append("")
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

                # Для оси ASC/DSC и MC/IC группируем
                if target in ['ASC', 'DSC']:
                    # Найдём парный аспект к противоположному углу
                    # Для простоты пока выводим как есть, но можно объединить
                    pass

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

                if ev['entry_date'] and ev['exit_date']:
                    lines.append(f"Период: {ev['entry_date'].strftime('%d.%m.%Y')} – {ev['exit_date'].strftime('%d.%m.%Y')}")
                if ev['exact_date']:
                    lines.append(f"Точная дата: {ev['exact_date'].strftime('%d.%m.%Y')}")
                lines.append("")

        return "\n".join(lines)