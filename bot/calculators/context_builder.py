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
    "full_orb": {
        "conjunction": 8.0,
        "opposition": 8.0,
        "square": 6.0,
        "trine": 6.0,
        "sextile": 5.0,
    },
    "active_orb": {
        "conjunction": 3.0,
        "opposition": 3.0,
        "square": 2.5,
        "trine": 2.5,
        "sextile": 2.0,
    },
    "planet_speed": {
        'Moon': 13.176,
        'Sun': 0.986,
        'Mercury': 1.383,
        'Venus': 1.2,
        'Mars': 0.524,
        'Jupiter': 0.083,
        'Saturn': 0.033,
        'Uranus': 0.012,
        'Neptune': 0.006,
        'Pluto': 0.004,
    },
    "min_theme_event_score": 6.0,
    "debug": True,
}


# ============================================================================
# ОСНОВНОЙ КЛАСС
# ============================================================================

class AstrologyContextBuilder:
    """
    Класс для построения контекста для трёх типов прогнозов: ДЕНЬ, МЕСЯЦ, ГОД.
    Реализует полный pipeline фильтрации согласно FINAL PATCH v2.0.
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
                       'ASC', 'MC', 'DSC', 'IC'}

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

    def _get_orb_factor(self, orb: float, aspect: str) -> float:
        max_orb = CONFIG['full_orb'].get(aspect, 8.0)
        if max_orb <= 0:
            return 0.0
        factor = 1.0 - (orb / max_orb)
        return max(0.0, min(1.0, factor))

    def _is_valid_target(self, target: str) -> bool:
        if target in self.PRIMARY_TARGETS:
            return True
        if CONFIG['secondary_points_enabled']:
            return True
        return False

    def _is_major_aspect(self, aspect: str) -> bool:
        if not CONFIG['minor_aspects_enabled']:
            return aspect in self.MAJOR_ASPECTS
        return True

    # ----- РАСЧЁТ ИНТЕРВАЛОВ -----

    def _calculate_intervals(self, transit_planet: str, aspect_type: str, peak_date: str, orb_at_peak: float) -> Dict:
        """Вычисляет full_cycle и active_window на основе средней скорости планеты и орбов."""
        speed = CONFIG['planet_speed'].get(transit_planet, 0.1)
        if speed <= 0:
            speed = 0.1

        full_orb = CONFIG['full_orb'].get(aspect_type, 8.0)
        active_orb = CONFIG['active_orb'].get(aspect_type, 3.0)

        full_duration = (full_orb / speed) * 2
        active_duration = (active_orb / speed) * 2

        try:
            peak_dt = datetime.strptime(peak_date, '%Y-%m-%d')
        except ValueError:
            return {
                'full_start': None,
                'full_end': None,
                'active_start': None,
                'active_end': None,
                'full_duration_days': 0,
                'active_duration_days': 0
            }

        full_start_dt = peak_dt - timedelta(days=full_duration / 2)
        full_end_dt = peak_dt + timedelta(days=full_duration / 2)
        active_start_dt = peak_dt - timedelta(days=active_duration / 2)
        active_end_dt = peak_dt + timedelta(days=active_duration / 2)

        return {
            'full_start': full_start_dt.strftime('%Y-%m-%d'),
            'full_end': full_end_dt.strftime('%Y-%m-%d'),
            'active_start': active_start_dt.strftime('%Y-%m-%d'),
            'active_end': active_end_dt.strftime('%Y-%m-%d'),
            'full_duration_days': int(full_duration),
            'active_duration_days': int(active_duration)
        }

    # ----- НОРМАЛИЗАЦИЯ И ПЕРВИЧНАЯ ФИЛЬТРАЦИЯ -----

    def _normalize(self) -> List[Dict]:
        if self._normalized is not None:
            return self._normalized

        all_aspects = self.transit_aspects + self.transit_angle_aspects
        normalized = []

        for asp in all_aspects:
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
            max_orb = CONFIG['full_orb'].get(aspect, 8.0)
            if orb > max_orb:
                continue

            phase = asp.get('phase', '')
            if phase not in ('applying', 'exact', 'separating'):
                continue

            exact_date = asp.get('exact_date')
            if not exact_date:
                continue

            if target in self.SECONDARY_TARGETS:
                if target == 'Chiron':
                    if orb > CONFIG.get('chiron_orb_limit', 1.5):
                        continue
                else:
                    continue

            is_angle = 'angle' in asp
            base_score = self._calculate_base_score(transit, target, aspect, orb, phase, is_angle)

            intervals = self._calculate_intervals(transit, aspect, exact_date, orb)

            event = {
                'transit_planet': transit,
                'natal_target': target,
                'aspect': aspect,
                'orb': orb,
                'phase': phase,
                'exact_peak_date': exact_date,
                'is_angle': is_angle,
                'angle': asp.get('angle'),
                'house': asp.get('transit_house'),
                'sign': asp.get('transit_sign'),
                'base_score': base_score,
                'raw': asp,
                'full_start': intervals['full_start'],
                'full_end': intervals['full_end'],
                'active_start': intervals['active_start'],
                'active_end': intervals['active_end'],
                'full_duration_days': intervals['full_duration_days'],
                'active_duration_days': intervals['active_duration_days'],
                'included_reason': [],
                'forecast_overlap_start': None,
                'forecast_overlap_end': None,
                'axis_events': []
            }

            # Валидация: full_start <= peak <= full_end
            if event['full_start'] and event['full_end']:
                try:
                    fs = datetime.strptime(event['full_start'], '%Y-%m-%d')
                    fe = datetime.strptime(event['full_end'], '%Y-%m-%d')
                    peak = datetime.strptime(event['exact_peak_date'], '%Y-%m-%d')
                    if not (fs <= peak <= fe):
                        if peak < fs:
                            event['full_start'] = peak.strftime('%Y-%m-%d')
                        if peak > fe:
                            event['full_end'] = peak.strftime('%Y-%m-%d')
                except:
                    pass

            normalized.append(event)

        self._normalized = normalized
        return normalized

    def _calculate_base_score(self, transit: str, target: str, aspect: str,
                              orb: float, phase: str, is_angle: bool) -> float:
        pw = self.PLANET_WEIGHT.get(transit, 1)
        tw = self.TARGET_WEIGHT.get(target, 1)
        aw = self.ASPECT_WEIGHT.get(aspect, 0.5)
        orb_factor = self._get_orb_factor(orb, aspect)
        phase_weight = CONFIG['phase_weight'].get(phase, 1.0)
        score = pw * tw * aw * orb_factor * phase_weight
        if is_angle:
            score *= CONFIG['angle_multiplier']
        return score

    # ----- ВСПОМОГАТЕЛЬНЫЕ ДЛЯ ДАТ -----

    def _to_naive(self, dt: datetime) -> datetime:
        if dt.tzinfo is not None:
            return dt.replace(tzinfo=None)
        return dt

    def _is_same_day(self, date_str: str, target_date: datetime) -> bool:
        if not date_str or not target_date:
            return False
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d').date()
            target_naive = self._to_naive(target_date)
            return dt == target_naive.date()
        except ValueError:
            return False

    def _is_date_in_range(self, date_str: str, start: datetime, end: datetime) -> bool:
        if not date_str or not start or not end:
            return False
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            start_naive = self._to_naive(start)
            end_naive = self._to_naive(end)
            return start_naive <= dt <= end_naive
        except ValueError:
            return False

    def _overlaps_period(self, start_str: str, end_str: str, period_start: datetime, period_end: datetime) -> bool:
        if not start_str or not end_str:
            return False
        try:
            s = datetime.strptime(start_str, '%Y-%m-%d')
            e = datetime.strptime(end_str, '%Y-%m-%d')
            ps = self._to_naive(period_start)
            pe = self._to_naive(period_end)
            return max(s, ps) <= min(e, pe)
        except ValueError:
            return False

    def _get_forecast_overlap(self, event: Dict, forecast_start: datetime, forecast_end: datetime) -> Tuple[Optional[str], Optional[str]]:
        """Вычисляет пересечение ACTIVE_WINDOW с прогнозным периодом."""
        if not event['active_start'] or not event['active_end']:
            return None, None
        try:
            s = datetime.strptime(event['active_start'], '%Y-%m-%d')
            e = datetime.strptime(event['active_end'], '%Y-%m-%d')
            fs = self._to_naive(forecast_start)
            fe = self._to_naive(forecast_end)
            overlap_start = max(s, fs)
            overlap_end = min(e, fe)
            if overlap_start <= overlap_end:
                return overlap_start.strftime('%Y-%m-%d'), overlap_end.strftime('%Y-%m-%d')
            return None, None
        except ValueError:
            return None, None

    def _normalize_theme_score(self, raw_score: float, event_count: int) -> float:
        if event_count == 0:
            return 0.0
        return raw_score / (event_count ** 0.5)

    # ----- ДЕДУПЛИКАЦИЯ -----

    def _get_canonical_key(self, event: Dict) -> str:
        target = event['natal_target']
        if target in ('ASC', 'DSC'):
            return f"{event['transit_planet']}_{event['aspect']}_AXIS_ASC_DSC"
        if target in ('MC', 'IC'):
            return f"{event['transit_planet']}_{event['aspect']}_AXIS_MC_IC"
        return f"{event['transit_planet']}_{event['natal_target']}_{event['aspect']}"

    def _deduplicate_axes(self, events: List[Dict]) -> List[Dict]:
        groups = defaultdict(list)
        for e in events:
            key = self._get_canonical_key(e)
            groups[key].append(e)

        deduped = []
        for key, items in groups.items():
            if len(items) == 1:
                deduped.append(items[0])
            else:
                best = max(items, key=lambda x: x['base_score'])
                best['axis_events'] = items
                deduped.append(best)

        return deduped

    def _deduplicate_exact(self, events: List[Dict]) -> List[Dict]:
        seen = set()
        unique = []
        for e in events:
            key = (e['transit_planet'], e['natal_target'], e['aspect'], e['exact_peak_date'])
            if key not in seen:
                seen.add(key)
                unique.append(e)
        return unique

    # ----- ТЕМЫ -----

    def _assign_theme(self, transit: str, target: str) -> str:
        key = (transit, target)
        theme = self.THEME_MAP.get(key)
        if theme is None:
            key_rev = (target, transit)
            theme = self.THEME_MAP.get(key_rev)
        return theme if theme else 'OTHER'

    def _cluster_themes(self, events: List[Dict], max_themes: int = 5) -> List[Dict]:
        min_score = CONFIG['min_theme_event_score']
        filtered_events = [e for e in events if e['base_score'] >= min_score]

        if not filtered_events:
            return []

        groups = defaultdict(list)
        for e in filtered_events:
            theme = self._assign_theme(e['transit_planet'], e['natal_target'])
            if theme == 'OTHER':
                continue
            groups[theme].append(e['base_score'])

        theme_scores = []
        for theme, scores in groups.items():
            raw_score = sum(scores)
            normalized_score = self._normalize_theme_score(raw_score, len(scores))
            theme_scores.append({
                'name': theme,
                'score': normalized_score,
                'raw_score': raw_score,
                'events_count': len(scores)
            })

        theme_scores.sort(key=lambda x: x['score'], reverse=True)

        result = []
        for ts in theme_scores[:max_themes]:
            descriptions = []
            for e in filtered_events:
                if self._assign_theme(e['transit_planet'], e['natal_target']) == ts['name']:
                    descriptions.append(
                        f"{self._format_planet(e['transit_planet'])} {self._format_aspect(e['aspect'])} {self._format_planet(e['natal_target'])}"
                    )
            result.append({
                'name': self._format_theme(ts['name']),
                'score': ts['score'],
                'raw_score': ts['raw_score'],
                'description': ', '.join(descriptions[:3]),
                'events_count': ts['events_count']
            })

        return result

    # ----- СКОРИНГ ПО ГОРИЗОНТУ (без изменения raw_significance) -----

    def _day_score(self, event: Dict, target_date: datetime) -> float:
        if not self._is_same_day(event['exact_peak_date'], target_date):
            if event['active_start'] and event['active_end']:
                if self._is_date_in_range(event['active_start'], target_date, target_date) or \
                   self._is_date_in_range(event['active_end'], target_date, target_date):
                    return event['base_score'] * 0.7
            return 0.0

        score = event['base_score']
        if event['is_angle']:
            score *= 1.2
        if event['phase'] == 'exact' or event['orb'] < 0.5:
            score *= 1.15
        if event['transit_planet'] in ['Moon', 'Sun', 'Mercury', 'Venus', 'Mars']:
            score *= 1.1
        return score

    def _month_score(self, event: Dict, month_start: datetime, month_end: datetime) -> float:
        overlap = self._get_forecast_overlap(event, month_start, month_end)
        if overlap[0] is None:
            return 0.0
        score = event['base_score']
        if self._is_date_in_range(event['exact_peak_date'], month_start, month_end):
            score *= 1.2
        # Дополнительно учитываем длительность пересечения
        try:
            overlap_start = datetime.strptime(overlap[0], '%Y-%m-%d')
            overlap_end = datetime.strptime(overlap[1], '%Y-%m-%d')
            overlap_days = (overlap_end - overlap_start).days
            if overlap_days > 15:
                score *= 1.1
        except:
            pass
        return score

    def _year_score(self, event: Dict, year_start: datetime, year_end: datetime) -> float:
        overlap = self._get_forecast_overlap(event, year_start, year_end)
        if overlap[0] is None:
            return 0.0
        score = event['base_score']
        if self._is_date_in_range(event['exact_peak_date'], year_start, year_end):
            score *= 1.1
        if event['full_duration_days'] > 120:
            score *= 1.3
        elif event['full_duration_days'] > 60:
            score *= 1.15
        return score

    # ----- ФИЛЬТР ИНГРЕССИЙ -----

    def _filter_ingresses(self, start_date: datetime, end_date: datetime, only_slow: bool = False) -> List[Dict]:
        important_ingresses = []
        for ing in self.transit_ingresses:
            if not self._is_date_in_range(ing.get('date'), start_date, end_date):
                continue
            planet = ing.get('planet')
            if only_slow:
                if planet in ['Pluto', 'Neptune', 'Uranus', 'Saturn', 'Jupiter']:
                    important_ingresses.append(ing)
            else:
                if planet in ['Pluto', 'Neptune', 'Uranus', 'Saturn', 'Jupiter']:
                    important_ingresses.append(ing)
                elif planet == 'Mars' and ing.get('type') == 'house' and int(ing.get('to', 0)) in [1, 4, 5, 7, 8, 10]:
                    important_ingresses.append(ing)
        return important_ingresses

    # ----- МЕСЯЧНАЯ АГРЕГАЦИЯ (независимая) -----

    def _build_monthly_aggregation(self, events: List[Dict], year_start: datetime, year_end: datetime) -> List[Dict]:
        monthly_results = []
        for month in range(1, 13):
            month_start = year_start.replace(month=month, day=1)
            if month_start > year_end:
                break
            month_end = min(year_end, month_start.replace(day=28) + timedelta(days=4) - timedelta(days=1))

            month_events = []
            for e in events:
                overlap = self._get_forecast_overlap(e, month_start, month_end)
                if overlap[0] is not None:
                    month_events.append(e)

            month_themes = self._cluster_themes(month_events, max_themes=3)
            if month_themes:
                monthly_results.append({
                    'month': month_start.strftime('%B'),
                    'themes': month_themes
                })
            else:
                monthly_results.append({
                    'month': month_start.strftime('%B'),
                    'themes': []
                })

        return monthly_results

    # ----- ДЕБАГ ИСКЛЮЧЁННЫХ -----

    def _get_excluded_events(self, all_events: List[Dict], selected_events: List[Dict]) -> List[Dict]:
        selected_keys = set()
        for e in selected_events:
            key = self._get_canonical_key(e)
            selected_keys.add(key)

        excluded = []
        for e in all_events:
            key = self._get_canonical_key(e)
            if key not in selected_keys:
                excluded.append(e)
        return excluded

    # ----- ФИЛЬТРЫ -----

    def _filter_day(self) -> Dict[str, Any]:
        target_date = self.start_utc
        if not target_date:
            return {}

        normalized = self._normalize()
        day_candidates = []
        for e in normalized:
            score = self._day_score(e, target_date)
            if score <= 0:
                continue
            e['horizon_score'] = score
            e['included_reason'] = []
            if self._is_same_day(e['exact_peak_date'], target_date):
                if e['is_angle']:
                    e['included_reason'].append('ANGLE')
                if e['phase'] == 'exact' or e['orb'] < 0.5:
                    e['included_reason'].append('EXACT_PEAK')
                if e['base_score'] > 15:
                    e['included_reason'].append('HIGH_SIGNIFICANCE')
                if e['transit_planet'] in ['Pluto', 'Neptune', 'Uranus', 'Saturn', 'Jupiter']:
                    e['included_reason'].append('SLOW_TRANSIT')
                if not e['included_reason']:
                    e['included_reason'].append('ACTIVE_IN_PERIOD')
            else:
                if self._overlaps_period(e['active_start'], e['active_end'], target_date, target_date):
                    e['included_reason'].append('ACTIVE_IN_PERIOD')
                else:
                    e['included_reason'].append('ACTIVE_IN_PERIOD')
            day_candidates.append(e)

        # Дедупликация осей перед сортировкой
        day_candidates = self._deduplicate_axes(day_candidates)

        def sort_key(e):
            priority = 0
            if e['is_angle']:
                priority += 1000
            if e['phase'] == 'exact' or e['orb'] < 0.5:
                priority += 100
            if e['transit_planet'] in ['Pluto', 'Neptune', 'Uranus', 'Saturn', 'Jupiter']:
                priority += 10
            return (priority, e['horizon_score'], -e['orb'])

        day_candidates.sort(key=sort_key, reverse=True)

        max_events = CONFIG['day']['absolute_max_events']
        top_events = day_candidates[:max_events]

        top_events = self._deduplicate_exact(top_events)

        angle_events = [e for e in top_events if e.get('is_angle')]

        themes = self._cluster_themes(top_events, max_themes=4)

        result = {
            'type': 'DAY',
            'date': target_date.strftime('%Y-%m-%d'),
            'top_events': top_events,
            'angle_events': angle_events,
            'themes': themes
        }

        if CONFIG.get('debug', False):
            excluded_events = self._get_excluded_events(day_candidates, top_events)
            debug_excluded = []
            for e in excluded_events:
                debug_excluded.append({
                    'event': f"{self._format_planet(e['transit_planet'])} {self._format_aspect(e['aspect'])} {self._format_planet(e['natal_target'])}",
                    'reason': 'below selection threshold',
                    'score': e['base_score'],
                    'orb': e['orb']
                })
            result['debug_excluded'] = debug_excluded

        return result

    def _filter_month(self) -> Dict[str, Any]:
        start_date = self.start_utc
        end_date = self.end_utc
        if not start_date or not end_date:
            return {}

        normalized = self._normalize()
        month_candidates = []

        for e in normalized:
            overlap = self._get_forecast_overlap(e, start_date, end_date)
            if overlap[0] is None:
                continue

            score = self._month_score(e, start_date, end_date)
            if score <= 0:
                continue

            e['horizon_score'] = score
            e['included_reason'] = ['ACTIVE_IN_PERIOD']
            e['forecast_overlap_start'] = overlap[0]
            e['forecast_overlap_end'] = overlap[1]

            if self._is_date_in_range(e['exact_peak_date'], start_date, end_date):
                e['included_reason'].append('EXACT_PEAK')

            month_candidates.append(e)

        # Дедупликация осей
        month_candidates = self._deduplicate_axes(month_candidates)

        month_candidates.sort(key=lambda x: (x['horizon_score'], -x['orb']), reverse=True)

        max_events = CONFIG['month']['max_events']
        main_events = month_candidates[:max_events]

        main_events = self._deduplicate_exact(main_events)

        key_dates = defaultdict(list)
        for e in main_events:
            if self._is_date_in_range(e['exact_peak_date'], start_date, end_date):
                key_dates[e['exact_peak_date']].append(
                    f"{self._format_planet(e['transit_planet'])} {self._format_aspect(e['aspect'])} {self._format_planet(e['natal_target'])} (пик)"
                )

        important_ingresses = self._filter_ingresses(start_date, end_date)

        themes = self._cluster_themes(main_events, max_themes=5)

        monthly_aggregation = self._build_monthly_aggregation(main_events, start_date, end_date)

        result = {
            'type': 'MONTH',
            'period': {'start': start_date.strftime('%Y-%m-%d'), 'end': end_date.strftime('%Y-%m-%d')},
            'main_events': main_events,
            'key_dates': dict(key_dates),
            'important_ingresses': important_ingresses,
            'themes': themes,
            'monthly_aggregation': monthly_aggregation
        }

        if CONFIG.get('debug', False):
            excluded_events = self._get_excluded_events(month_candidates, main_events)
            debug_excluded = []
            for e in excluded_events:
                debug_excluded.append({
                    'event': f"{self._format_planet(e['transit_planet'])} {self._format_aspect(e['aspect'])} {self._format_planet(e['natal_target'])}",
                    'reason': 'below selection threshold',
                    'score': e['base_score'],
                    'orb': e['orb']
                })
            result['debug_excluded'] = debug_excluded

        return result

    def _filter_year(self) -> Dict[str, Any]:
        start_date = self.start_utc
        end_date = self.end_utc
        if not start_date or not end_date:
            return {}

        normalized = self._normalize()
        slow_planets = ['Pluto', 'Neptune', 'Uranus', 'Saturn', 'Jupiter']
        year_candidates = []

        for e in normalized:
            if e['transit_planet'] not in slow_planets:
                continue

            overlap = self._get_forecast_overlap(e, start_date, end_date)
            if overlap[0] is None:
                continue

            score = self._year_score(e, start_date, end_date)
            if score <= 0:
                continue

            e['horizon_score'] = score
            e['included_reason'] = ['ACTIVE_IN_PERIOD']
            e['forecast_overlap_start'] = overlap[0]
            e['forecast_overlap_end'] = overlap[1]

            if self._is_date_in_range(e['exact_peak_date'], start_date, end_date):
                e['included_reason'].append('EXACT_PEAK')

            year_candidates.append(e)

        # Дедупликация осей
        year_candidates = self._deduplicate_axes(year_candidates)

        year_candidates.sort(key=lambda x: (x['horizon_score'], -x['orb']), reverse=True)

        max_events = CONFIG['year']['max_events']
        main_events = year_candidates[:max_events]

        main_events = self._deduplicate_exact(main_events)

        key_periods = []
        for e in main_events:
            full_cycle = f"{e['full_start']} – {e['full_end']}" if e['full_start'] and e['full_end'] else "не рассчитан"
            active_in_year = self._get_forecast_overlap(e, start_date, end_date)
            active_str = f"{active_in_year[0]} – {active_in_year[1]}" if active_in_year[0] and active_in_year[1] else "не пересекается"
            key_periods.append({
                'full_cycle': full_cycle,
                'active_in_period': active_str,
                'peak': e['exact_peak_date'],
                'process': f"{self._format_planet(e['transit_planet'])} {self._format_aspect(e['aspect'])} {self._format_planet(e['natal_target'])}",
                'theme': self._assign_theme(e['transit_planet'], e['natal_target']),
                'score': e['horizon_score'],
                'duration': e['full_duration_days']
            })

        major_ingresses = self._filter_ingresses(start_date, end_date, only_slow=True)

        themes = self._cluster_themes(main_events, max_themes=6)

        monthly_aggregation = self._build_monthly_aggregation(main_events, start_date, end_date)

        result = {
            'type': 'YEAR',
            'year': start_date.year,
            'main_events': main_events,
            'key_periods': key_periods,
            'major_ingresses': major_ingresses,
            'themes': themes,
            'monthly_aggregation': monthly_aggregation
        }

        if CONFIG.get('debug', False):
            excluded_events = self._get_excluded_events(year_candidates, main_events)
            debug_excluded = []
            for e in excluded_events:
                debug_excluded.append({
                    'event': f"{self._format_planet(e['transit_planet'])} {self._format_aspect(e['aspect'])} {self._format_planet(e['natal_target'])}",
                    'reason': 'below selection threshold',
                    'score': e['base_score'],
                    'orb': e['orb']
                })
            result['debug_excluded'] = debug_excluded

        return result

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
                reasons = ', '.join(e.get('included_reason', []))
                line = f"{i}. {planet} {aspect} {target}, орб {orb:.2f}°, фаза {phase}, значимость {score:.1f}"
                if reasons:
                    line += f" [{reasons}]"
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

        if data.get('debug_excluded') and CONFIG.get('debug', False):
            lines.append("## ИСКЛЮЧЁННЫЕ СОБЫТИЯ")
            for ex in data['debug_excluded']:
                lines.append(f"- {ex['event']}: {ex['reason']} (score: {ex['score']:.1f}, orb: {ex['orb']:.2f}°)")
            lines.append("")

        return "\n".join(lines)

    def _format_month_output(self, data: Dict) -> str:
        lines = []
        lines.append("## КОНТЕКСТ ПРОГНОЗА")
        lines.append("Тип: МЕСЯЦ")
        period = data.get('period', {})
        lines.append(f"Период: {period.get('start', '')} – {period.get('end', '')}")
        lines.append("")

        if data.get('main_events'):
            lines.append("## ГЛАВНЫЕ ПРОЦЕССЫ МЕСЯЦА")
            for i, e in enumerate(data['main_events'], 1):
                planet = self._format_planet(e['transit_planet'])
                target = self._format_planet(e['natal_target'])
                aspect = self._format_aspect(e['aspect'])
                lines.append(f"{i}. {planet} {aspect} {target}")
                lines.append(f"   Полный цикл: {e['full_start']} – {e['full_end']}" if e['full_start'] and e['full_end'] else "   Полный цикл: не рассчитан")
                lines.append(f"   Активно в периоде: {e['active_start']} – {e['active_end']}" if e['active_start'] and e['active_end'] else "   Активно в периоде: не рассчитано")
                if e['forecast_overlap_start'] and e['forecast_overlap_end']:
                    lines.append(f"   Пересечение с периодом: {e['forecast_overlap_start']} – {e['forecast_overlap_end']}")
                lines.append(f"   Пик: {e['exact_peak_date']}")
                lines.append(f"   Длительность полного цикла: {e['full_duration_days']} дней")
                lines.append(f"   Длительность активного периода: {e['active_duration_days']} дней")
                lines.append(f"   Значимость: {e.get('horizon_score', e['base_score']):.1f}")
                theme = self._assign_theme(e['transit_planet'], e['natal_target'])
                if theme != 'OTHER':
                    lines.append(f"   Тема: {self._format_theme(theme)}")
                reasons = ', '.join(e.get('included_reason', []))
                if reasons:
                    lines.append(f"   Причина включения: {reasons}")
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

        if data.get('debug_excluded') and CONFIG.get('debug', False):
            lines.append("## ИСКЛЮЧЁННЫЕ СОБЫТИЯ")
            for ex in data['debug_excluded']:
                lines.append(f"- {ex['event']}: {ex['reason']} (score: {ex['score']:.1f}, orb: {ex['orb']:.2f}°)")
            lines.append("")

        return "\n".join(lines)

    def _format_year_output(self, data: Dict) -> str:
        lines = []
        lines.append("## КОНТЕКСТ ПРОГНОЗА")
        lines.append("Тип: ГОД")
        lines.append(f"Год: {data.get('year', '')}")
        lines.append("")

        if data.get('main_events'):
            lines.append("## ГЛАВНЫЕ ДОЛГОСРОЧНЫЕ ПРОЦЕССЫ ГОДА")
            for i, e in enumerate(data['main_events'], 1):
                planet = self._format_planet(e['transit_planet'])
                target = self._format_planet(e['natal_target'])
                aspect = self._format_aspect(e['aspect'])
                lines.append(f"{i}. {planet} {aspect} {target}")
                lines.append(f"   Полный цикл: {e['full_start']} – {e['full_end']}" if e['full_start'] and e['full_end'] else "   Полный цикл: не рассчитан")
                if e['forecast_overlap_start'] and e['forecast_overlap_end']:
                    lines.append(f"   Активно в {data.get('year')}: {e['forecast_overlap_start']} – {e['forecast_overlap_end']}")
                lines.append(f"   Пик: {e['exact_peak_date']}")
                lines.append(f"   Длительность полного цикла: {e['full_duration_days']} дней")
                lines.append(f"   Значимость: {e.get('horizon_score', e['base_score']):.1f}")
                theme = self._assign_theme(e['transit_planet'], e['natal_target'])
                if theme != 'OTHER':
                    lines.append(f"   Тема: {self._format_theme(theme)}")
                reasons = ', '.join(e.get('included_reason', []))
                if reasons:
                    lines.append(f"   Причина включения: {reasons}")
            lines.append("")

        if data.get('key_periods'):
            lines.append("## КЛЮЧЕВЫЕ ПЕРИОДЫ ГОДА")
            for p in data['key_periods']:
                lines.append(f"Полный цикл: {p['full_cycle']}")
                lines.append(f"Активно в периоде: {p['active_in_period']}")
                lines.append(f"Пик: {p['peak']}")
                lines.append(f"Процесс: {p['process']}")
                lines.append(f"Тема: {self._format_theme(p['theme']) if p['theme'] != 'OTHER' else 'Не определена'}")
                lines.append(f"Значимость: {p['score']:.1f}")
                lines.append("")
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

        if data.get('monthly_aggregation'):
            lines.append("## МЕСЯЧНАЯ АГРЕГАЦИЯ")
            for item in data['monthly_aggregation']:
                if item['themes']:
                    themes_str = ', '.join([f"{t['name']} ({t['score']:.1f})" for t in item['themes']])
                    lines.append(f"{item['month']}: {themes_str}")
                else:
                    lines.append(f"{item['month']}: нет активных тем")
            lines.append("")

        if data.get('debug_excluded') and CONFIG.get('debug', False):
            lines.append("## ИСКЛЮЧЁННЫЕ СОБЫТИЯ")
            for ex in data['debug_excluded']:
                lines.append(f"- {ex['event']}: {ex['reason']} (score: {ex['score']:.1f}, orb: {ex['orb']:.2f}°)")
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