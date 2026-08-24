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
            emulation_mode=False  # натальная карта строится всегда
        )
        self.natal_data = self.astro_calc._build_natal_chart()
        self.subject = self.astro_calc._subject

        # Сохраняем натальные планеты и углы для быстрого доступа
        self.natal_planets = self.natal_data['planets']
        self.natal_angles = self.natal_data['angles']
        self.natal_houses = self.natal_data['houses']

        # Список натальных целей: планеты + углы + узлы + Хирон + True_Lilith (если есть)
        self.natal_targets = []
        # Основные планеты
        main_names = {'Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                      'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto'}
        for p in self.natal_planets:
            if p['name'] in main_names:
                self.natal_targets.append(p)
        # Углы
        angle_names = ['ASC', 'MC', 'DSC', 'IC']
        for name in angle_names:
            if name in self.natal_angles and self.natal_angles[name] is not None:
                self.natal_targets.append({
                    'name': name,
                    'sign': self.natal_angles[name]['sign'],
                    'position': self.natal_angles[name]['position'],
                    'house': None,
                    'retrograde': False,
                    'is_angle': True
                })
        # Узлы, Хирон, True_Lilith (если есть)
        extra_names = {'True_North_Lunar_Node', 'True_South_Lunar_Node', 'Chiron', 'True_Lilith'}
        for p in self.natal_planets:
            if p['name'] in extra_names:
                self.natal_targets.append(p)

        # Кеш для транзитных позиций
        self._position_cache = {}

    # ---------- ПОЛУЧЕНИЕ ТРАНЗИТНЫХ ПОЗИЦИЙ ----------

    def _get_transit_subject(self, date: datetime) -> AstrologicalSubject:
        """Создаёт субъект для транзитов на указанную дату (UTC)."""
        # Используем натальные координаты, но время транзита
        # Для транзитов мы используем те же координаты, что и в натальной карте
        lat = self.natal_data['location']['lat']
        lng = self.natal_data['location']['lng']
        # Время – переданное UTC
        # В Kerykeion tz_str должен быть "UTC", так как мы передаём UTC время
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
        """
        Возвращает позиции транзитных планет на указанную дату.
        Кеширует по дате (по дням).
        """
        key = date.strftime('%Y-%m-%d')
        if key in self._position_cache:
            return self._position_cache[key]

        subject = self._get_transit_subject(date)
        model = subject.model() if callable(subject.model) else subject.model
        data = model.dict() if hasattr(model, 'dict') else model.__dict__

        planets = {}
        # Извлекаем все нужные планеты
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
        """Определяет натальный дом для транзитной планеты."""
        if not self.natal_houses:
            return 0
        # Сортируем куспиды по градусу
        sorted_houses = sorted(self.natal_houses, key=lambda h: h['degree'])
        # Ищем дом
        for i, h in enumerate(sorted_houses):
            next_house = sorted_houses[(i + 1) % len(sorted_houses)]
            start = h['degree']
            end = next_house['degree']
            if end < start:
                if longitude >= start or longitude < end:
                    return i + 1  # номер дома (1-12)
            else:
                if start <= longitude < end:
                    return i + 1
        return 0

    # ---------- РАСЧЁТ АСПЕКТОВ ----------

    def _calculate_aspect(self, lon1: float, lon2: float) -> Optional[Tuple[str, float]]:
        """Возвращает (тип аспекта, орб) или None, если нет аспекта."""
        diff = abs(lon1 - lon2) % 360
        if diff > 180:
            diff = 360 - diff
        # Проверяем основные аспекты
        targets = {
            'conjunction': 0,
            'opposition': 180,
            'trine': 120,
            'square': 90,
            'sextile': 60,
        }
        for aspect, angle in targets.items():
            orb = abs(diff - angle)
            if orb <= 5.0:  # предварительный фильтр, реальный орб будет проверяться позже
                return aspect, orb
        return None

    def _get_transit_aspects(self, date: datetime, target_date: datetime = None,
                             period_type: str = 'today') -> List[Dict]:
        """
        Получает все транзитные аспекты на указанную дату (или диапазон).
        Для диапазона использует сканирование по дням и собирает события.
        """
        if period_type == 'today':
            # Для дня: берём одну дату
            aspects = self._get_aspects_for_day(date)
            return aspects
        elif period_type == 'month':
            # Для месяца: сканируем все дни в диапазоне
            start = date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            # Определяем последний день месяца
            next_month = start + timedelta(days=32)
            end = next_month.replace(day=1) - timedelta(seconds=1)
            return self._scan_period(start, end, period_type)
        else:  # year
            start = date.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            end = date.replace(month=12, day=31, hour=23, minute=59, second=59)
            return self._scan_period(start, end, period_type)

    def _get_aspects_for_day(self, date: datetime) -> List[Dict]:
        """Возвращает транзитные аспекты на конкретную дату."""
        transit_positions = self._get_transit_positions(date)
        aspects = []
        for t_planet, t_data in transit_positions.items():
            t_lon = t_data['longitude']
            t_house = t_data['house']
            t_retro = t_data['retrograde']
            t_speed = t_data['speed']

            for target in self.natal_targets:
                n_lon = target['position']
                aspect_info = self._calculate_aspect(t_lon, n_lon)
                if not aspect_info:
                    continue
                aspect_type, orb = aspect_info

                # Определяем, какой орб использовать
                if target.get('is_angle'):
                    max_orb = self.ANGLE_ORBS.get(aspect_type, 2.0)
                elif target['name'] in ('True_North_Lunar_Node', 'True_South_Lunar_Node', 'Chiron'):
                    max_orb = self.EXTRA_ORBS.get(aspect_type, 2.0)
                else:
                    max_orb = self.PLANET_ORBS.get(aspect_type, 3.0)

                # Луна: особый орб
                if t_planet == 'Moon':
                    max_orb = self.MOON_ORB

                if orb > max_orb:
                    continue

                # Проверяем применимость по приоритету (для годового/месячного фильтрация позже)
                # Определяем applying/separating
                # Используем aspect_movement из Kerykeion, но у нас нет отдельного объекта аспекта,
                # поэтому вычислим по изменению орба на ±1 день.
                # Для точности мы можем вычислить фазу позже, при сканировании.
                # Пока сохраним все данные.
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
        """
        Сканирует период с шагом 1 день и собирает все значимые транзиты,
        затем группирует по проходам и вычисляет даты входа/выхода.
        Возвращает список событий с полной информацией.
        """
        # Шаг 1: собираем все дни и аспекты
        daily_aspects = []
        current = start
        while current <= end:
            aspects = self._get_aspects_for_day(current)
            for a in aspects:
                a['date'] = current
                daily_aspects.append(a)
            current += timedelta(days=1)

        # Шаг 2: группируем по (transit_planet, natal_target, aspect)
        groups = {}
        for a in daily_aspects:
            key = (a['transit_planet'], a['natal_target'], a['aspect'])
            if key not in groups:
                groups[key] = []
            groups[key].append(a)

        # Шаг 3: для каждой группы определяем периоды входа/выхода и точные даты
        events = []
        for key, items in groups.items():
            if not items:
                continue
            t_planet, n_target, aspect = key
            # Сортируем по дате
            items_sorted = sorted(items, key=lambda x: x['date'])
            # Определяем непрерывные периоды, когда аспект активен (орб <= max_orb)
            # Для этого нужно знать максимальный орб для этого типа
            # Определим по первому элементу
            first = items_sorted[0]
            if first['target_is_angle']:
                max_orb = self.ANGLE_ORBS.get(aspect, 2.0)
            elif n_target in ('True_North_Lunar_Node', 'True_South_Lunar_Node', 'Chiron'):
                max_orb = self.EXTRA_ORBS.get(aspect, 2.0)
            else:
                max_orb = self.PLANET_ORBS.get(aspect, 3.0)
            if t_planet == 'Moon':
                max_orb = self.MOON_ORB

            # Найдём интервалы, где орб <= max_orb
            # Простой подход: проходим по дням и ищем непрерывные сегменты
            segments = []
            current_segment = []
            for i, item in enumerate(items_sorted):
                if item['orb'] <= max_orb:
                    if not current_segment:
                        current_segment.append(item)
                    else:
                        # Проверяем, не разрыв ли по дате (больше 1 дня)
                        prev = current_segment[-1]
                        if (item['date'] - prev['date']).days <= 1:
                            current_segment.append(item)
                        else:
                            # Сохраняем предыдущий сегмент, если он содержит больше 1 записи
                            if len(current_segment) >= 2:
                                segments.append(current_segment)
                            current_segment = [item]
                else:
                    if len(current_segment) >= 2:
                        segments.append(current_segment)
                    current_segment = []
            if len(current_segment) >= 2:
                segments.append(current_segment)

            # Для каждого сегмента определяем вход, выход, точную дату
            for seg in segments:
                if len(seg) < 2:
                    continue
                # Находим день с минимальным орбом (точный аспект)
                min_orb_item = min(seg, key=lambda x: x['orb'])
                exact_date = min_orb_item['date']
                # Вход в орб: первый день сегмента
                entry_date = seg[0]['date']
                # Выход из орба: последний день сегмента
                exit_date = seg[-1]['date']

                # Уточняем точную дату бинарным поиском (улучшаем до часа)
                # Для простоты пока оставим как есть, позже можно реализовать уточнение

                # Определяем фазу (применяется/расходится) по изменению орба
                # Если орб уменьшается до точного → applying, увеличивается после → separating
                # Для простоты возьмём направление изменения орба вокруг точной даты
                # (можно использовать скорость или просто сравнить орб до и после)
                phase = 'applying' if min_orb_item.get('phase') == 'applying' else 'separating'
                # В реальности мы можем определить по изменению орба на соседних днях
                # Здесь для простоты оставим как есть.

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

    # ---------- ФИЛЬТРАЦИЯ ПО ПРИОРИТЕТУ ----------

    def _filter_events(self, events: List[Dict], period_type: str, target_date: datetime = None) -> List[Dict]:
        """
        Фильтрует события в зависимости от типа прогноза и приоритетов.
        """
        # Если день: оставляем все события, но дополнительно фильтруем по орбу и приоритету
        if period_type == 'today':
            # Оставляем только те, у которых дата точного аспекта == target_date (или орб <= макс)
            # Но мы уже отфильтровали по орбу, так что просто оставляем все, относящиеся к этому дню
            # Для дня мы хотим показать все активные транзиты, включая долгосрочные, которые действуют в этот день
            # Поэтому фильтруем по тому, что точная дата попадает в интервал [target_date - 1, target_date + 1]
            # У нас уже есть точные даты.
            filtered = []
            for ev in events:
                # Проверяем, пересекается ли период действия с целевой датой
                if ev['entry_date'] <= target_date <= ev['exit_date']:
                    filtered.append(ev)
            return filtered

        elif period_type == 'month':
            # Для месяца: оставляем события групп A и B (и C только если очень точные)
            filtered = []
            for ev in events:
                planet = ev['transit_planet']
                if planet in self.GROUP_A or planet in self.GROUP_B:
                    filtered.append(ev)
                elif planet in self.GROUP_C:
                    # Луна: только если орб <= 0.5° или аспект к важному объекту (Солнце, Луна, ASC, MC)
                    if ev['orb_min'] <= 0.5 or ev['natal_target'] in ('Sun', 'Moon', 'ASC', 'MC'):
                        filtered.append(ev)
            return filtered

        else:  # year
            # Для года: только группа A + очень точные из B (орб <= 0.5 и важные объекты)
            filtered = []
            for ev in events:
                planet = ev['transit_planet']
                if planet in self.GROUP_A:
                    filtered.append(ev)
                elif planet in self.GROUP_B:
                    if ev['orb_min'] <= 0.5 and ev['natal_target'] in ('Sun', 'Moon', 'ASC', 'MC'):
                        filtered.append(ev)
                # Group C не попадает в годовой прогноз
            return filtered

    # ---------- ПОСТРОЕНИЕ КОНТЕКСТА ----------

    def build_context(self, period: str = 'today',
                      start_date: Optional[datetime] = None,
                      end_date: Optional[datetime] = None,
                      target_date: Optional[datetime] = None) -> str:
        """
        Основной метод: возвращает контекст для гороскопа.
        period: 'today', 'month', 'year'
        """
        if not start_date or not end_date or not target_date:
            # Определяем автоматически
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
            else:  # year
                now = datetime.now(timezone.utc)
                target_date = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
                start_date = target_date
                end_date = target_date.replace(month=12, day=31, hour=23, minute=59, second=59)

        # Получаем события
        all_events = self._scan_period(start_date, end_date, period)
        # Фильтруем
        filtered_events = self._filter_events(all_events, period, target_date)

        # Формируем текстовый контекст
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

        # Натальные данные (можно переиспользовать NatalContextBuilder, но только основные данные)
        # Для компактности выведем только планеты и углы
        lines.append("### Натальные данные")
        lines.append("")
        # Углы
        for angle_name in ['ASC', 'MC', 'DSC', 'IC']:
            angle = self.natal_angles.get(angle_name)
            if angle:
                sign = NatalContextBuilder.SIGN_MAP.get(angle.get('sign'), angle.get('sign'))
                pos = angle.get('position', 0.0)
                lines.append(f"{angle_name}: {sign} {pos:.2f}°")
        lines.append("")
        # Планеты (основные 10)
        planet_order = ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                        'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']
        for name in planet_order:
            planet = next((p for p in self.natal_planets if p['name'] == name), None)
            if planet:
                sign = NatalContextBuilder.SIGN_MAP.get(planet['sign'], planet['sign'])
                pos = planet['position']
                house = planet['house']
                retro = planet['retrograde']
                line = f"{name}: {sign} {pos:.2f}°, {house} дом"
                if retro:
                    line += ", ретроградный"
                lines.append(line)
        lines.append("")

        # Транзиты
        if not filtered_events:
            lines.append("### Активные транзиты")
            lines.append("")
            lines.append("Нет значимых транзитов в указанный период.")
            lines.append("")
        else:
            # Сортируем по важности (приоритет планет, затем по точной дате)
            filtered_events.sort(key=lambda x: (self.PLANET_PRIORITY.get(x['transit_planet'], 0),
                                                x['exact_date']), reverse=True)

            # Выводим основные транзиты
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

                # Преобразуем названия
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
                # Период и точная дата
                if ev['entry_date'] and ev['exit_date']:
                    lines.append(f"Период: {ev['entry_date'].strftime('%d.%m.%Y')} – {ev['exit_date'].strftime('%d.%m.%Y')}")
                if ev['exact_date']:
                    lines.append(f"Точная дата: {ev['exact_date'].strftime('%d.%m.%Y')}")
                lines.append("")

            # Дополнительно: если есть повторные прохождения, вывести их отдельно
            # Для простоты пропустим, но в будущем можно добавить

        return "\n".join(lines)

    # ---------- ВСПОМОГАТЕЛЬНЫЕ ----------

    def get_transit_periods(self) -> Dict[str, List[Dict]]:
        """Возвращает словарь с периодами транзитов для использования в хендлере."""
        # Можно использовать для дополнительной группировки
        pass