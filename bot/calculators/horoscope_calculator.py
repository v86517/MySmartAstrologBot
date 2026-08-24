import logging
import zoneinfo
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Tuple, Set
import math
from dataclasses import dataclass, field
from enum import Enum

from kerykeion import AstrologicalSubject

from bot.calculators.astrology_calculator import AstrologyCalculator
from bot.calculators.natal_context_builder import NatalContextBuilder

logger = logging.getLogger(__name__)


class PeakStatus(Enum):
    TODAY = "today"
    TOMORROW = "tomorrow"
    YESTERDAY = "yesterday"
    FUTURE = "future"
    PAST = "past"


@dataclass
class TransitEvent:
    """Полное описание одного транзитного события."""
    transit_body: str
    transit_longitude: float
    transit_house: Optional[int]
    natal_target: str
    natal_target_longitude: float
    natal_target_house: Optional[int]
    aspect: str
    orb: float
    distance: float
    exact_angle: float
    applying: bool
    exact_datetime: Optional[datetime]
    days_to_exact: Optional[float]
    peak_status: PeakStatus
    active_today: bool
    axis: Optional[str]
    category: str
    score: float

    def unique_key(self) -> str:
        if self.axis:
            return f"{self.transit_body}:{self.axis}:{self.aspect}"
        return f"{self.transit_body}:{self.natal_target}:{self.aspect}"


class HoroscopeCalculator:
    """
    Калькулятор гороскопа на день с корректной математикой аспектов.
    """

    SIGN_OFFSET = {
        'Aries': 0, 'Taurus': 30, 'Gemini': 60, 'Cancer': 90,
        'Leo': 120, 'Virgo': 150, 'Libra': 180, 'Scorpio': 210,
        'Sagittarius': 240, 'Capricorn': 270, 'Aquarius': 300, 'Pisces': 330,
        'Ari': 0, 'Tau': 30, 'Gem': 60, 'Can': 90,
        'Leo': 120, 'Vir': 150, 'Lib': 180, 'Sco': 210,
        'Sag': 240, 'Cap': 270, 'Aqu': 300, 'Pis': 330
    }

    ASPECT_ANGLES = {
        'conjunction': 0,
        'sextile': 60,
        'square': 90,
        'trine': 120,
        'opposition': 180,
    }

    MAX_ORBS = {
        'conjunction': 6.0,
        'opposition': 6.0,
        'trine': 6.0,
        'square': 6.0,
        'sextile': 5.0,
    }

    ACTIVE_ORBS = {
        'Sun': 2.0,
        'Moon': 2.0,
        'Mercury': 2.0,
        'Venus': 2.0,
        'Mars': 2.0,
        'Jupiter': 3.0,
        'Saturn': 3.0,
        'Uranus': 2.5,
        'Neptune': 2.5,
        'Pluto': 2.5,
    }

    PLANET_WEIGHT = {
        'Pluto': 10, 'Neptune': 9, 'Uranus': 9, 'Saturn': 8,
        'Jupiter': 7, 'Mars': 6, 'Venus': 5, 'Mercury': 5,
        'Sun': 5, 'Moon': 4
    }

    TARGET_WEIGHT = {
        'Sun': 10, 'Moon': 10, 'ASC': 10, 'MC': 9,
        'Mercury': 8, 'Venus': 8, 'Mars': 8,
        'Jupiter': 6, 'Saturn': 6, 'Uranus': 5,
        'Neptune': 5, 'Pluto': 5
    }

    ASPECT_WEIGHT = {
        'conjunction': 1.0,
        'opposition': 0.95,
        'trine': 0.90,
        'square': 0.85,
        'sextile': 0.75
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

        self.astro_calc = AstrologyCalculator(
            user_data, lang=lang, telegram_id=telegram_id, coords=coords,
            emulation_mode=False
        )
        self.natal_data = self.astro_calc._build_natal_chart()
        self.subject = self.astro_calc._subject

        self.natal_planets = self.natal_data['planets']
        self.natal_angles = self.natal_data['angles']
        self.natal_houses = self.natal_data['houses']

        self.debug = True

        self.natal_targets = self._build_natal_targets()
        self._transit_cache = {}

        self.all_raw_events: List[TransitEvent] = []
        self.deduplicated_events: List[TransitEvent] = []
        self.filtered_events: List[TransitEvent] = []

    def _build_natal_targets(self) -> List[Dict]:
        targets = []
        main_names = {'Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                      'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto'}
        for p in self.natal_planets:
            if p['name'] in main_names:
                lon = self._normalize_longitude(p['sign'], p['degree'])
                targets.append({
                    'name': p['name'],
                    'longitude': lon,
                    'house': p['house'],
                    'is_angle': False,
                    'extra_type': None,
                    'weight': self.TARGET_WEIGHT.get(p['name'], 5)
                })

        angle_names = ['ASC', 'MC', 'DSC', 'IC']
        for angle in angle_names:
            if angle in self.natal_angles and self.natal_angles[angle] is not None:
                a = self.natal_angles[angle]
                lon = self._normalize_longitude(a['sign'], a['position'])
                if self.debug:
                    logger.info(f"🔍 Натальный угол {angle}: {a['sign']} {a['position']:.2f}° → abs {lon:.4f}")
                targets.append({
                    'name': angle,
                    'longitude': lon,
                    'house': None,
                    'is_angle': True,
                    'extra_type': 'angle',
                    'weight': self.TARGET_WEIGHT.get(angle, 9)
                })

        extra_names = ['True_North_Lunar_Node', 'True_South_Lunar_Node', 'Chiron', 'True_Lilith']
        for p in self.natal_planets:
            if p['name'] in extra_names:
                lon = self._normalize_longitude(p['sign'], p['degree'])
                extra_type = 'node' if 'Node' in p['name'] else 'chiron' if p['name'] == 'Chiron' else 'lilith'
                targets.append({
                    'name': p['name'],
                    'longitude': lon,
                    'house': p.get('house'),
                    'is_angle': False,
                    'extra_type': extra_type,
                    'weight': 3
                })
        return targets

    def _normalize_longitude(self, sign: str, degree: float) -> float:
        start = self.SIGN_OFFSET.get(sign, 0)
        if degree >= 30:
            if abs(degree - 30.0) < 0.001:
                next_sign = self._next_sign(sign)
                if next_sign:
                    return self.SIGN_OFFSET.get(next_sign, 0) + (degree - 30.0)
            return start + degree
        return start + degree

    def _next_sign(self, sign: str) -> Optional[str]:
        signs = ['Aries', 'Taurus', 'Gemini', 'Cancer', 'Leo', 'Virgo',
                 'Libra', 'Scorpio', 'Sagittarius', 'Capricorn', 'Aquarius', 'Pisces']
        full_signs = {
            'Ari': 'Aries', 'Tau': 'Taurus', 'Gem': 'Gemini', 'Can': 'Cancer',
            'Leo': 'Leo', 'Vir': 'Virgo', 'Lib': 'Libra', 'Sco': 'Scorpio',
            'Sag': 'Sagittarius', 'Cap': 'Capricorn', 'Aqu': 'Aquarius', 'Pis': 'Pisces'
        }
        full = full_signs.get(sign, sign)
        if full in signs:
            idx = signs.index(full)
            next_idx = (idx + 1) % 12
            return signs[next_idx]
        return None

    # ==================== КАНОНИЧЕСКАЯ ФУНКЦИЯ АСПЕКТА ====================

    def detect_aspect(self, transit_lon: float, natal_lon: float) -> Dict[str, Any]:
        """
        Единая каноническая функция определения аспекта.
        Возвращает immutable результат.
        """
        # Нормализуем в диапазон [0, 360)
        t_lon = transit_lon % 360
        n_lon = natal_lon % 360

        # Минимальное угловое расстояние
        diff = abs(t_lon - n_lon) % 360
        if diff > 180:
            distance = 360 - diff
        else:
            distance = diff

        # Находим ближайший аспект
        best_aspect = None
        best_orb = 360.0
        best_angle = None
        for aspect, exact_angle in self.ASPECT_ANGLES.items():
            orb = abs(distance - exact_angle)
            if orb < best_orb:
                best_orb = orb
                best_aspect = aspect
                best_angle = exact_angle

        if best_orb > 10.0:
            return {
                'aspect': None,
                'exact_angle': None,
                'distance': distance,
                'orb': best_orb
            }

        return {
            'aspect': best_aspect,
            'exact_angle': best_angle,
            'distance': distance,
            'orb': best_orb
        }

    # ==================== ТРАНЗИТНЫЕ ПОЗИЦИИ ====================

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
                        positions[planet] = self._normalize_longitude(sign, degree)
                else:
                    if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                        sign = getattr(obj, 'sign', '')
                        degree = getattr(obj, 'position', 0.0)
                        if sign:
                            positions[planet] = self._normalize_longitude(sign, degree)

        self._transit_cache[key] = positions
        return positions

    def _get_transit_position(self, date: datetime, planet: str) -> Optional[float]:
        positions = self._get_transit_positions(date)
        return positions.get(planet)

    def _get_transit_house(self, date: datetime, planet: str) -> int:
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

    # ==================== ОПРЕДЕЛЕНИЕ APPLYING ====================

    def _determine_applying(self, planet: str, natal_lon: float, aspect_angle: float,
                            forecast_date: datetime, exact_dt: datetime) -> bool:
        """
        Определяет applying/separating по изменению орба во времени.
        """
        # Используем шаг в 1 день для всех планет (для простоты)
        dt_before = exact_dt - timedelta(days=1)
        dt_after = exact_dt + timedelta(days=1)

        pos_before = self._get_transit_position(dt_before, planet)
        pos_after = self._get_transit_position(dt_after, planet)

        if pos_before is None or pos_after is None:
            return False

        # Вычисляем ошибку аспекта до и после
        def aspect_error(pos, lon, angle):
            dist = self._angular_distance(pos, lon)
            return dist - angle

        error_before = aspect_error(pos_before, natal_lon, aspect_angle)
        error_after = aspect_error(pos_after, natal_lon, aspect_angle)

        # Если ошибка уменьшается → applying
        return abs(error_before) > abs(error_after)

    def _angular_distance(self, lon1: float, lon2: float) -> float:
        diff = abs(lon1 - lon2) % 360
        if diff > 180:
            diff = 360 - diff
        return diff

    # ==================== ПОИСК ТОЧНОГО ВРЕМЕНИ ====================

    def _find_exact_datetime(self, planet: str, natal_lon: float, aspect_angle: float,
                             start_date: datetime, end_date: datetime) -> Optional[datetime]:
        start_pos = self._get_transit_position(start_date, planet)
        end_pos = self._get_transit_position(end_date, planet)
        if start_pos is None or end_pos is None:
            return None

        def error_at(date):
            pos = self._get_transit_position(date, planet)
            if pos is None:
                return None
            dist = self._angular_distance(pos, natal_lon)
            return dist - aspect_angle

        start_err = error_at(start_date)
        end_err = error_at(end_date)
        if start_err is None or end_err is None:
            return None

        eps = 0.0001
        max_iter = 100
        left = start_date
        right = end_date
        left_err = start_err
        right_err = end_err

        if left_err * right_err > 0:
            # Минимум абсолютной ошибки
            for _ in range(max_iter):
                mid = left + (right - left) / 2
                mid_err = error_at(mid)
                if mid_err is None:
                    break
                if abs(mid_err) < eps:
                    return mid
                if abs(mid_err) < abs(left_err):
                    left = mid
                    left_err = mid_err
                else:
                    right = mid
                    right_err = mid_err
                if (right - left).total_seconds() < 60:
                    break
            return left if abs(left_err) < abs(right_err) else right

        # Бинарный поиск (разные знаки)
        for _ in range(max_iter):
            mid = left + (right - left) / 2
            mid_err = error_at(mid)
            if mid_err is None:
                break
            if abs(mid_err) < eps:
                return mid
            if left_err * mid_err < 0:
                right = mid
                right_err = mid_err
            else:
                left = mid
                left_err = mid_err
            if (right - left).total_seconds() < 60:
                break
        return left if abs(left_err) < abs(right_err) else right

    # ==================== ОСНОВНОЙ РАСЧЁТ ====================

    def _calculate_all_events(self, forecast_date: datetime, days_range: int = 5) -> List[TransitEvent]:
        start = forecast_date - timedelta(days=days_range)
        end = forecast_date + timedelta(days=days_range)

        days = []
        current = start
        while current <= end:
            positions = self._get_transit_positions(current)
            days.append({'date': current, 'positions': positions})
            current += timedelta(days=1)

        if len(days) < 2:
            return []

        events: List[TransitEvent] = []

        for target in self.natal_targets:
            t_lon = target['longitude']
            for planet in ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                           'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']:
                has_position = any(planet in day['positions'] for day in days)
                if not has_position:
                    continue

                for aspect, aspect_angle in self.ASPECT_ANGLES.items():
                    exact_dt = self._find_exact_datetime(
                        planet, t_lon, aspect_angle,
                        start, end
                    )
                    if exact_dt is None:
                        continue

                    forecast_pos = self._get_transit_position(forecast_date, planet)
                    if forecast_pos is None:
                        continue

                    # Используем каноническую функцию определения аспекта
                    aspect_info = self.detect_aspect(forecast_pos, t_lon)
                    if aspect_info['aspect'] is None:
                        continue

                    max_orb = self.MAX_ORBS.get(aspect_info['aspect'], 6.0)
                    if aspect_info['orb'] > max_orb:
                        continue

                    # Логируем RAW аспект
                    if self.debug:
                        logger.info(
                            f"[ASPECT_RAW] {planet} → {target['name']} | "
                            f"transit_lon={forecast_pos:.4f}, target_lon={t_lon:.4f}, "
                            f"distance={aspect_info['distance']:.4f}, "
                            f"aspect={aspect_info['aspect']}, orb={aspect_info['orb']:.4f}"
                        )

                    # Определяем applying
                    applying = self._determine_applying(
                        planet, t_lon, aspect_angle,
                        forecast_date, exact_dt
                    )

                    # Вычисляем разницу
                    delta = exact_dt - forecast_date
                    days_to_exact = delta.total_seconds() / 3600 / 24

                    if abs(days_to_exact) < 0.5:
                        peak_status = PeakStatus.TODAY
                    elif days_to_exact > 0 and days_to_exact < 2:
                        peak_status = PeakStatus.TOMORROW
                    elif days_to_exact < 0 and days_to_exact > -2:
                        peak_status = PeakStatus.YESTERDAY
                    elif days_to_exact > 0:
                        peak_status = PeakStatus.FUTURE
                    else:
                        peak_status = PeakStatus.PAST

                    active_orb = self.ACTIVE_ORBS.get(planet, 2.5)
                    active_today = aspect_info['orb'] <= active_orb

                    transit_house = self._get_transit_house(forecast_date, planet)

                    score = self._calculate_score(
                        planet,
                        target,
                        aspect_info['aspect'],
                        aspect_info['orb'],
                        applying,
                        peak_status,
                        active_today
                    )

                    event = TransitEvent(
                        transit_body=planet,
                        transit_longitude=forecast_pos,
                        transit_house=transit_house,
                        natal_target=target['name'],
                        natal_target_longitude=t_lon,
                        natal_target_house=target['house'],
                        aspect=aspect_info['aspect'],
                        orb=aspect_info['orb'],
                        distance=aspect_info['distance'],
                        exact_angle=aspect_info['exact_angle'],
                        applying=applying,
                        exact_datetime=exact_dt,
                        days_to_exact=days_to_exact,
                        peak_status=peak_status,
                        active_today=active_today,
                        axis=None,
                        category='BACKGROUND',
                        score=score
                    )
                    events.append(event)

        return events

    def _calculate_score(self, planet: str, target: Dict, aspect: str,
                         orb: float, applying: bool, peak_status: PeakStatus,
                         active_today: bool) -> float:
        base = (self.PLANET_WEIGHT.get(planet, 5) *
                self.ASPECT_WEIGHT.get(aspect, 0.7) *
                target.get('weight', 5)) / 100

        orb_factor = max(0.2, 1 - orb / 6.0)
        phase_factor = 1.2 if applying else 0.9
        status_factor = {
            PeakStatus.TODAY: 1.5,
            PeakStatus.TOMORROW: 1.3,
            PeakStatus.YESTERDAY: 1.1,
            PeakStatus.FUTURE: 0.8,
            PeakStatus.PAST: 0.6
        }.get(peak_status, 0.8)
        active_factor = 1.2 if active_today else 0.8
        angle_factor = 1.3 if target.get('is_angle') else 1.0

        return base * orb_factor * phase_factor * status_factor * active_factor * angle_factor

    # ==================== ДЕДУПЛИКАЦИЯ И ОСИ ====================

    def _deduplicate_and_axes(self, events: List[TransitEvent]) -> List[TransitEvent]:
        # 1. Группируем оси ASC/DSC и MC/IC
        axis_groups = {}
        for ev in events:
            if ev.natal_target == 'ASC':
                key = (ev.transit_body, ev.aspect, 'ASC_DSC')
                if key not in axis_groups:
                    axis_groups[key] = {'asc': ev, 'dsc': None}
                axis_groups[key]['asc'] = ev
            elif ev.natal_target == 'DSC':
                key = (ev.transit_body, ev.aspect, 'ASC_DSC')
                if key not in axis_groups:
                    axis_groups[key] = {'asc': None, 'dsc': ev}
                axis_groups[key]['dsc'] = ev
            elif ev.natal_target == 'MC':
                key = (ev.transit_body, ev.aspect, 'MC_IC')
                if key not in axis_groups:
                    axis_groups[key] = {'mc': ev, 'ic': None}
                axis_groups[key]['mc'] = ev
            elif ev.natal_target == 'IC':
                key = (ev.transit_body, ev.aspect, 'MC_IC')
                if key not in axis_groups:
                    axis_groups[key] = {'mc': None, 'ic': ev}
                axis_groups[key]['ic'] = ev

        axis_events = []
        for key, pair in axis_groups.items():
            axis_name = key[2]
            if axis_name == 'ASC_DSC':
                asc_ev = pair.get('asc')
                dsc_ev = pair.get('dsc')
                if asc_ev and dsc_ev:
                    ev = asc_ev if asc_ev.orb <= dsc_ev.orb else dsc_ev
                    ev.axis = 'ASC_DSC'
                    ev.natal_target = 'ASC'
                    axis_events.append(ev)
                elif asc_ev:
                    asc_ev.axis = 'ASC_DSC'
                    asc_ev.natal_target = 'ASC'
                    axis_events.append(asc_ev)
                elif dsc_ev:
                    dsc_ev.axis = 'ASC_DSC'
                    dsc_ev.natal_target = 'ASC'
                    axis_events.append(dsc_ev)
            elif axis_name == 'MC_IC':
                mc_ev = pair.get('mc')
                ic_ev = pair.get('ic')
                if mc_ev and ic_ev:
                    ev = mc_ev if mc_ev.orb <= ic_ev.orb else ic_ev
                    ev.axis = 'MC_IC'
                    ev.natal_target = 'MC'
                    axis_events.append(ev)
                elif mc_ev:
                    mc_ev.axis = 'MC_IC'
                    mc_ev.natal_target = 'MC'
                    axis_events.append(mc_ev)
                elif ic_ev:
                    ic_ev.axis = 'MC_IC'
                    ic_ev.natal_target = 'MC'
                    axis_events.append(ic_ev)

        other_events = []
        for ev in events:
            if ev.natal_target in ['ASC', 'DSC', 'MC', 'IC']:
                continue
            other_events.append(ev)

        all_events = axis_events + other_events

        # 2. Дедупликация по уникальному ключу
        seen = set()
        unique = []
        for ev in all_events:
            key = ev.unique_key()
            if key not in seen:
                seen.add(key)
                unique.append(ev)

        return unique

    # ==================== ФИЛЬТРАЦИЯ ====================

    def _filter_events(self, events: List[TransitEvent]) -> List[TransitEvent]:
        # Пересчитываем score
        for ev in events:
            ev.score = self._calculate_score(
                ev.transit_body,
                {'name': ev.natal_target,
                 'weight': self.TARGET_WEIGHT.get(ev.natal_target, 5),
                 'is_angle': ev.natal_target in ['ASC', 'MC', 'DSC', 'IC']},
                ev.aspect,
                ev.orb,
                ev.applying,
                ev.peak_status,
                ev.active_today
            )

        # Категоризация (НЕ меняет aspect)
        for ev in events:
            if ev.peak_status == PeakStatus.TODAY and ev.active_today:
                ev.category = 'TODAY'
            elif ev.active_today and ev.peak_status in [PeakStatus.TOMORROW, PeakStatus.YESTERDAY]:
                ev.category = 'TRIGGER'
            else:
                ev.category = 'BACKGROUND'

        # Сортировка по score
        events.sort(key=lambda x: x.score, reverse=True)

        # Берём топ-5 TODAY, топ-3 TRIGGER
        top_today = [e for e in events if e.category == 'TODAY'][:5]
        top_trigger = [e for e in events if e.category == 'TRIGGER'][:3]

        result = top_today + top_trigger
        if len(result) < 3:
            background = [e for e in events if e.category == 'BACKGROUND']
            result.extend(background[:3 - len(result)])

        # Логируем финальные аспекты
        if self.debug:
            for ev in result:
                logger.info(
                    f"[ASPECT_FINAL] {ev.transit_body} → {ev.natal_target} | "
                    f"aspect={ev.aspect}, orb={ev.orb:.4f}, score={ev.score:.2f}"
                )

        return result

    # ==================== ОСНОВНОЙ МЕТОД ====================

    def build_context(self, period: str = 'today',
                      target_date: Optional[datetime] = None,
                      days_range: int = 5) -> str:
        if target_date is None:
            target_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        raw_events = self._calculate_all_events(target_date, days_range)
        self.all_raw_events = raw_events

        dedup_events = self._deduplicate_and_axes(raw_events)
        self.deduplicated_events = dedup_events

        final_events = self._filter_events(dedup_events)
        self.filtered_events = final_events

        # Проверка: aspect не должен меняться
        for ev in final_events:
            # Проверяем, что aspect соответствует расстоянию
            aspect_info = self.detect_aspect(ev.transit_longitude, ev.natal_target_longitude)
            if aspect_info['aspect'] != ev.aspect:
                logger.error(
                    f"❌ MISMATCH: {ev.transit_body} → {ev.natal_target} | "
                    f"stored={ev.aspect}, recalculated={aspect_info['aspect']}"
                )
                raise ValueError(f"Aspect mismatch for {ev.transit_body} → {ev.natal_target}")

        # Формирование текста
        lines = []
        lines.append(f"### Прогноз на день")
        lines.append(f"Дата: {target_date.strftime('%d.%m.%Y')}")
        lines.append("")

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

        if not final_events:
            lines.append("### Основные транзиты")
            lines.append("")
            lines.append("Нет значимых транзитов в указанный период.")
        else:
            lines.append("### Основные транзиты")
            lines.append("")
            for ev in final_events:
                planet = ev.transit_body
                target = ev.natal_target
                aspect = ev.aspect
                orb = ev.orb
                applying = ev.applying
                status = ev.peak_status
                transit_house = ev.transit_house
                natal_house = ev.natal_target_house

                aspect_name = NatalContextBuilder.ASPECT_MAP.get(aspect, aspect)
                phase_text = "сходящийся" if applying else "расходящийся"

                line = f"{planet} транзитный — {aspect_name} — натальное {target}"
                line += f", орб {orb:.2f}°, {phase_text}"
                lines.append(line)

                if transit_house:
                    lines.append(f"Транзитная планета активирует {transit_house} дом")
                if natal_house:
                    lines.append(f"Натальный {target} находится в {natal_house} доме")

                if status == PeakStatus.TODAY:
                    lines.append("Пик влияния: сегодня")
                elif status == PeakStatus.TOMORROW:
                    lines.append("Пик влияния: завтра")
                elif status == PeakStatus.YESTERDAY:
                    lines.append("Пик влияния: вчера")
                elif status == PeakStatus.FUTURE:
                    days = int(ev.days_to_exact) if ev.days_to_exact else 0
                    lines.append(f"Пик влияния: через {days} дн.")
                elif status == PeakStatus.PAST:
                    days = int(abs(ev.days_to_exact)) if ev.days_to_exact else 0
                    lines.append(f"Пик влияния: был {days} дн. назад")

                if ev.active_today:
                    lines.append("Активен сегодня")

                lines.append("")

        return "\n".join(lines)

    def get_stats(self) -> Dict:
        return {
            'total_raw': len(self.all_raw_events),
            'deduplicated': len(self.deduplicated_events),
            'filtered': len(self.filtered_events)
        }