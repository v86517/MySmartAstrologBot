# bot/calculators/context_builder.py
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict
import math

logger = logging.getLogger(__name__)


class AstrologyContextBuilder:
    """
    Класс для построения контекста для трёх типов прогнозов: ДЕНЬ, МЕСЯЦ, ГОД.
    Реализует три независимых фильтра с дедупликацией, объединением процессов и текстовым выводом.
    """

    # Веса планет (транзитных)
    PLANET_WEIGHT = {
        'Pluto': 10, 'Neptune': 9, 'Uranus': 9, 'Saturn': 8,
        'Jupiter': 7, 'Mars': 6, 'Venus': 5, 'Mercury': 5,
        'Sun': 5, 'Moon': 4
    }

    # Веса натальных целей
    TARGET_WEIGHT = {
        'Sun': 10, 'Moon': 10, 'ASC': 10, 'MC': 9,
        'Mercury': 8, 'Venus': 8, 'Mars': 8, 'Saturn': 6,
        'Jupiter': 6, 'Uranus': 5, 'Neptune': 5, 'Pluto': 5,
        'Chiron': 3, 'NorthNode': 3, 'SouthNode': 3, 'Lilith': 2
    }

    # Веса аспектов
    ASPECT_WEIGHT = {
        'conjunction': 1.0,
        'opposition': 0.95,
        'square': 0.90,
        'trine': 0.80,
        'sextile': 0.65
    }

    # Фазы
    PHASE_WEIGHT = {
        'exact': 1.0,
        'applying': 0.95,
        'separating': 0.85
    }

    # Классы длительности
    DURATION_CLASS = {
        'event': (0, 1),
        'short': (2, 7),
        'medium': (8, 30),
        'long': (31, float('inf'))
    }

    # Лимиты
    DAY_MAX_EVENTS = 7
    MONTH_MAX_PROCESSES = 10
    MONTH_MAX_DATES = 10
    MONTH_MAX_INGRESSES = 7
    YEAR_MAX_PROCESSES = 12
    YEAR_MAX_PERIODS = 10
    YEAR_MAX_INGRESSES = 10

    # Семантические домены для тем
    THEME_DOMAINS = {
        'IDENTITY': ['Sun', 'ASC', 'self', 'personality'],
        'EMOTIONS': ['Moon', 'emotions', 'family', 'intuition'],
        'RELATIONSHIPS': ['Venus', '7th house', 'DSC', 'partnership'],
        'LOVE': ['Venus', 'love', 'beauty', 'values'],
        'COMMUNICATION': ['Mercury', 'communication', 'learning', 'intellect'],
        'CAREER': ['MC', '10th house', 'career', 'status'],
        'MONEY': ['2nd house', '8th house', 'finance', 'resources'],
        'FAMILY': ['4th house', 'IC', 'home', 'family'],
        'HEALTH': ['6th house', 'health', 'routine'],
        'CHANGE': ['Uranus', 'change', 'innovation', 'freedom'],
        'TRANSFORMATION': ['Pluto', 'transformation', 'power', 'depth'],
        'RESPONSIBILITY': ['Saturn', 'responsibility', 'discipline', 'structure'],
        'EXPANSION': ['Jupiter', 'growth', 'expansion', 'wisdom'],
        'INTUITION': ['Neptune', 'intuition', 'spirituality', 'illusion'],
        'HEALING': ['Chiron', 'healing', 'wound', 'teaching'],
        'SPIRITUALITY': ['Neptune', 'spirituality', 'intuition'],
        'ACTION': ['Mars', 'action', 'drive', 'conflict']
    }

    # Локализация
    PLANET_NAMES_RU = {
        'Sun': 'Солнце', 'Moon': 'Луна', 'Mercury': 'Меркурий',
        'Venus': 'Венера', 'Mars': 'Марс', 'Jupiter': 'Юпитер',
        'Saturn': 'Сатурн', 'Uranus': 'Уран', 'Neptune': 'Нептун',
        'Pluto': 'Плутон', 'Chiron': 'Хирон', 'Mean_Lilith': 'Лилит',
        'True_North_Lunar_Node': 'Северный узел', 'True_South_Lunar_Node': 'Южный узел'
    }
    ASPECT_NAMES_RU = {
        'conjunction': 'соединение',
        'opposition': 'оппозиция',
        'square': 'квадрат',
        'trine': 'трин',
        'sextile': 'секстиль'
    }
    THEME_NAMES_RU = {
        'IDENTITY': 'Идентичность',
        'EMOTIONS': 'Эмоции',
        'RELATIONSHIPS': 'Отношения',
        'LOVE': 'Любовь',
        'COMMUNICATION': 'Коммуникация',
        'CAREER': 'Карьера',
        'MONEY': 'Деньги',
        'FAMILY': 'Семья',
        'HEALTH': 'Здоровье',
        'CHANGE': 'Перемены',
        'TRANSFORMATION': 'Трансформация',
        'RESPONSIBILITY': 'Ответственность',
        'EXPANSION': 'Расширение',
        'INTUITION': 'Интуиция',
        'HEALING': 'Исцеление',
        'SPIRITUALITY': 'Духовность',
        'ACTION': 'Действие'
    }

    def __init__(self, user_data: Dict, natal_data: Dict, transit_data: Dict, lang: str = 'ru'):
        self.user_data = user_data
        self.natal_data = natal_data
        self.transit_data = transit_data
        self.lang = lang
        self.natal = natal_data.get('natal', {})
        self.planets = self.natal.get('planets', [])
        self.houses = self.natal.get('houses', [])
        self.aspects = self.natal.get('aspects', [])
        self.angles = self.natal.get('angles', {})
        self.transit_aspects = transit_data.get('transit_aspects', [])
        self.transit_angle_aspects = transit_data.get('transit_angle_aspects', [])
        self.transit_ingresses = transit_data.get('transit_ingresses', [])
        self.period = transit_data.get('period', 'today')
        self.start_utc = transit_data.get('start_utc')
        self.end_utc = transit_data.get('end_utc')

        self._normalized = None  # кеш нормализованных аспектов
        self._processes = None   # кеш объединённых процессов

    # ----- ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ -----

    def _format_planet(self, name: str) -> str:
        return self.PLANET_NAMES_RU.get(name, name)

    def _format_aspect(self, name: str) -> str:
        return self.ASPECT_NAMES_RU.get(name, name)

    def _format_theme(self, name: str) -> str:
        return self.THEME_NAMES_RU.get(name, name)

    def _get_orb_weight(self, orb: float) -> float:
        if orb <= 0.5:
            return 1.0
        elif orb <= 1.0:
            return 0.95
        elif orb <= 2.0:
            return 0.80
        elif orb <= 3.0:
            return 0.60
        elif orb <= 4.0:
            return 0.35
        else:
            return 0.0

    def _calculate_score(self, transit_planet: str, natal_target: str, aspect: str,
                         orb: float, phase: str, is_angle: bool = False) -> float:
        """Вычисляет скоринг для аспекта."""
        pw = self.PLANET_WEIGHT.get(transit_planet, 1)
        tw = self.TARGET_WEIGHT.get(natal_target, 1)
        aw = self.ASPECT_WEIGHT.get(aspect, 0.5)
        ow = self._get_orb_weight(orb)
        phw = self.PHASE_WEIGHT.get(phase, 0.8)
        base = pw * tw * aw * ow * phw
        if is_angle:
            base *= 1.2
        return base

    def _is_date_in_range(self, date_str: str, start: Optional[datetime], end: Optional[datetime]) -> bool:
        if not date_str or not start or not end:
            return False
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d').date()
            return start.date() <= dt <= end.date()
        except:
            return False

    def _is_same_day(self, date_str: str, target_date: datetime) -> bool:
        if not date_str:
            return False
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d').date()
            return dt == target_date.date()
        except:
            return False

    def _get_duration_days(self, start: str, end: str) -> int:
        try:
            s = datetime.strptime(start, '%Y-%m-%d')
            e = datetime.strptime(end, '%Y-%m-%d')
            return (e - s).days
        except:
            return 0

    def _get_duration_class(self, days: int) -> str:
        if days <= 1:
            return 'event'
        elif days <= 7:
            return 'short'
        elif days <= 30:
            return 'medium'
        else:
            return 'long'

    # ----- НОРМАЛИЗАЦИЯ -----

    def _normalize(self) -> List[Dict]:
        """Приводит все аспекты к единому формату."""
        if self._normalized is not None:
            return self._normalized

        all_aspects = self.transit_aspects + self.transit_angle_aspects
        normalized = []

        for asp in all_aspects:
            # Проверка обязательных полей
            if not asp.get('transit_planet') or not asp.get('aspect'):
                continue
            natal_target = asp.get('natal_planet') or asp.get('angle')
            if not natal_target:
                continue
            orb = asp.get('orb', 10.0)
            if orb > 8.0:  # отсекаем слишком большие орбы
                continue
            phase = asp.get('phase', '')
            exact_date = asp.get('exact_date')
            if not exact_date:
                continue

            # Определяем, является ли аспект угловым
            is_angle = 'angle' in asp
            score = self._calculate_score(asp['transit_planet'], natal_target,
                                          asp['aspect'], orb, phase, is_angle)

            normalized.append({
                'transit_planet': asp['transit_planet'],
                'natal_target': natal_target,
                'aspect': asp['aspect'],
                'orb': orb,
                'phase': phase,
                'exact_date': exact_date,
                'score': score,
                'is_angle': is_angle,
                'house': asp.get('transit_house'),
                'sign': asp.get('transit_sign'),
                'angle': asp.get('angle') if is_angle else None,
                'raw': asp
            })

        self._normalized = normalized
        return normalized

    # ----- РАСЧЁТ АКТИВНОГО ИНТЕРВАЛА -----

    def _calculate_active_interval(self, transit_planet: str, natal_target: str,
                                   aspect: str, peaks: List[str]) -> Dict:
        """
        Приближённо вычисляет активный интервал для процесса.
        Использует среднюю скорость планеты.
        """
        if not peaks:
            return {'start': None, 'end': None, 'duration': 0}

        # Сортируем пики
        peaks_sorted = sorted(peaks)
        first_peak = peaks_sorted[0]
        last_peak = peaks_sorted[-1]

        # Определяем среднюю скорость (градусов в день)
        avg_speeds = {
            'Pluto': 0.004, 'Neptune': 0.006, 'Uranus': 0.012,
            'Saturn': 0.033, 'Jupiter': 0.083, 'Mars': 0.524,
            'Sun': 0.986, 'Venus': 1.2, 'Mercury': 1.383, 'Moon': 13.176
        }
        speed = avg_speeds.get(transit_planet, 0.1)

        # Допустимый орб для медленных планет ~3°, для быстрых ~1°
        if transit_planet in ['Pluto', 'Neptune', 'Uranus', 'Saturn', 'Jupiter']:
            max_orb = 3.0
        else:
            max_orb = 1.0

        # Если скорость известна, оцениваем длительность
        if speed > 0:
            days_before = max_orb / speed
            days_after = max_orb / speed
        else:
            days_before = 2
            days_after = 2

        # Вычисляем start и end
        try:
            dt_first = datetime.strptime(first_peak, '%Y-%m-%d')
            dt_last = datetime.strptime(last_peak, '%Y-%m-%d')
            start_dt = dt_first - timedelta(days=days_before)
            end_dt = dt_last + timedelta(days=days_after)
            start = start_dt.strftime('%Y-%m-%d')
            end = end_dt.strftime('%Y-%m-%d')
            duration = (end_dt - start_dt).days
            return {'start': start, 'end': end, 'duration': duration}
        except:
            return {'start': first_peak, 'end': last_peak, 'duration': 0}

    # ----- ОБЪЕДИНЕНИЕ РЕТРОГРАДНЫХ ПРОХОДОВ -----

    def _merge_retrograde_passes(self, aspects: List[Dict]) -> List[Dict]:
        """Объединяет повторные проходы одного транзита в процессы."""
        # Группируем по (transit_planet, natal_target, aspect)
        groups = defaultdict(list)
        for asp in aspects:
            key = (asp['transit_planet'], asp['natal_target'], asp['aspect'])
            groups[key].append(asp)

        processes = []
        for key, items in groups.items():
            if not items:
                continue
            # Сортируем по дате
            items.sort(key=lambda x: x['exact_date'])
            peaks = [i['exact_date'] for i in items]
            # Находим пик с максимальным score
            best = max(items, key=lambda x: x['score'])
            # Вычисляем активный интервал
            interval = self._calculate_active_interval(
                best['transit_planet'], best['natal_target'],
                best['aspect'], peaks
            )
            # Усреднённый score
            avg_score = sum(i['score'] for i in items) / len(items)
            # Бонус за длительность
            duration_bonus = 1 + 0.3 * min(interval['duration'] / 30, 1.0)
            final_score = avg_score * duration_bonus

            # Определяем основную тему
            theme = self._assign_theme(best['transit_planet'], best['natal_target'])

            process = {
                'id': f"P{len(processes)+1:03d}",
                'transit_planet': best['transit_planet'],
                'natal_target': best['natal_target'],
                'aspect': best['aspect'],
                'active_from': interval['start'],
                'peak_dates': peaks,
                'active_to': interval['end'],
                'duration': interval['duration'],
                'score': final_score,
                'theme': theme,
                'is_angle': best.get('is_angle', False),
                'angle': best.get('angle'),
                'house': best.get('house'),
                'all_aspects': items
            }
            processes.append(process)

        return processes

    def _assign_theme(self, transit_planet: str, natal_target: str) -> str:
        """Присваивает тему на основе планет."""
        mapping = {
            'Pluto': 'TRANSFORMATION',
            'Neptune': 'INTUITION',
            'Uranus': 'CHANGE',
            'Saturn': 'RESPONSIBILITY',
            'Jupiter': 'EXPANSION',
            'Mars': 'ACTION',
            'Venus': 'LOVE',
            'Mercury': 'COMMUNICATION',
            'Sun': 'IDENTITY',
            'Moon': 'EMOTIONS'
        }
        # Сначала пробуем по натальной цели
        if natal_target in ['Sun', 'ASC']:
            return 'IDENTITY'
        if natal_target == 'Moon':
            return 'EMOTIONS'
        if natal_target in ['Venus', 'DSC']:
            return 'LOVE'
        if natal_target == 'Mercury':
            return 'COMMUNICATION'
        if natal_target in ['MC', 'Saturn']:
            return 'CAREER'
        # Иначе по транзитной
        return mapping.get(transit_planet, 'OTHER')

    # ----- ДЕДУПЛИКАЦИЯ ОСЕЙ -----

    def _deduplicate_axes(self, events: List[Dict]) -> List[Dict]:
        """Объединяет пары ASC/DSC и MC/IC в один блок."""
        axis_groups = defaultdict(list)
        others = []
        for e in events:
            target = e.get('natal_target')
            if target in ['ASC', 'DSC']:
                axis_groups[('ASC_DSC', e['transit_planet'], e['aspect'])].append(e)
            elif target in ['MC', 'IC']:
                axis_groups[('MC_IC', e['transit_planet'], e['aspect'])].append(e)
            else:
                others.append(e)

        merged = []
        for key, items in axis_groups.items():
            if len(items) == 1:
                merged.append(items[0])
            else:
                # Объединяем
                primary = max(items, key=lambda x: x['score'])
                combined = primary.copy()
                combined['natal_target'] = key[0]  # 'ASC_DSC' or 'MC_IC'
                combined['score'] = sum(i['score'] for i in items)  # не суммируем, а оставляем наибольший?
                # Лучше оставить score наиболее сильного контакта
                combined['score'] = primary['score']
                combined['supporting'] = [i for i in items if i is not primary]
                merged.append(combined)

        merged.extend(others)
        return merged

    # ----- ФИЛЬТРЫ -----

    def _filter_day(self) -> Dict[str, Any]:
        """Фильтр для дневного прогноза."""
        target_date = self.start_utc
        if not target_date:
            return {}

        normalized = self._normalize()
        # Фильтруем по дате
        day_aspects = [a for a in normalized if self._is_same_day(a['exact_date'], target_date)]
        # Ограничиваем орб для быстрых планет
        filtered = []
        for a in day_aspects:
            if a['transit_planet'] in ['Moon', 'Sun', 'Mercury', 'Venus', 'Mars'] and a['orb'] > 3.0:
                continue
            if a['transit_planet'] in ['Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto'] and a['orb'] > 4.0:
                continue
            filtered.append(a)

        # Сортируем по score
        filtered.sort(key=lambda x: x['score'], reverse=True)
        # Дедупликация осей
        deduped = self._deduplicate_axes(filtered)
        # Ограничиваем количество
        top_events = deduped[:self.DAY_MAX_EVENTS]

        # Извлекаем угловые события
        angle_events = [e for e in top_events if e.get('is_angle')]

        # Формируем темы
        themes = self._cluster_themes(top_events, max_themes=4)

        return {
            'type': 'DAY',
            'date': target_date.strftime('%Y-%m-%d'),
            'top_events': top_events,
            'angle_events': angle_events,
            'themes': themes
        }

    def _filter_month(self) -> Dict[str, Any]:
        """Фильтр для месячного прогноза."""
        start_date = self.start_utc
        end_date = self.end_utc
        if not start_date or not end_date:
            return {}

        normalized = self._normalize()
        # Фильтруем по диапазону
        month_aspects = [a for a in normalized if self._is_date_in_range(a['exact_date'], start_date, end_date)]

        # Строим процессы (объединяем повторные проходы)
        processes = self._merge_retrograde_passes(month_aspects)

        # Фильтруем процессы по длительности и значимости
        # Оставляем только те, у которых duration > 1 или несколько пиков
        filtered_processes = [p for p in processes if p['duration'] > 1 or len(p['peak_dates']) > 1]

        # Сортируем по score
        filtered_processes.sort(key=lambda x: x['score'], reverse=True)
        main_processes = filtered_processes[:self.MONTH_MAX_PROCESSES]

        # Ключевые даты
        key_dates = {}
        for p in main_processes:
            for peak in p['peak_dates']:
                if peak not in key_dates:
                    key_dates[peak] = []
                key_dates[peak].append(f"{self._format_planet(p['transit_planet'])} {self._format_aspect(p['aspect'])} {self._format_planet(p['natal_target'])} (пик)")

        # Ингрессии месяца
        important_ingresses = []
        for ing in self.transit_ingresses:
            if not self._is_date_in_range(ing.get('date'), start_date, end_date):
                continue
            planet = ing.get('planet')
            if planet in ['Pluto', 'Neptune', 'Uranus', 'Saturn', 'Jupiter']:
                important_ingresses.append(ing)
            elif planet == 'Mars' and ing.get('type') == 'house' and int(ing.get('to', 0)) in [1, 4, 5, 7, 8, 10]:
                important_ingresses.append(ing)

        # Темы
        all_events = []
        for p in main_processes:
            all_events.extend(p['all_aspects'])
        themes = self._cluster_themes(all_events, max_themes=5)

        return {
            'type': 'MONTH',
            'period': {'start': start_date.strftime('%Y-%m-%d'), 'end': end_date.strftime('%Y-%m-%d')},
            'main_processes': main_processes,
            'key_dates': key_dates,
            'important_ingresses': important_ingresses,
            'themes': themes
        }

    def _filter_year(self) -> Dict[str, Any]:
        """Фильтр для годового прогноза."""
        start_date = self.start_utc
        end_date = self.end_utc
        if not start_date or not end_date:
            return {}

        normalized = self._normalize()
        # Оставляем только медленные планеты
        slow_planets = ['Pluto', 'Neptune', 'Uranus', 'Saturn', 'Jupiter']
        year_aspects = [a for a in normalized if a['transit_planet'] in slow_planets]
        # Фильтруем по диапазону
        year_aspects = [a for a in year_aspects if self._is_date_in_range(a['exact_date'], start_date, end_date)]

        # Строим процессы
        processes = self._merge_retrograde_passes(year_aspects)

        # Фильтруем: оставляем только долгосрочные (duration > 1 день)
        long_processes = [p for p in processes if p['duration'] > 1]

        # Сортируем по score
        long_processes.sort(key=lambda x: x['score'], reverse=True)
        main_processes = long_processes[:self.YEAR_MAX_PROCESSES]

        # Ключевые периоды (группируем по кварталам)
        periods = []
        if main_processes:
            # Сортируем по start
            sorted_proc = sorted(main_processes, key=lambda x: x['active_from'] or '')
            # Создаём периоды из каждого процесса
            for p in sorted_proc:
                periods.append({
                    'start': p['active_from'],
                    'end': p['active_to'],
                    'theme': self._format_theme(p['theme']),
                    'process': f"{self._format_planet(p['transit_planet'])} {self._format_aspect(p['aspect'])} {self._format_planet(p['natal_target'])}",
                    'score': p['score']
                })

        # Ингрессии года
        major_ingresses = []
        for ing in self.transit_ingresses:
            if not self._is_date_in_range(ing.get('date'), start_date, end_date):
                continue
            if ing.get('planet') in ['Pluto', 'Neptune', 'Uranus', 'Saturn', 'Jupiter']:
                major_ingresses.append(ing)

        # Темы
        all_events = []
        for p in main_processes:
            all_events.extend(p['all_aspects'])
        themes = self._cluster_themes(all_events, max_themes=6)

        # Месячная агрегация
        monthly_summary = []
        for month in range(1, 13):
            month_start = start_date.replace(month=month, day=1)
            if month_start > end_date:
                break
            month_end = min(end_date, month_start.replace(day=28) + timedelta(days=4) - timedelta(days=1))
            month_themes = []
            for p in main_processes:
                if p['active_from'] and p['active_to']:
                    try:
                        p_start = datetime.strptime(p['active_from'], '%Y-%m-%d')
                        p_end = datetime.strptime(p['active_to'], '%Y-%m-%d')
                        if p_start <= month_end and p_end >= month_start:
                            month_themes.append(self._format_theme(p['theme']))
                    except:
                        pass
            if month_themes:
                monthly_summary.append({
                    'month': month_start.strftime('%B'),
                    'themes': month_themes[:3]
                })

        return {
            'type': 'YEAR',
            'year': start_date.year,
            'main_processes': main_processes,
            'key_periods': periods,
            'major_ingresses': major_ingresses,
            'themes': themes,
            'monthly_summary': monthly_summary
        }

    # ----- КЛАСТЕРИЗАЦИЯ ТЕМ -----

    def _cluster_themes(self, events: List[Dict], max_themes: int) -> List[Dict]:
        """Группирует события по темам."""
        # Сопоставляем планеты с доменами
        domain_map = {}
        for domain, keywords in self.THEME_DOMAINS.items():
            for kw in keywords:
                domain_map[kw] = domain

        # Группируем события по домену
        theme_groups = defaultdict(list)
        for e in events:
            transit = e.get('transit_planet')
            target = e.get('natal_target')
            domain = None
            # Сначала ищем по натальной цели
            for dom, keywords in self.THEME_DOMAINS.items():
                if target in keywords:
                    domain = dom
                    break
            # Если не найден, по транзитной
            if not domain:
                for dom, keywords in self.THEME_DOMAINS.items():
                    if transit in keywords:
                        domain = dom
                        break
            if not domain:
                domain = 'OTHER'
            theme_groups[domain].append(e)

        themes = []
        for domain, items in theme_groups.items():
            if domain == 'OTHER' or not items:
                continue
            # Усредняем score
            avg_score = sum(i.get('score', 0) for i in items) / len(items)
            # Формируем описание
            primary = items[0]
            description = f"{self._format_planet(primary['transit_planet'])} {self._format_aspect(primary['aspect'])} {self._format_planet(primary['natal_target'])}"
            if len(items) > 1:
                supports = [f"{self._format_planet(i['transit_planet'])} {self._format_aspect(i['aspect'])} {self._format_planet(i['natal_target'])}" for i in items[1:]]
                description += f" + {', '.join(supports)}"
            themes.append({
                'name': self._format_theme(domain),
                'description': description,
                'score': avg_score
            })

        themes.sort(key=lambda x: x['score'], reverse=True)
        return themes[:max_themes]

    # ----- ТЕКСТОВЫЙ ВЫВОД -----

    def _format_day_output(self, data: Dict) -> str:
        lines = []
        lines.append("## КОНТЕКСТ ПРОГНОЗА")
        lines.append("Тип: ДЕНЬ")
        lines.append(f"Дата: {data.get('date', '')}")
        lines.append("")

        if data.get('top_events'):
            lines.append("## КЛЮЧЕВЫЕ СОБЫТИЯ")
            for i, e in enumerate(data['top_events'], 1):
                planet = self._format_planet(e['transit_planet'])
                target = self._format_planet(e['natal_target'])
                aspect = self._format_aspect(e['aspect'])
                orb = e['orb']
                phase = e['phase']
                score = e['score']
                line = f"{i}. {planet} {aspect} {target}, орб {orb:.2f}°, фаза {phase}, значимость {score:.1f}"
                if e.get('supporting'):
                    supp = [f"{self._format_planet(s['natal_target'])}" for s in e['supporting']]
                    line += f" (объединено с {', '.join(supp)})"
                lines.append(line)
            lines.append("")

        if data.get('angle_events'):
            lines.append("## ТРАНЗИТЫ К УГЛАМ")
            for e in data['angle_events']:
                planet = self._format_planet(e['transit_planet'])
                angle = e['natal_target']
                aspect = self._format_aspect(e['aspect'])
                orb = e['orb']
                score = e['score']
                lines.append(f"- {planet} {aspect} {angle}, орб {orb:.2f}°, значимость {score:.1f}")
            lines.append("")

        if data.get('themes'):
            lines.append("## ОСНОВНЫЕ ТЕМЫ")
            for i, theme in enumerate(data['themes'], 1):
                lines.append(f"{i}. {theme['name']}: {theme['description']} (значимость {theme['score']:.1f})")
            lines.append("")

        return "\n".join(lines)

    def _format_month_output(self, data: Dict) -> str:
        lines = []
        lines.append("## КОНТЕКСТ ПРОГНОЗА")
        lines.append("Тип: МЕСЯЦ")
        period = data.get('period', {})
        lines.append(f"Период: {period.get('start', '')} – {period.get('end', '')}")
        lines.append("")

        if data.get('main_processes'):
            lines.append("## ГЛАВНЫЕ ПРОЦЕССЫ МЕСЯЦА")
            for i, p in enumerate(data['main_processes'], 1):
                planet = self._format_planet(p['transit_planet'])
                target = self._format_planet(p['natal_target'])
                aspect = self._format_aspect(p['aspect'])
                lines.append(f"{i}. {planet} {aspect} {target}")
                lines.append(f"   Начало активности: {p['active_from']}")
                lines.append(f"   Пики: {', '.join(p['peak_dates'])}")
                lines.append(f"   Окончание активности: {p['active_to']}")
                lines.append(f"   Длительность: {p['duration']} дней")
                lines.append(f"   Значимость: {p['score']:.1f}")
                lines.append(f"   Тема: {self._format_theme(p['theme'])}")
            lines.append("")

        if data.get('key_dates'):
            lines.append("## КЛЮЧЕВЫЕ ДАТЫ")
            for date, events in sorted(data['key_dates'].items()):
                lines.append(f"{date}: {', '.join(events)}")
            lines.append("")

        if data.get('important_ingresses'):
            lines.append("## ЗНАЧИМЫЕ ИНГРЕССИИ")
            for ing in data['important_ingresses']:
                planet = self._format_planet(ing.get('planet', ''))
                if ing.get('type') == 'sign':
                    lines.append(f"{ing.get('date')} — {planet} входит в знак {ing.get('to')}")
                else:
                    lines.append(f"{ing.get('date')} — {planet} входит в дом {ing.get('to')}")
            lines.append("")

        if data.get('themes'):
            lines.append("## ОСНОВНЫЕ ТЕМЫ МЕСЯЦА")
            for i, theme in enumerate(data['themes'], 1):
                lines.append(f"{i}. {theme['name']}: {theme['description']} (значимость {theme['score']:.1f})")
            lines.append("")

        return "\n".join(lines)

    def _format_year_output(self, data: Dict) -> str:
        lines = []
        lines.append("## КОНТЕКСТ ПРОГНОЗА")
        lines.append("Тип: ГОД")
        lines.append(f"Год: {data.get('year', '')}")
        lines.append("")

        if data.get('main_processes'):
            lines.append("## ГЛАВНЫЕ ДОЛГОСРОЧНЫЕ ПРОЦЕССЫ ГОДА")
            for i, p in enumerate(data['main_processes'], 1):
                planet = self._format_planet(p['transit_planet'])
                target = self._format_planet(p['natal_target'])
                aspect = self._format_aspect(p['aspect'])
                lines.append(f"{i}. {planet} {aspect} {target}")
                lines.append(f"   Начало активности: {p['active_from']}")
                lines.append(f"   Пики: {', '.join(p['peak_dates'])}")
                lines.append(f"   Окончание активности: {p['active_to']}")
                lines.append(f"   Длительность: {p['duration']} дней")
                lines.append(f"   Значимость: {p['score']:.1f}")
                lines.append(f"   Тема: {self._format_theme(p['theme'])}")
            lines.append("")

        if data.get('key_periods'):
            lines.append("## КЛЮЧЕВЫЕ ПЕРИОДЫ ГОДА")
            for p in data['key_periods']:
                lines.append(f"{p['start']} – {p['end']}: {p['theme']} ({p['process']}), значимость {p['score']:.1f}")
            lines.append("")

        if data.get('major_ingresses'):
            lines.append("## ЗНАЧИМЫЕ ИНГРЕССИИ")
            for ing in data['major_ingresses']:
                planet = self._format_planet(ing.get('planet', ''))
                if ing.get('type') == 'sign':
                    lines.append(f"{ing.get('date')} — {planet} входит в знак {ing.get('to')}")
                else:
                    lines.append(f"{ing.get('date')} — {planet} входит в дом {ing.get('to')}")
            lines.append("")

        if data.get('themes'):
            lines.append("## ОСНОВНЫЕ ТЕМЫ ГОДА")
            for i, theme in enumerate(data['themes'], 1):
                lines.append(f"{i}. {theme['name']}: {theme['description']} (значимость {theme['score']:.1f})")
            lines.append("")

        if data.get('monthly_summary'):
            lines.append("## МЕСЯЧНАЯ АГРЕГАЦИЯ")
            for item in data['monthly_summary']:
                lines.append(f"{item['month']}: {', '.join(item['themes'])}")
            lines.append("")

        return "\n".join(lines)

    # ----- ПУБЛИЧНЫЕ МЕТОДЫ -----

    def build_day_context(self) -> str:
        """Возвращает текстовый контекст для дневного прогноза."""
        data = self._filter_day()
        return self._format_day_output(data)

    def build_month_context(self) -> str:
        """Возвращает текстовый контекст для месячного прогноза."""
        data = self._filter_month()
        return self._format_month_output(data)

    def build_year_context(self) -> str:
        """Возвращает текстовый контекст для годового прогноза."""
        data = self._filter_year()
        return self._format_year_output(data)