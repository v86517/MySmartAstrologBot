# bot/calculators/context_builder.py
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict
import math

logger = logging.getLogger(__name__)


class AstrologyContextBuilder:
    """
    Класс для построения трёх разных контекстов: DAY, MONTH, YEAR.
    Каждый метод возвращает текст, который вставляется в промпт.
    """

    # Веса транзитных планет (для DAY и MONTH/YEAR)
    PLANET_WEIGHT = {
        'Pluto': 10, 'Neptune': 9, 'Uranus': 9, 'Saturn': 8,
        'Jupiter': 7, 'Mars': 6, 'Venus': 5, 'Mercury': 5,
        'Sun': 5, 'Moon': 4
    }

    # Веса натальных точек
    NATAL_WEIGHT = {
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

    # Длительность (в днях) для классификации
    DURATION_CLASS = {
        'event': (0, 1),
        'short': (2, 7),
        'medium': (8, 30),
        'long': (31, float('inf'))
    }

    # Ограничения
    DAY_MAX_EVENTS = 6
    MONTH_MAX_PROCESSES = 8
    MONTH_MAX_DATES = 10
    MONTH_MAX_INGRESSES = 7
    YEAR_MAX_PROCESSES = 10
    YEAR_MAX_PERIODS = 8
    YEAR_MAX_INGRESSES = 7

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
    # Семантические домены для тем
    SEMANTIC_DOMAINS = {
        'identity': ['Sun', 'ASC', 'self', 'personality'],
        'emotions': ['Moon', 'emotions', 'family', 'intuition'],
        'communication': ['Mercury', 'communication', 'learning', 'intellect'],
        'love': ['Venus', 'love', 'beauty', 'values'],
        'action': ['Mars', 'action', 'drive', 'conflict'],
        'growth': ['Jupiter', 'growth', 'expansion', 'wisdom'],
        'structure': ['Saturn', 'structure', 'responsibility', 'discipline'],
        'change': ['Uranus', 'change', 'innovation', 'freedom'],
        'spirituality': ['Neptune', 'spirituality', 'intuition', 'illusion'],
        'transformation': ['Pluto', 'transformation', 'power', 'depth'],
        'healing': ['Chiron', 'healing', 'wound', 'teaching'],
        'karma': ['NorthNode', 'SouthNode', 'karma', 'destiny']
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
        self.transit_stations = transit_data.get('transit_stations', [])
        self.period = transit_data.get('period', 'today')
        self.start_utc = transit_data.get('start_utc')
        self.end_utc = transit_data.get('end_utc')

    # ----- ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ -----

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

    def _calculate_significance(self, aspect: Dict, transit_planet: str, natal_point: str,
                                is_angle: bool = False) -> float:
        """Расчёт значимости для одного аспекта."""
        planet_w = self.PLANET_WEIGHT.get(transit_planet, 1)
        natal_w = self.NATAL_WEIGHT.get(natal_point, 1)
        aspect_w = self.ASPECT_WEIGHT.get(aspect.get('aspect', ''), 0.5)
        orb = aspect.get('orb', 10.0)
        orb_w = self._get_orb_weight(orb)
        phase = aspect.get('phase', '')
        phase_w = self.PHASE_WEIGHT.get(phase, 0.8)
        base = planet_w * natal_w * aspect_w * orb_w * phase_w
        if is_angle:
            base *= 1.2  # бонус за угол
        return base

    def _validate_aspect(self, asp: Dict) -> bool:
        required = ['transit_planet', 'aspect', 'orb', 'phase', 'exact_date']
        for f in required:
            if f not in asp or asp[f] is None:
                return False
        return True

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

    def _format_planet(self, name: str) -> str:
        return self.PLANET_NAMES_RU.get(name, name)

    def _format_aspect(self, name: str) -> str:
        return self.ASPECT_NAMES_RU.get(name, name)

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

    # ----- ОБЪЕДИНЕНИЕ ПОВТОРНЫХ АСПЕКТОВ В ПРОЦЕССЫ -----

    def _build_processes(self, aspects: List[Dict], period_type: str) -> List[Dict]:
        """Группирует аспекты по (transit_planet, natal_point, aspect) в процессы."""
        groups = defaultdict(list)
        for asp in aspects:
            key = (asp['transit_planet'], asp.get('natal_planet') or asp.get('angle'), asp['aspect'])
            groups[key].append(asp)

        processes = []
        for (t_planet, n_point, aspect), asp_list in groups.items():
            if not asp_list:
                continue
            asp_list.sort(key=lambda x: x.get('exact_date', ''))
            first = asp_list[0]
            last = asp_list[-1]
            start = first.get('exact_date')
            end = last.get('exact_date')
            duration = self._get_duration_days(start, end) if start and end else 0
            # Находим пик (макс significance)
            peak_asp = max(asp_list, key=lambda x: x.get('significance', 0))
            peak_date = peak_asp.get('exact_date')
            # Собираем все даты проходов
            passes = [a.get('exact_date') for a in asp_list if a.get('exact_date')]
            # Усреднённая значимость
            avg_significance = sum(a.get('significance', 0) for a in asp_list) / len(asp_list)
            # Добавляем бонус за длительность
            if period_type == 'month':
                avg_significance *= (1 + 0.3 * min(duration / 30, 1.0))
            elif period_type == 'year':
                avg_significance *= (1 + 0.5 * min(duration / 90, 1.0))
            processes.append({
                'transit_planet': t_planet,
                'natal_point': n_point,
                'aspect': aspect,
                'start_date': start,
                'end_date': end,
                'duration_days': duration,
                'duration_class': self._get_duration_class(duration),
                'peak_date': peak_date,
                'significance': avg_significance,
                'passes': passes,
                'is_angle': 'angle' in first,
                'aspects': asp_list  # добавлено
            })
        return processes

    # ----- ДЕДУПЛИКАЦИЯ ОСЕЙ ASC/DSC И MC/IC -----

    def _deduplicate_axes(self, events: List[Dict]) -> List[Dict]:
        """
        Объединяет пары ASC/DSC и MC/IC в один конфигурационный блок.
        """
        # Группируем по (transit_planet, aspect_type)
        axes = defaultdict(list)
        others = []
        for e in events:
            natal = e.get('natal_point')
            if natal in ['ASC', 'DSC']:
                key = (e['transit_planet'], e['aspect'], 'ASC_DSC')
                axes[key].append(e)
            elif natal in ['MC', 'IC']:
                key = (e['transit_planet'], e['aspect'], 'MC_IC')
                axes[key].append(e)
            else:
                others.append(e)

        merged = []
        for key, items in axes.items():
            if len(items) == 1:
                merged.append(items[0])
            else:
                # Объединяем
                first = items[0]
                combined = first.copy()
                combined['natal_point'] = key[2]  # 'ASC_DSC' или 'MC_IC'
                combined['significance'] = sum(i['significance'] for i in items)
                # Собираем supporting events
                combined['supporting'] = [{'natal_point': i['natal_point'], 'aspect': i['aspect']} for i in items]
                merged.append(combined)

        # Добавляем остальные
        merged.extend(others)
        return merged

    # ----- СЕМАНТИЧЕСКАЯ КЛАСТЕРИЗАЦИЯ ТЕМ -----

    def _cluster_themes(self, events: List[Dict], max_themes: int) -> List[Dict]:
        """
        Группирует события в темы на основе семантических доменов.
        """
        # Сопоставляем планеты с доменами
        domain_map = {}
        for domain, keywords in self.SEMANTIC_DOMAINS.items():
            for kw in keywords:
                domain_map[kw] = domain

        # Группируем события по домену
        theme_groups = defaultdict(list)
        for e in events:
            # Определяем домен по транзитной планете и натальной точке
            t_planet = e.get('transit_planet')
            n_point = e.get('natal_point')
            domain = None
            # Сначала ищем по натальной точке
            for dom, keywords in self.SEMANTIC_DOMAINS.items():
                if n_point in keywords:
                    domain = dom
                    break
            # Если не найден, по транзитной
            if not domain:
                for dom, keywords in self.SEMANTIC_DOMAINS.items():
                    if t_planet in keywords:
                        domain = dom
                        break
            if not domain:
                domain = 'other'
            theme_groups[domain].append(e)

        themes = []
        for domain, items in theme_groups.items():
            if domain == 'other':
                continue
            # Сортируем по значимости
            items.sort(key=lambda x: x.get('significance', 0), reverse=True)
            # Главный драйвер
            primary = items[0]
            # Формируем описание темы
            theme_name = domain.capitalize()
            theme_desc = f"{self._format_planet(primary['transit_planet'])} {self._format_aspect(primary['aspect'])} {self._format_planet(primary['natal_point'])}"
            if len(items) > 1:
                supports = [f"{self._format_planet(i['transit_planet'])} {self._format_aspect(i['aspect'])} {self._format_planet(i['natal_point'])}" for i in items[1:]]
                theme_desc += f" + {', '.join(supports)}"
            themes.append({
                'theme': theme_name,
                'description': theme_desc,
                'significance': sum(i['significance'] for i in items) / len(items)
            })

        themes.sort(key=lambda x: x['significance'], reverse=True)
        return themes[:max_themes]

    # ----- DAY_FILTER -----

    def _build_day_context(self) -> str:
        target_date = self.start_utc
        if not target_date:
            return ""

        # Собираем все аспекты дня
        day_events = []
        for asp in self.transit_aspects + self.transit_angle_aspects:
            if not self._is_same_day(asp.get('exact_date'), target_date):
                continue
            if not self._validate_aspect(asp):
                continue
            transit_planet = asp.get('transit_planet')
            natal_point = asp.get('natal_planet') or asp.get('angle')
            if not natal_point:
                continue
            # Для дня отсекаем слишком большие орбы
            orb = asp.get('orb', 10.0)
            if transit_planet in ['Moon', 'Sun', 'Mercury', 'Venus', 'Mars'] and orb > 3.0:
                continue
            if transit_planet in ['Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto'] and orb > 4.0:
                continue
            # Рассчитываем значимость
            significance = self._calculate_significance(asp, transit_planet, natal_point, 'angle' in asp)
            asp['significance'] = significance
            asp['natal_point'] = natal_point
            asp['is_angle'] = 'angle' in asp
            day_events.append(asp)

        # Сортируем по значимости
        day_events.sort(key=lambda x: x['significance'], reverse=True)
        # Оставляем только топ (но с учётом дедупликации)
        top_events = day_events[:self.DAY_MAX_EVENTS * 2]  # запас

        # Дедупликация осей
        deduped = self._deduplicate_axes(top_events)

        # Оставляем топ 5-6
        final_events = deduped[:self.DAY_MAX_EVENTS]

        # Формируем темы
        themes = self._cluster_themes(final_events, max_themes=3)

        # --- Формирование текста ---
        lines = []
        lines.append("## КОНТЕКСТ ПРОГНОЗА")
        lines.append("Тип: ДЕНЬ")
        lines.append(f"Дата: {target_date.strftime('%d.%m.%Y')}")
        lines.append("")

        if final_events:
            lines.append("## КЛЮЧЕВЫЕ СОБЫТИЯ")
            for i, e in enumerate(final_events, 1):
                planet = self._format_planet(e['transit_planet'])
                natal = self._format_planet(e['natal_point'])
                aspect = self._format_aspect(e['aspect'])
                orb = e['orb']
                phase = e['phase']
                sig = e['significance']
                lines.append(f"{i}. {planet} {aspect} {natal}, орб {orb:.2f}°, фаза {phase}, значимость {sig:.1f}")
                if e.get('supporting'):
                    supp = [f"{self._format_planet(s['natal_point'])} {self._format_aspect(s['aspect'])}" for s in e['supporting']]
                    lines.append(f"   (объединено с {', '.join(supp)})")
            lines.append("")

        # Угловые события отдельно
        angle_events = [e for e in final_events if e.get('is_angle')]
        if angle_events:
            lines.append("## ТРАНЗИТЫ К УГЛАМ")
            for e in angle_events:
                planet = self._format_planet(e['transit_planet'])
                angle = e['natal_point']
                aspect = self._format_aspect(e['aspect'])
                orb = e['orb']
                sig = e['significance']
                lines.append(f"- {planet} {aspect} {angle}, орб {orb:.2f}°, значимость {sig:.1f}")
            lines.append("")

        if themes:
            lines.append("## ОСНОВНЫЕ ТЕМЫ")
            for i, theme in enumerate(themes, 1):
                lines.append(f"{i}. {theme['theme']}: {theme['description']} (значимость {theme['significance']:.1f})")
            lines.append("")

        return "\n".join(lines)

    # ----- MONTH_FILTER -----

    def _build_month_context(self) -> str:
        start_date = self.start_utc
        end_date = self.end_utc
        if not start_date or not end_date:
            return ""

        # Собираем аспекты за месяц
        month_aspects = []
        for asp in self.transit_aspects + self.transit_angle_aspects:
            if not self._is_date_in_range(asp.get('exact_date'), start_date, end_date):
                continue
            if not self._validate_aspect(asp):
                continue
            transit_planet = asp.get('transit_planet')
            natal_point = asp.get('natal_planet') or asp.get('angle')
            if not natal_point:
                continue
            # Орб для месяца более гибкий
            orb = asp.get('orb', 10.0)
            if transit_planet in ['Pluto', 'Neptune', 'Uranus', 'Saturn'] and orb > 5.0:
                continue
            if transit_planet in ['Jupiter'] and orb > 6.0:
                continue
            if transit_planet in ['Moon', 'Sun', 'Mercury', 'Venus', 'Mars'] and orb > 5.0:
                continue
            significance = self._calculate_significance(asp, transit_planet, natal_point, 'angle' in asp)
            asp['significance'] = significance
            asp['natal_point'] = natal_point
            asp['is_angle'] = 'angle' in asp
            month_aspects.append(asp)

        # Строим процессы (группируем повторяющиеся)
        processes = self._build_processes(month_aspects, 'month')

        # Сортируем процессы по значимости с учётом длительности
        processes.sort(key=lambda x: x['significance'], reverse=True)

        # Выбираем главные процессы (но не более лимита)
        main_processes = processes[:self.MONTH_MAX_PROCESSES]

        # Ключевые даты (пики процессов + сильные краткосрочные события)
        key_dates = []
        for p in main_processes:
            if p['peak_date']:
                key_dates.append({
                    'date': p['peak_date'],
                    'event': f"{self._format_planet(p['transit_planet'])} {self._format_aspect(p['aspect'])} {self._format_planet(p['natal_point'])} (пик)"
                })
        # Добавляем краткосрочные события, которые не вошли в процессы, если они сильные
        used_aspect_ids = set(id(a) for p in processes for a in p['aspects'])
        short_events = [a for a in month_aspects if id(a) not in used_aspect_ids]
        short_events.sort(key=lambda x: x['significance'], reverse=True)
        for e in short_events[:5]:
            if e['exact_date']:
                key_dates.append({
                    'date': e['exact_date'],
                    'event': f"{self._format_planet(e['transit_planet'])} {self._format_aspect(e['aspect'])} {self._format_planet(e['natal_point'])}"
                })

        # Дедупликация дат
        unique_dates = {}
        for item in key_dates:
            date = item['date']
            if date not in unique_dates:
                unique_dates[date] = []
            unique_dates[date].append(item['event'])

        # Формируем список ключевых дат (сортируем)
        key_dates_list = []
        for date, events in sorted(unique_dates.items()):
            key_dates_list.append({
                'date': date,
                'events': events
            })

        # Ингрессии (только значимые)
        important_ingresses = []
        for ing in self.transit_ingresses:
            if not self._is_date_in_range(ing.get('date'), start_date, end_date):
                continue
            planet = ing.get('planet')
            if planet in ['Pluto', 'Neptune', 'Uranus', 'Saturn', 'Jupiter']:
                important_ingresses.append(ing)
            elif planet == 'Mars' and ing.get('type') == 'house' and int(ing.get('to', 0)) in [1, 4, 5, 7, 8, 10]:
                important_ingresses.append(ing)
            # Игнорируем Moon и быстрые

        # Темы (семантическая кластеризация)
        all_events_for_themes = []
        for p in main_processes:
            all_events_for_themes.extend(p['aspects'])
        all_events_for_themes.extend(short_events[:3])
        themes = self._cluster_themes(all_events_for_themes, max_themes=5)

        # Формируем текст
        lines = []
        lines.append("## КОНТЕКСТ ПРОГНОЗА")
        lines.append("Тип: МЕСЯЦ")
        lines.append(f"Период: {start_date.strftime('%d.%m.%Y')} – {end_date.strftime('%d.%m.%Y')}")
        lines.append("")

        if main_processes:
            lines.append("## ГЛАВНЫЕ ПРОЦЕССЫ МЕСЯЦА")
            for i, p in enumerate(main_processes, 1):
                planet = self._format_planet(p['transit_planet'])
                natal = self._format_planet(p['natal_point'])
                aspect = self._format_aspect(p['aspect'])
                start = p['start_date']
                end = p['end_date']
                peak = p['peak_date']
                duration = p['duration_days']
                sig = p['significance']
                lines.append(f"{i}. {planet} {aspect} {natal}")
                lines.append(f"   Начало: {start}, пик: {peak}, окончание: {end}, длительность: {duration} дн., значимость: {sig:.1f}")
                if len(p['passes']) > 1:
                    passes_str = ", ".join(p['passes'])
                    lines.append(f"   Прохождения: {passes_str}")
            lines.append("")

        if key_dates_list:
            lines.append("## КЛЮЧЕВЫЕ ДАТЫ")
            for item in key_dates_list[:self.MONTH_MAX_DATES]:
                lines.append(f"{item['date']}: {', '.join(item['events'])}")
            lines.append("")

        if important_ingresses:
            lines.append("## ЗНАЧИМЫЕ ИНГРЕССИИ")
            for ing in important_ingresses[:self.MONTH_MAX_INGRESSES]:
                planet = self._format_planet(ing.get('planet', ''))
                if ing.get('type') == 'sign':
                    lines.append(f"{ing.get('date')} — {planet} входит в знак {ing.get('to')}")
                else:
                    lines.append(f"{ing.get('date')} — {planet} входит в дом {ing.get('to')}")
            lines.append("")

        if themes:
            lines.append("## ОСНОВНЫЕ ТЕМЫ МЕСЯЦА")
            for i, theme in enumerate(themes, 1):
                lines.append(f"{i}. {theme['theme']}: {theme['description']} (значимость {theme['significance']:.1f})")
            lines.append("")

        return "\n".join(lines)

    # ----- YEAR_FILTER -----

    def _build_year_context(self) -> str:
        start_date = self.start_utc
        end_date = self.end_utc
        if not start_date or not end_date:
            return ""

        # Собираем только медленные планеты для года
        year_aspects = []
        for asp in self.transit_aspects:
            if not self._is_date_in_range(asp.get('exact_date'), start_date, end_date):
                continue
            transit_planet = asp.get('transit_planet')
            if transit_planet not in ['Pluto', 'Neptune', 'Uranus', 'Saturn', 'Jupiter']:
                continue
            if not self._validate_aspect(asp):
                continue
            natal_point = asp.get('natal_planet') or asp.get('angle')
            if not natal_point:
                continue
            # Орб для года больше
            orb = asp.get('orb', 10.0)
            if orb > 5.0:
                continue
            significance = self._calculate_significance(asp, transit_planet, natal_point, 'angle' in asp)
            asp['significance'] = significance
            asp['natal_point'] = natal_point
            asp['is_angle'] = 'angle' in asp
            year_aspects.append(asp)

        # Строим процессы (группируем повторяющиеся)
        processes = self._build_processes(year_aspects, 'year')

        # Фильтруем: оставляем только долгосрочные (duration > 1 день) или с несколькими проходами
        long_processes = [p for p in processes if p['duration_days'] > 1 or len(p['passes']) > 1]

        # Сортируем по значимости
        long_processes.sort(key=lambda x: x['significance'], reverse=True)
        main_processes = long_processes[:self.YEAR_MAX_PROCESSES]

        # Ключевые периоды года (группируем близкие по времени процессы)
        periods = []
        if main_processes:
            # Сортируем по start_date
            sorted_proc = sorted(main_processes, key=lambda x: x['start_date'] or '')
            # Группируем по кварталам или по близости
            current_period = None
            for p in sorted_proc:
                if not p['start_date'] or not p['end_date']:
                    continue
                # Просто создаём отдельный период для каждого процесса
                periods.append({
                    'start': p['start_date'],
                    'end': p['end_date'],
                    'theme': f"{self._format_planet(p['transit_planet'])} {self._format_aspect(p['aspect'])} {self._format_planet(p['natal_point'])}",
                    'significance': p['significance']
                })

        # Ингрессии для года (только медленные)
        major_ingresses = []
        for ing in self.transit_ingresses:
            if not self._is_date_in_range(ing.get('date'), start_date, end_date):
                continue
            if ing.get('planet') in ['Pluto', 'Neptune', 'Uranus', 'Saturn', 'Jupiter']:
                major_ingresses.append(ing)

        # Темы (семантическая кластеризация)
        all_events = []
        for p in main_processes:
            all_events.extend(p['aspects'])
        themes = self._cluster_themes(all_events, max_themes=6)

        # Месячная агрегация (упрощённо)
        monthly_summary = []
        for month in range(1, 13):
            month_start = start_date.replace(month=month, day=1)
            if month_start > end_date:
                break
            month_end = min(end_date, month_start.replace(day=28) + timedelta(days=4) - timedelta(days=1))
            month_themes = []
            for p in main_processes:
                if p['start_date'] and p['end_date']:
                    try:
                        p_start = datetime.strptime(p['start_date'], '%Y-%m-%d')
                        p_end = datetime.strptime(p['end_date'], '%Y-%m-%d')
                        if p_start <= month_end and p_end >= month_start:
                            month_themes.append(f"{self._format_planet(p['transit_planet'])} {self._format_aspect(p['aspect'])} {self._format_planet(p['natal_point'])}")
                    except:
                        pass
            if month_themes:
                monthly_summary.append({
                    'month': month_start.strftime('%B'),
                    'themes': month_themes[:3]
                })

        # Формируем текст
        lines = []
        lines.append("## КОНТЕКСТ ПРОГНОЗА")
        lines.append("Тип: ГОД")
        lines.append(f"Год: {start_date.year}")
        lines.append("")

        if main_processes:
            lines.append("## ГЛАВНЫЕ ДОЛГОСРОЧНЫЕ ПРОЦЕССЫ")
            for i, p in enumerate(main_processes, 1):
                planet = self._format_planet(p['transit_planet'])
                natal = self._format_planet(p['natal_point'])
                aspect = self._format_aspect(p['aspect'])
                start = p['start_date']
                end = p['end_date']
                peak = p['peak_date']
                duration = p['duration_days']
                passes = len(p['passes'])
                sig = p['significance']
                lines.append(f"{i}. {planet} {aspect} {natal}")
                lines.append(f"   Период: {start} – {end}, пик: {peak}, длительность: {duration} дн., проходов: {passes}, значимость: {sig:.1f}")
                if len(p['passes']) > 1:
                    passes_str = ", ".join(p['passes'])
                    lines.append(f"   Прохождения: {passes_str}")
            lines.append("")

        if periods:
            lines.append("## КЛЮЧЕВЫЕ ПЕРИОДЫ ГОДА")
            for p in periods:
                lines.append(f"{p['start']} – {p['end']}: {p['theme']} (значимость {p['significance']:.1f})")
            lines.append("")

        if major_ingresses:
            lines.append("## ЗНАЧИМЫЕ ИНГРЕССИИ")
            for ing in major_ingresses[:self.YEAR_MAX_INGRESSES]:
                planet = self._format_planet(ing.get('planet', ''))
                if ing.get('type') == 'sign':
                    lines.append(f"{ing.get('date')} — {planet} входит в знак {ing.get('to')}")
                else:
                    lines.append(f"{ing.get('date')} — {planet} входит в дом {ing.get('to')}")
            lines.append("")

        if themes:
            lines.append("## ОСНОВНЫЕ ТЕМЫ ГОДА")
            for i, theme in enumerate(themes, 1):
                lines.append(f"{i}. {theme['theme']}: {theme['description']} (значимость {theme['significance']:.1f})")
            lines.append("")

        if monthly_summary:
            lines.append("## МЕСЯЧНАЯ АГРЕГАЦИЯ")
            for item in monthly_summary:
                lines.append(f"{item['month']}: {', '.join(item['themes'])}")
            lines.append("")

        return "\n".join(lines)

    # ----- ПУБЛИЧНЫЕ МЕТОДЫ -----

    def build_day_context(self) -> str:
        return self._build_day_context()

    def build_month_context(self) -> str:
        return self._build_month_context()

    def build_year_context(self) -> str:
        return self._build_year_context()