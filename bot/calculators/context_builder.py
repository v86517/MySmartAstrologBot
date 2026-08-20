# bot/calculators/context_builder.py
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict
import math

logger = logging.getLogger(__name__)


# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================

CONFIG = {
    "day": {
        "max_events": 5,
        "absolute_max_events": 7,
        "min_events": 3,
    },
    "month": {
        "max_events": 8,
    },
    "year": {
        "max_events": 12,
    },
    "minor_aspects_enabled": False,
    "secondary_points_enabled": False,
    "angle_multiplier": 1.25,
    "phase_weight": {
        "applying": 1.10,
        "exact": 1.20,
        "separating": 0.80,
    },
    "theme_diminishing_returns": [1.0, 0.5, 0.25, 0.125],
    "fast_duration_limit": 7,          # дней
    "medium_duration_limit": 120,      # дней
    # остальное – long
    "max_orb": {
        "conjunction": 8.0,
        "opposition": 8.0,
        "square": 6.0,
        "trine": 6.0,
        "sextile": 5.0,
    },
    "chiron_orb_limit": 1.5,
    "chiron_significance_threshold": 6.0,
}


# ============================================================================
# ОСНОВНОЙ КЛАСС
# ============================================================================

class AstrologyContextBuilder:
    """
    Класс для построения контекста для трёх типов прогнозов: ДЕНЬ, МЕСЯЦ, ГОД.
    Реализует полный pipeline фильтрации согласно FINAL PATCH SPECIFICATION v1.0.
    """

    # Веса планет (транзитных) – для базовой значимости
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
        # secondary – низкий вес
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

    # Основные аспекты (разрешённые)
    MAJOR_ASPECTS = {'conjunction', 'opposition', 'square', 'trine', 'sextile'}

    # Разрешённые транзитные планеты
    ALLOWED_TRANSITS = {'Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                        'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto'}

    # Основные натальные цели (для фильтрации)
    PRIMARY_TARGETS = {'Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                       'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto',
                       'ASC', 'MC'}

    # Вторичные точки (исключаются по умолчанию)
    SECONDARY_TARGETS = {'Chiron', 'NorthNode', 'SouthNode', 'Lilith',
                         'Mean_Lilith', 'True_Lilith', 'Vertex'}

    # Таблица маппинга тем (фиксированная)
    THEME_MAP = {
        # Солнце
        ('Sun', 'ASC'): 'IDENTITY',
        ('Sun', 'DSC'): 'IDENTITY',
        ('Sun', 'MC'): 'CAREER',
        ('Sun', 'IC'): 'FAMILY',
        # Луна
        ('Moon', 'ASC'): 'IDENTITY',
        ('Moon', 'DSC'): 'RELATIONSHIPS',
        ('Moon', 'MC'): 'CAREER',
        ('Moon', 'IC'): 'FAMILY',
        # Плутон, Нептун, Уран, Марс к Меркурию – коммуникация
        ('Pluto', 'Mercury'): 'COMMUNICATION',
        ('Neptune', 'Mercury'): 'COMMUNICATION',
        ('Uranus', 'Mercury'): 'COMMUNICATION',
        ('Mars', 'Mercury'): 'COMMUNICATION',
        # К Луне – эмоции
        ('Pluto', 'Moon'): 'EMOTIONS',
        ('Neptune', 'Moon'): 'EMOTIONS',
        ('Uranus', 'Moon'): 'EMOTIONS',
        ('Mars', 'Moon'): 'EMOTIONS',
        # Юпитер/Сатурн к Венере – отношения
        ('Jupiter', 'Venus'): 'RELATIONSHIPS',
        ('Saturn', 'Venus'): 'RELATIONSHIPS',
        # Уран к Марсу – перемены
        ('Uranus', 'Mars'): 'CHANGE',
        # Марс к Сатурну – ответственность
        ('Mars', 'Saturn'): 'RESPONSIBILITY',
        ('Pluto', 'Saturn'): 'RESPONSIBILITY',
        ('Neptune', 'Saturn'): 'RESPONSIBILITY',
        ('Uranus', 'Saturn'): 'RESPONSIBILITY',
        # Сатурн к Солнцу – идентичность
        ('Saturn', 'Sun'): 'IDENTITY',
        ('Pluto', 'Sun'): 'TRANSFORMATION',
        ('Neptune', 'Sun'): 'INTUITION',
        ('Uranus', 'Sun'): 'CHANGE',
        # Дополнительно для ASC/MC
        ('Jupiter', 'ASC'): 'IDENTITY',
        ('Saturn', 'ASC'): 'IDENTITY',
        ('Pluto', 'ASC'): 'TRANSFORMATION',
        ('Uranus', 'ASC'): 'CHANGE',
        ('Jupiter', 'MC'): 'CAREER',
        ('Saturn', 'MC'): 'CAREER',
        ('Pluto', 'MC'): 'CAREER',
        ('Uranus', 'MC'): 'CAREER',
    }

    # Локализация для вывода
    PLANET_NAMES_RU = {
        'Sun': 'Солнце', 'Moon': 'Луна', 'Mercury': 'Меркурий',
        'Venus': 'Венера', 'Mars': 'Марс', 'Jupiter': 'Юпитер',
        'Saturn': 'Сатурн', 'Uranus': 'Уран', 'Neptune': 'Нептун',
        'Pluto': 'Плутон', 'Chiron': 'Хирон', 'Lilith': 'Лилит'
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

        # Кеши
        self._normalized = None
        self._processes = None

    # ----- ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ -----

    def _format_planet(self, name: str) -> str:
        return self.PLANET_NAMES_RU.get(name, name)

    def _format_aspect(self, name: str) -> str:
        return self.ASPECT_NAMES_RU.get(name, name)

    def _format_theme(self, name: str) -> str:
        return self.THEME_NAMES_RU.get(name, name)

    def _is_same_day(self, date_str: str, target_date: datetime) -> bool:
        """Проверяет, совпадает ли дата события с целевой датой."""
        if not date_str or not target_date:
            return False
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d').date()
            return dt == target_date.date()
        except ValueError:
            return False

    def _is_date_in_range(self, date_str: str, start: datetime, end: datetime) -> bool:
        """Проверяет, попадает ли дата в интервал [start, end] (включительно)."""
        if not date_str or not start or not end:
            return False
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            return start <= dt <= end
        except ValueError:
            return False

    def _get_orb_factor(self, orb: float, aspect: str) -> float:
        """Нормализованный коэффициент орба (0..1)."""
        max_orb = CONFIG['max_orb'].get(aspect, 8.0)
        if max_orb <= 0:
            return 0.0
        factor = 1.0 - (orb / max_orb)
        return max(0.0, min(1.0, factor))

    def _is_valid_target(self, target: str) -> bool:
        """Проверяет, является ли натальная точка основной."""
        if target in self.PRIMARY_TARGETS:
            return True
        # Вторичные разрешены только если включены в конфиге
        if CONFIG['secondary_points_enabled']:
            return True
        return False

    def _is_major_aspect(self, aspect: str) -> bool:
        """Проверяет, является ли аспект мажорным."""
        if not CONFIG['minor_aspects_enabled']:
            return aspect in self.MAJOR_ASPECTS
        return True  # если разрешены минорные, пропускаем все

    def _normalize_target(self, target: str) -> str:
        """Нормализует цель для дедупликации осей."""
        if target in ('ASC', 'DSC'):
            return 'ASC_DSC_AXIS'
        if target in ('MC', 'IC'):
            return 'MC_IC_AXIS'
        return target

    def _get_axis_primary(self, target: str, aspect: str, is_conjunct: bool = None) -> str:
        """
        Возвращает предпочтительное представление для оси.
        Если есть соединение с ASC, выводим ASC, иначе DSC.
        Для MC/IC аналогично.
        """
        if target == 'ASC_DSC_AXIS':
            return 'ASC' if is_conjunct else 'DSC'
        if target == 'MC_IC_AXIS':
            return 'MC' if is_conjunct else 'IC'
        return target

    def _get_duration_class(self, days: int) -> str:
        if days <= CONFIG['fast_duration_limit']:
            return 'FAST'
        elif days <= CONFIG['medium_duration_limit']:
            return 'MEDIUM'
        else:
            return 'LONG'

    # ----- НОРМАЛИЗАЦИЯ И ПЕРВИЧНАЯ ФИЛЬТРАЦИЯ -----

    def _normalize(self) -> List[Dict]:
        """
        Приводит все аспекты к единому формату, применяет object eligibility,
        aspect type filter, orb filter, phase/motion validation.
        """
        if self._normalized is not None:
            return self._normalized

        all_aspects = self.transit_aspects + self.transit_angle_aspects
        normalized = []

        for asp in all_aspects:
            # Проверка обязательных полей
            transit = asp.get('transit_planet')
            if transit not in self.ALLOWED_TRANSITS:
                continue

            target = asp.get('natal_planet') or asp.get('angle')
            if not target or not self._is_valid_target(target):
                continue

            aspect = asp.get('aspect')
            if not aspect or not self._is_major_aspect(aspect):
                continue

            orb = asp.get('orb', 10.0)
            max_orb = CONFIG['max_orb'].get(aspect, 8.0)
            if orb > max_orb:
                continue

            # Проверка фазы (движение)
            phase = asp.get('phase', '')
            # если фаза неизвестна, пропускаем
            if phase not in ('applying', 'exact', 'separating'):
                continue

            exact_date = asp.get('exact_date')
            if not exact_date:
                continue

            # Вторичные точки: Chiron имеет особый режим
            if target in self.SECONDARY_TARGETS:
                if target == 'Chiron':
                    if orb > CONFIG['chiron_orb_limit']:
                        continue
                    # significance threshold будет применён позже
                else:
                    continue  # остальные вторичные исключаем

            is_angle = 'angle' in asp
            # Базовый скоринг (используется для event_score)
            base_score = self._calculate_base_score(transit, target, aspect, orb, phase, is_angle)

            normalized.append({
                'transit_planet': transit,
                'natal_target': target,
                'aspect': aspect,
                'orb': orb,
                'phase': phase,
                'exact_date': exact_date,
                'is_angle': is_angle,
                'angle': asp.get('angle'),
                'house': asp.get('transit_house'),
                'sign': asp.get('transit_sign'),
                'base_score': base_score,
                'raw': asp
            })

        self._normalized = normalized
        return normalized

    def _calculate_base_score(self, transit: str, target: str, aspect: str,
                              orb: float, phase: str, is_angle: bool) -> float:
        """Базовый скоринг (общий для всех горизонтов)."""
        pw = self.PLANET_WEIGHT.get(transit, 1)
        tw = self.TARGET_WEIGHT.get(target, 1)
        aw = self.ASPECT_WEIGHT.get(aspect, 0.5)
        orb_factor = self._get_orb_factor(orb, aspect)
        phase_weight = CONFIG['phase_weight'].get(phase, 1.0)
        score = pw * tw * aw * orb_factor * phase_weight
        if is_angle:
            score *= CONFIG['angle_multiplier']
        return score

    # ----- НОРМАЛИЗАЦИЯ ОСЕЙ И ДЕДУПЛИКАЦИЯ -----

    def _normalize_axes(self, events: List[Dict]) -> List[Dict]:
        """
        Объединяет пары ASC/DSC и MC/IC в один объект.
        Возвращает список событий с нормализованными целями.
        """
        # Группируем по оси
        axis_groups = defaultdict(list)
        others = []

        for e in events:
            target = e['natal_target']
            if target in ('ASC', 'DSC'):
                key = (e['transit_planet'], e['aspect'], 'ASC_DSC')
                axis_groups[key].append(e)
            elif target in ('MC', 'IC'):
                key = (e['transit_planet'], e['aspect'], 'MC_IC')
                axis_groups[key].append(e)
            else:
                others.append(e)

        merged = []
        for key, items in axis_groups.items():
            if len(items) == 1:
                merged.append(items[0])
                continue

            # Объединяем несколько событий на одной оси
            # Выбираем основное (соединение с ASC/MC если есть)
            primary = None
            secondary = []
            for item in items:
                if item['natal_target'] in ('ASC', 'MC') and item['aspect'] == 'conjunction':
                    primary = item
                else:
                    secondary.append(item)

            if primary is None:
                # если нет соединения с основным углом, берём первое
                primary = items[0]
                secondary = items[1:]

            # Копируем основное, но меняем цель на нормализованную
            new_event = primary.copy()
            new_event['natal_target'] = self._normalize_target(primary['natal_target'])
            new_event['axis_primary'] = primary['natal_target']  # сохраняем для вывода
            new_event['secondary_axis'] = [s['natal_target'] for s in secondary]
            new_event['base_score'] = max(primary['base_score'], max(s['base_score'] for s in secondary) if secondary else 0)
            # Используем наибольший скоринг (не суммируем)
            merged.append(new_event)

        # Добавляем остальные события
        merged.extend(others)

        # Теперь нормализуем все оставшиеся цели (для единообразия)
        for e in merged:
            if e['natal_target'] not in ('ASC_DSC_AXIS', 'MC_IC_AXIS'):
                e['natal_target'] = self._normalize_target(e['natal_target'])

        return merged

    # ----- КЛАССИФИКАЦИЯ ПО ВРЕМЕНИ -----

    def _classify_duration(self, event: Dict) -> str:
        """
        Определяет класс длительности транзита.
        Для простоты используем среднюю скорость планеты для оценки длительности.
        """
        transit = event['transit_planet']
        # Средние скорости (градусов в день)
        speeds = {
            'Moon': 13.176, 'Sun': 0.986, 'Mercury': 1.383,
            'Venus': 1.2, 'Mars': 0.524, 'Jupiter': 0.083,
            'Saturn': 0.033, 'Uranus': 0.012, 'Neptune': 0.006,
            'Pluto': 0.004
        }
        speed = speeds.get(transit, 0.1)
        orb = event['orb']
        if speed <= 0:
            return 'FAST'  # fallback

        # Оцениваем длительность в днях по орбу и скорости (приблизительно)
        duration_days = (2 * orb) / speed  # две стороны от пика
        if duration_days <= CONFIG['fast_duration_limit']:
            return 'FAST'
        elif duration_days <= CONFIG['medium_duration_limit']:
            return 'MEDIUM'
        else:
            return 'LONG'

    # ----- ВЫЧИСЛЕНИЕ ДОЛГОСРОЧНЫХ ПРОЦЕССОВ (для MONTH и YEAR) -----

    def _merge_retrograde_passes(self, aspects: List[Dict]) -> List[Dict]:
        """Объединяет повторные проходы одного транзита в процессы."""
        groups = defaultdict(list)
        for asp in aspects:
            key = (asp['transit_planet'], asp['natal_target'], asp['aspect'])
            groups[key].append(asp)

        processes = []
        for key, items in groups.items():
            if not items:
                continue
            items.sort(key=lambda x: x['exact_date'])
            peaks = [i['exact_date'] for i in items]
            # Определяем полный интервал (от первого до последнего пика)
            full_start = peaks[0]
            full_end = peaks[-1]
            # Вычисляем длительность (приблизительно)
            try:
                start_dt = datetime.strptime(full_start, '%Y-%m-%d')
                end_dt = datetime.strptime(full_end, '%Y-%m-%d')
                duration_days = (end_dt - start_dt).days
            except:
                duration_days = 0

            # Берём лучший скоринг (максимальный)
            best = max(items, key=lambda x: x['base_score'])
            # Расширяем интервал до активного (с учётом орба и скорости)
            # Для простоты расширим на 30% длительности
            extra = max(1, int(duration_days * 0.3))
            if extra > 60:
                extra = 60
            try:
                start_dt = datetime.strptime(full_start, '%Y-%m-%d') - timedelta(days=extra)
                end_dt = datetime.strptime(full_end, '%Y-%m-%d') + timedelta(days=extra)
                active_start = start_dt.strftime('%Y-%m-%d')
                active_end = end_dt.strftime('%Y-%m-%d')
                active_duration = (end_dt - start_dt).days
            except:
                active_start = full_start
                active_end = full_end
                active_duration = duration_days

            process = {
                'transit_planet': best['transit_planet'],
                'natal_target': best['natal_target'],
                'aspect': best['aspect'],
                'full_start': full_start,
                'full_end': full_end,
                'active_start': active_start,
                'active_end': active_end,
                'peak_dates': peaks,
                'duration_days': duration_days,
                'active_duration_days': active_duration,
                'duration_class': self._get_duration_class(active_duration),
                'base_score': best['base_score'],
                'is_angle': best.get('is_angle', False),
                'angle': best.get('angle'),
                'house': best.get('house'),
                'all_aspects': items
            }
            processes.append(process)

        return processes

    # ----- СКОРИНГ ПО ГОРИЗОНТУ -----

    def _day_score(self, event: Dict, target_date: datetime) -> float:
        """Скоринг для дневного прогноза."""
        # Является ли событие активным сегодня?
        if not self._is_same_day(event['exact_date'], target_date):
            return 0.0

        # Базовый скоринг
        score = event['base_score']
        # Приоритет для быстрых транзитов
        duration_class = self._classify_duration(event)
        if duration_class == 'FAST':
            score *= 1.3
        else:
            # Медленные транзиты получают бонус только если точны сегодня
            if event['phase'] == 'exact' or event['orb'] < 0.5:
                score *= 1.1
            else:
                score *= 0.7
        # Углы получают бонус
        if event.get('is_angle'):
            score *= 1.2
        return score

    def _month_score(self, process: Dict, month_start: datetime, month_end: datetime) -> float:
        """Скоринг для месячного прогноза (на основе процесса)."""
        # Проверяем, пересекает ли процесс месяц
        if not self._overlaps_period(process['active_start'], process['active_end'], month_start, month_end):
            return 0.0

        score = process['base_score']
        # Бонус за длительность (MEDIUM/LONG)
        duration_class = process['duration_class']
        if duration_class in ('MEDIUM', 'LONG'):
            score *= 1.2
        # Бонус за пик внутри месяца
        peaks_in_month = [p for p in process['peak_dates'] if self._is_date_in_range(p, month_start, month_end)]
        if peaks_in_month:
            score *= 1.3
        return score

    def _year_score(self, process: Dict, year_start: datetime, year_end: datetime) -> float:
        """Скоринг для годового прогноза (на основе процесса)."""
        # Проверяем пересечение с годом
        if not self._overlaps_period(process['active_start'], process['active_end'], year_start, year_end):
            return 0.0

        score = process['base_score']
        # Бонус за длительность (LONG)
        if process['duration_class'] == 'LONG':
            score *= 1.5
        # Бонус за количество пиков
        if len(process['peak_dates']) > 1:
            score *= 1.2
        # Бонус за пик внутри года
        peaks_in_year = [p for p in process['peak_dates'] if self._is_date_in_range(p, year_start, year_end)]
        if peaks_in_year:
            score *= 1.1
        return score

    def _overlaps_period(self, start_str: str, end_str: str, period_start: datetime, period_end: datetime) -> bool:
        if not start_str or not end_str:
            return False
        try:
            s = datetime.strptime(start_str, '%Y-%m-%d')
            e = datetime.strptime(end_str, '%Y-%m-%d')
            return max(s, period_start) <= min(e, period_end)
        except:
            return False

    # ----- КЛАСТЕРИЗАЦИЯ ТЕМ С DIMINISHING RETURNS -----

    def _assign_theme(self, transit: str, target: str) -> str:
        """Возвращает тему по фиксированной таблице."""
        key = (transit, target)
        theme = self.THEME_MAP.get(key)
        if theme is None:
            # Пробуем обратный порядок (если таблица не покрывает)
            key_rev = (target, transit)
            theme = self.THEME_MAP.get(key_rev)
        return theme if theme else 'OTHER'

    def _cluster_themes(self, events: List[Dict], max_themes: int = 5) -> List[Dict]:
        """
        Группирует события по темам, применяет diminishing returns.
        Возвращает список тем с их скорингом.
        """
        # Определяем темы для каждого события
        themed_events = []
        for e in events:
            theme = self._assign_theme(e['transit_planet'], e['natal_target'])
            if theme == 'OTHER':
                continue
            themed_events.append((theme, e['base_score']))

        if not themed_events:
            return []

        # Группируем по темам
        groups = defaultdict(list)
        for theme, score in themed_events:
            groups[theme].append(score)

        # Сортируем скоринги внутри каждой темы по убыванию
        theme_scores = []
        for theme, scores in groups.items():
            sorted_scores = sorted(scores, reverse=True)
            # Применяем diminishing returns
            total = 0.0
            for i, s in enumerate(sorted_scores):
                weight = CONFIG['theme_diminishing_returns'][i] if i < len(CONFIG['theme_diminishing_returns']) else 0.125
                total += s * weight
            theme_scores.append({
                'name': theme,
                'score': total,
                'events_count': len(scores)
            })

        # Сортируем по убыванию скоринга
        theme_scores.sort(key=lambda x: x['score'], reverse=True)

        # Формируем описания
        result = []
        for ts in theme_scores[:max_themes]:
            # Собираем описания из событий, относящихся к этой теме
            descriptions = []
            for e in events:
                if self._assign_theme(e['transit_planet'], e['natal_target']) == ts['name']:
                    descriptions.append(
                        f"{self._format_planet(e['transit_planet'])} {self._format_aspect(e['aspect'])} {self._format_planet(e['natal_target'])}"
                    )
            result.append({
                'name': self._format_theme(ts['name']),
                'score': ts['score'],
                'description': ', '.join(descriptions[:3]),  # не более 3
                'raw_theme': ts['name']
            })

        return result

    # ----- ФИЛЬТРЫ -----

    def _filter_day(self) -> Dict[str, Any]:
        target_date = self.start_utc
        if not target_date:
            return {}

        normalized = self._normalize()
        # Применяем дневной фильтр: только события, активные сегодня
        day_events = []
        for e in normalized:
            # Проверяем, что событие точно сегодня
            if not self._is_same_day(e['exact_date'], target_date):
                continue
            # Вычисляем дневной скоринг
            score = self._day_score(e, target_date)
            if score <= 0:
                continue
            e['horizon_score'] = score
            day_events.append(e)

        # Нормализация осей
        day_events = self._normalize_axes(day_events)

        # Сортировка по horizon_score
        day_events.sort(key=lambda x: x['horizon_score'], reverse=True)

        # Ограничение количества
        max_events = CONFIG['day']['max_events']
        absolute_max = CONFIG['day']['absolute_max_events']
        top_events = day_events[:absolute_max]

        # Дополнительная фильтрация: если событий меньше min, оставляем сколько есть
        # (не добавляем слабые)

        # Угловые события
        angle_events = [e for e in top_events if e.get('is_angle')]

        # Темы
        themes = self._cluster_themes(top_events, max_themes=4)

        return {
            'type': 'DAY',
            'date': target_date.strftime('%Y-%m-%d'),
            'top_events': top_events,
            'angle_events': angle_events,
            'themes': themes
        }

    def _filter_month(self) -> Dict[str, Any]:
        start_date = self.start_utc
        end_date = self.end_utc
        if not start_date or not end_date:
            return {}

        normalized = self._normalize()
        # Фильтруем по дате: события, пересекающие месяц
        # Для месяца используем процессы, поэтому сначала собираем все аспекты за месяц
        month_aspects = []
        for e in normalized:
            if self._is_date_in_range(e['exact_date'], start_date, end_date):
                month_aspects.append(e)

        # Строим процессы из этих аспектов
        processes = self._merge_retrograde_passes(month_aspects)

        # Вычисляем месячный скоринг для каждого процесса
        for p in processes:
            p['horizon_score'] = self._month_score(p, start_date, end_date)

        # Фильтруем процессы с нулевым скорингом
        processes = [p for p in processes if p['horizon_score'] > 0]

        # Сортировка по horizon_score
        processes.sort(key=lambda x: x['horizon_score'], reverse=True)

        # Ограничиваем количество
        max_events = CONFIG['month']['max_events']
        main_processes = processes[:max_events]

        # Ключевые даты (пики внутри месяца)
        key_dates = defaultdict(list)
        for p in main_processes:
            for peak in p['peak_dates']:
                if self._is_date_in_range(peak, start_date, end_date):
                    key_dates[peak].append(
                        f"{self._format_planet(p['transit_planet'])} {self._format_aspect(p['aspect'])} {self._format_planet(p['natal_target'])} (пик)"
                    )

        # Ингрессии
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
            'key_dates': dict(key_dates),
            'important_ingresses': important_ingresses,
            'themes': themes
        }

    def _filter_year(self) -> Dict[str, Any]:
        start_date = self.start_utc
        end_date = self.end_utc
        if not start_date or not end_date:
            return {}

        normalized = self._normalize()
        # Оставляем только медленные планеты для года
        slow_planets = ['Pluto', 'Neptune', 'Uranus', 'Saturn', 'Jupiter']
        year_aspects = [e for e in normalized if e['transit_planet'] in slow_planets]
        # Фильтруем по диапазону (любое пересечение с годом)
        year_aspects = [e for e in year_aspects if self._is_date_in_range(e['exact_date'], start_date, end_date)]

        # Строим процессы
        processes = self._merge_retrograde_passes(year_aspects)

        # Вычисляем годовой скоринг
        for p in processes:
            p['horizon_score'] = self._year_score(p, start_date, end_date)

        # Фильтруем процессы с нулевым скорингом
        processes = [p for p in processes if p['horizon_score'] > 0]

        # Сортировка по horizon_score
        processes.sort(key=lambda x: x['horizon_score'], reverse=True)

        # Ограничиваем количество
        max_events = CONFIG['year']['max_events']
        main_processes = processes[:max_events]

        # Ключевые периоды (каждый процесс как период)
        key_periods = []
        for p in main_processes:
            key_periods.append({
                'start': p['active_start'],
                'end': p['active_end'],
                'process': f"{self._format_planet(p['transit_planet'])} {self._format_aspect(p['aspect'])} {self._format_planet(p['natal_target'])}",
                'theme': self._assign_theme(p['transit_planet'], p['natal_target']),
                'score': p['horizon_score'],
                'full_cycle': f"{p['full_start']} – {p['full_end']}",
                'peaks': p['peak_dates']
            })

        # Ингрессии
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
                if p['active_start'] and p['active_end']:
                    try:
                        p_start = datetime.strptime(p['active_start'], '%Y-%m-%d')
                        p_end = datetime.strptime(p['active_end'], '%Y-%m-%d')
                        if p_start <= month_end and p_end >= month_start:
                            month_themes.append(self._format_theme(self._assign_theme(p['transit_planet'], p['natal_target'])))
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
            'key_periods': key_periods,
            'major_ingresses': major_ingresses,
            'themes': themes,
            'monthly_summary': monthly_summary
        }

    # ----- ВЫВОД В ТЕКСТ -----

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
                score = e.get('horizon_score', e['base_score'])
                line = f"{i}. {planet} {aspect} {target}, орб {orb:.2f}°, фаза {phase}, значимость {score:.1f}"
                if e.get('secondary_axis'):
                    supp = [self._format_planet(s) for s in e['secondary_axis']]
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
                score = e.get('horizon_score', e['base_score'])
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
                lines.append(f"   Полный цикл: {p['full_start']} – {p['full_end']}")
                lines.append(f"   Активно в периоде: {p['active_start']} – {p['active_end']}")
                lines.append(f"   Пики: {', '.join(p['peak_dates'])}")
                lines.append(f"   Длительность полного цикла: {p['duration_days']} дней")
                lines.append(f"   Длительность в прогнозном периоде: {p['active_duration_days']} дней")
                lines.append(f"   Значимость: {p.get('horizon_score', p['base_score']):.1f}")
                theme_name = self._assign_theme(p['transit_planet'], p['natal_target'])
                lines.append(f"   Тема: {self._format_theme(theme_name)}")
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
                lines.append(f"   Полный цикл: {p['full_start']} – {p['full_end']}")
                lines.append(f"   Активно в {data.get('year')}: {p['active_start']} – {p['active_end']}")
                lines.append(f"   Пики в {data.get('year')}: {', '.join(p['peak_dates'])}")
                lines.append(f"   Длительность полного цикла: {p['duration_days']} дней")
                lines.append(f"   Длительность в прогнозном периоде: {p['active_duration_days']} дней")
                lines.append(f"   Значимость: {p.get('horizon_score', p['base_score']):.1f}")
                theme_name = self._assign_theme(p['transit_planet'], p['natal_target'])
                lines.append(f"   Тема: {self._format_theme(theme_name)}")
            lines.append("")

        if data.get('key_periods'):
            lines.append("## КЛЮЧЕВЫЕ ПЕРИОДЫ ГОДА")
            for p in data['key_periods']:
                lines.append(f"{p['start']} – {p['end']}: {p['process']} (тема: {self._format_theme(p['theme'])}), значимость {p['score']:.1f}")
                if 'peaks' in p:
                    lines.append(f"   Пики: {', '.join(p['peaks'])}")
                if 'full_cycle' in p:
                    lines.append(f"   Полный цикл: {p['full_cycle']}")
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
        data = self._filter_day()
        return self._format_day_output(data)

    def build_month_context(self) -> str:
        data = self._filter_month()
        return self._format_month_output(data)

    def build_year_context(self) -> str:
        data = self._filter_year()
        return self._format_year_output(data)