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


class EventStatus(Enum):
    TODAY = "TODAY"
    ACTIVE = "ACTIVE"
    BACKGROUND = "BACKGROUND"
    IGNORE = "IGNORE"


class PriorityLabel(Enum):
    PRIMARY = "PRIMARY"
    STRONG = "STRONG"
    SUPPORTING = "SUPPORTING"
    BACKGROUND = "BACKGROUND"


@dataclass
class TransitEvent:
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
    exact_datetime: datetime
    days_to_peak: float
    phase: str                     # "applying", "exact", "separating"
    activity_status: EventStatus
    priority_label: PriorityLabel
    axis: Optional[str]            # "ASC_DSC" или "MC_IC"
    priority_score: float
    filter_reason: Optional[str] = None
    raw_data: Optional[Dict] = None

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

    # Активные орбы для разных планет (после пика)
    ACTIVE_ORB_THRESHOLDS = {
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

    DAYS_WINDOW_TODAY = 0.5
    DAYS_WINDOW_ACTIVE = 2.0   # для классификации ACTIVE (если пик не сегодня, но близко)

    # Веса для ранжирования
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

        # Pipeline stages
        self.raw_events: List[TransitEvent] = []
        self.validated_events: List[TransitEvent] = []
        self.dedup_events: List[TransitEvent] = []
        self.phase_events: List[TransitEvent] = []
        self.activity_events: List[TransitEvent] = []
        self.priority_events: List[TransitEvent] = []
        self.filtered_events: List[TransitEvent] = []
        self.ranked_events: List[TransitEvent] = []
        self.final_events: List[TransitEvent] = []
        self.background_events: List[TransitEvent] = []

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
        t_lon = transit_lon % 360
        n_lon = natal_lon % 360

        diff = abs(t_lon - n_lon) % 360
        if diff > 180:
            distance = 360 - diff
        else:
            distance = diff

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

    def _angular_distance(self, lon1: float, lon2: float) -> float:
        diff = abs(lon1 - lon2) % 360
        if diff > 180:
            diff = 360 - diff
        return diff

    # ==================== ЕДИНАЯ ФУНКЦИЯ ФАЗЫ И ПИКА ====================

    def _calculate_phase_and_peak(self, event: TransitEvent, forecast_date: datetime) -> Dict[str, Any]:
        """
        Определяет фазу (applying/exact/separating) и проверяет согласованность.
        Возвращает словарь с phase, peak_date, days_to_peak.
        """
        # Проверяем, что exact_datetime не None
        if event.exact_datetime is None:
            return {'phase': 'unknown', 'peak_date': None, 'days_to_peak': None}

        peak_date = event.exact_datetime
        days_to_peak = event.days_to_peak

        # Определяем фазу по изменению орба до/после точной даты
        # Для этого вычисляем ошибку аспекта за день до и после
        dt_before = peak_date - timedelta(days=1)
        dt_after = peak_date + timedelta(days=1)

        pos_before = self._get_transit_position(dt_before, event.transit_body)
        pos_after = self._get_transit_position(dt_after, event.transit_body)

        if pos_before is not None and pos_after is not None:
            error_before = self._aspect_error(pos_before, event.natal_target_longitude, event.exact_angle)
            error_after = self._aspect_error(pos_after, event.natal_target_longitude, event.exact_angle)
            if abs(error_before) > abs(error_after):
                phase = 'applying'
            elif abs(error_before) < abs(error_after):
                phase = 'separating'
            else:
                phase = 'exact'
        else:
            phase = 'unknown'

        # Проверка согласованности: если applying, то peak_date >= forecast_date
        if phase == 'applying' and peak_date < forecast_date:
            logger.error(
                f"❌ Несогласованность: {event.transit_body} → {event.natal_target} "
                f"applying, но peak_date ({peak_date}) < forecast_date ({forecast_date})"
            )
            # Исправляем: если peak_date уже прошёл, но мы посчитали applying – значит, ошиблись, меняем на separating
            phase = 'separating'
        elif phase == 'separating' and peak_date > forecast_date:
            logger.error(
                f"❌ Несогласованность: {event.transit_body} → {event.natal_target} "
                f"separating, но peak_date ({peak_date}) > forecast_date ({forecast_date})"
            )
            phase = 'applying'

        # Также проверяем, что days_to_peak соответствует
        if phase == 'applying' and days_to_peak < 0:
            logger.warning(
                f"⚠️ days_to_peak отрицательный для applying: {event.transit_body} → {event.natal_target}"
            )
            days_to_peak = abs(days_to_peak)
        elif phase == 'separating' and days_to_peak > 0:
            days_to_peak = -abs(days_to_peak)

        return {
            'phase': phase,
            'peak_date': peak_date,
            'days_to_peak': days_to_peak,
        }

    def _aspect_error(self, transit_lon: float, natal_lon: float, exact_angle: float) -> float:
        distance = self._angular_distance(transit_lon, natal_lon)
        return distance - exact_angle

    # ==================== КЛАССИФИКАЦИЯ АКТИВНОСТИ ====================

    def _classify_activity(self, event: TransitEvent) -> EventStatus:
        """Определяет активность транзита на основе орба и фазы."""
        # Если орб превышает максимальный, игнорируем
        max_orb = self.MAX_ORBS.get(event.aspect, 6.0)
        if event.orb > max_orb:
            return EventStatus.IGNORE

        # Активный порог для планеты
        threshold = self.ACTIVE_ORB_THRESHOLDS.get(event.transit_body, 2.5)

        # Если пик сегодня
        if abs(event.days_to_peak) <= self.DAYS_WINDOW_TODAY:
            return EventStatus.TODAY

        # Если орб мал, считаем активным
        if event.orb <= threshold:
            return EventStatus.ACTIVE

        # Если орб ещё не слишком большой, но больше порога – фоновый
        if event.orb <= max_orb:
            return EventStatus.BACKGROUND

        return EventStatus.IGNORE

    # ==================== ПРИОРИТЕТ ====================

    def _assign_priority(self, event: TransitEvent, forecast_date: datetime) -> PriorityLabel:
        """Определяет приоритет события."""
        # PRIMARY: точный сегодня, очень малый орб, соединение/оппозиция к ASC/MC, сильный транзит к личной планете
        if event.activity_status == EventStatus.TODAY:
            return PriorityLabel.PRIMARY
        if event.orb < 0.5:
            return PriorityLabel.PRIMARY
        if event.aspect in ('conjunction', 'opposition') and event.orb < 1.0 and event.natal_target in ('ASC', 'MC', 'DSC', 'IC'):
            return PriorityLabel.PRIMARY
        if event.transit_body in ('Sun', 'Moon', 'Mercury', 'Venus', 'Mars') and event.orb < 1.0 and event.natal_target in ('Sun', 'Moon', 'Mercury', 'Venus', 'Mars'):
            return PriorityLabel.PRIMARY

        # STRONG: активные медленные планеты с малым орбом, активные транзиты к углам
        if event.activity_status in (EventStatus.TODAY, EventStatus.ACTIVE):
            if event.transit_body in ('Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto'):
                return PriorityLabel.STRONG
            if event.natal_target in ('ASC', 'MC', 'DSC', 'IC'):
                return PriorityLabel.STRONG
            if event.orb < 1.5:
                return PriorityLabel.STRONG

        # SUPPORTING: остальные активные
        if event.activity_status in (EventStatus.TODAY, EventStatus.ACTIVE):
            return PriorityLabel.SUPPORTING

        # BACKGROUND
        return PriorityLabel.BACKGROUND

    # ==================== PIPELINE STAGES ====================

    def _calculate_raw_events(self, forecast_date: datetime, days_range: int = 5) -> List[TransitEvent]:
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

        events = []

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

                    aspect_info = self.detect_aspect(forecast_pos, t_lon)
                    if aspect_info['aspect'] is None:
                        continue

                    max_orb = self.MAX_ORBS.get(aspect_info['aspect'], 6.0)
                    if aspect_info['orb'] > max_orb:
                        continue

                    if self.debug:
                        logger.info(
                            f"[RAW] {planet} → {target['name']} | "
                            f"transit_lon={forecast_pos:.4f}, target_lon={t_lon:.4f}, "
                            f"distance={aspect_info['distance']:.4f}, "
                            f"aspect={aspect_info['aspect']}, orb={aspect_info['orb']:.4f}"
                        )

                    delta = exact_dt - forecast_date
                    days_to_peak = delta.total_seconds() / 3600 / 24

                    transit_house = self._get_transit_house(forecast_date, planet)

                    # Временный event без фазы, активности, приоритета
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
                        exact_datetime=exact_dt,
                        days_to_peak=days_to_peak,
                        phase='unknown',
                        activity_status=EventStatus.IGNORE,
                        priority_label=PriorityLabel.BACKGROUND,
                        axis=None,
                        priority_score=0.0,
                        raw_data=aspect_info
                    )
                    events.append(event)

        return events

    def _validate_events(self, events: List[TransitEvent]) -> List[TransitEvent]:
        validated = []
        for ev in events:
            aspect_info = self.detect_aspect(ev.transit_longitude, ev.natal_target_longitude)
            if aspect_info['aspect'] is None:
                continue
            if aspect_info['aspect'] != ev.aspect:
                logger.error(
                    f"❌ Валидация не пройдена: {ev.transit_body} → {ev.natal_target} | "
                    f"сохранён {ev.aspect}, вычислен {aspect_info['aspect']}"
                )
                continue
            if abs(aspect_info['orb'] - ev.orb) > 0.01:
                logger.warning(
                    f"⚠️ Орб не совпадает: {ev.transit_body} → {ev.natal_target} | "
                    f"сохранён {ev.orb:.4f}, вычислен {aspect_info['orb']:.4f}"
                )
                ev.orb = aspect_info['orb']
                ev.distance = aspect_info['distance']
                ev.exact_angle = aspect_info['exact_angle']
            validated.append(ev)
        return validated

    def _deduplicate_events(self, events: List[TransitEvent]) -> List[TransitEvent]:
        # 1. Обработка осей ASC/DSC и MC/IC
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
                    if self.debug:
                        logger.info(f"[DEDUP] Объединены ASC/DSC для {ev.transit_body} (аспект {ev.aspect})")
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
                    if self.debug:
                        logger.info(f"[DEDUP] Объединены MC/IC для {ev.transit_body} (аспект {ev.aspect})")
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

        # 2. Дедупликация по уникальному ключу (с учётом оси)
        seen = set()
        unique = []
        for ev in all_events:
            key = ev.unique_key()
            if key not in seen:
                seen.add(key)
                unique.append(ev)
            else:
                if self.debug:
                    logger.info(f"[DEDUP] Удалён дубликат: {key}")

        return unique

    def _apply_phase_and_peak(self, events: List[TransitEvent], forecast_date: datetime) -> List[TransitEvent]:
        for ev in events:
            phase_info = self._calculate_phase_and_peak(ev, forecast_date)
            ev.phase = phase_info['phase']
            ev.days_to_peak = phase_info['days_to_peak']  # обновляем, если нужно
            # Также обновляем exact_datetime, если оно изменилось?
            # В _calculate_phase_and_peak мы не меняем exact_datetime, только проверяем.
            # Поэтому оставляем как есть.
        return events

    def _classify_activity_and_priority(self, events: List[TransitEvent], forecast_date: datetime) -> List[TransitEvent]:
        for ev in events:
            ev.activity_status = self._classify_activity(ev)
            ev.priority_label = self._assign_priority(ev, forecast_date)
        return events

    def _filter_events(self, events: List[TransitEvent]) -> Tuple[List[TransitEvent], List[TransitEvent]]:
        foreground = []
        background = []
        for ev in events:
            if ev.activity_status == EventStatus.IGNORE:
                ev.filter_reason = f"IGNORE: orb {ev.orb:.2f} > max_orb {self.MAX_ORBS.get(ev.aspect, 6.0)}"
                background.append(ev)
            elif ev.activity_status == EventStatus.BACKGROUND:
                ev.filter_reason = f"BACKGROUND: orb {ev.orb:.2f} > active threshold {self.ACTIVE_ORB_THRESHOLDS.get(ev.transit_body, 2.5)}"
                background.append(ev)
            else:
                foreground.append(ev)
        return foreground, background

    def _rank_events(self, events: List[TransitEvent], forecast_date: datetime) -> List[TransitEvent]:
        for ev in events:
            # Пересчёт priority_score
            planet_weight = self.PLANET_WEIGHT.get(ev.transit_body, 5)
            aspect_weight = self.ASPECT_WEIGHT.get(ev.aspect, 0.7)
            target_weight = self.TARGET_WEIGHT.get(ev.natal_target, 5)
            base = (planet_weight * aspect_weight * target_weight) / 100

            orb_factor = max(0.1, 1 - ev.orb / 6.0)
            phase_factor = 1.2 if ev.phase == 'applying' else 0.9 if ev.phase == 'separating' else 1.0
            status_factor = {
                EventStatus.TODAY: 1.5,
                EventStatus.ACTIVE: 1.2,
                EventStatus.BACKGROUND: 0.5,
                EventStatus.IGNORE: 0.0
            }.get(ev.activity_status, 1.0)
            angle_factor = 1.4 if ev.natal_target in ['ASC', 'MC', 'DSC', 'IC'] else 1.0
            distance_factor = max(0.5, 1 - abs(ev.days_to_peak) / 5.0)

            ev.priority_score = base * orb_factor * phase_factor * status_factor * angle_factor * distance_factor

        events.sort(key=lambda x: x.priority_score, reverse=True)
        return events

    def _build_final(self, events: List[TransitEvent], max_events: int = 7) -> List[TransitEvent]:
        # Отдаём предпочтение PRIMARY, затем STRONG, затем SUPPORTING
        sorted_by_priority = sorted(events, key=lambda x: (
            0 if x.priority_label == PriorityLabel.PRIMARY else
            1 if x.priority_label == PriorityLabel.STRONG else
            2 if x.priority_label == PriorityLabel.SUPPORTING else 3,
            -x.priority_score
        ))
        return sorted_by_priority[:max_events]

    # ==================== ОСНОВНОЙ МЕТОД ====================

    def build_context(self, period: str = 'today',
                      target_date: Optional[datetime] = None,
                      days_range: int = 5) -> str:
        if target_date is None:
            target_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        # 1. RAW
        raw = self._calculate_raw_events(target_date, days_range)
        self.raw_events = raw
        logger.info(f"[PIPELINE] RAW: {len(raw)}")

        # 2. VALIDATE
        validated = self._validate_events(raw)
        self.validated_events = validated
        logger.info(f"[PIPELINE] VALIDATED: {len(validated)}")

        # 3. DEDUP
        dedup = self._deduplicate_events(validated)
        self.dedup_events = dedup
        logger.info(f"[PIPELINE] DEDUP: {len(dedup)}")

        # 4. PHASE_AND_PEAK
        phase_events = self._apply_phase_and_peak(dedup, target_date)
        self.phase_events = phase_events
        logger.info(f"[PIPELINE] PHASE applied")

        # 5. ACTIVITY
        activity_events = self._classify_activity_and_priority(phase_events, target_date)
        self.activity_events = activity_events
        logger.info(f"[PIPELINE] ACTIVITY classified")

        # 6. FILTER
        foreground, background = self._filter_events(activity_events)
        self.filtered_events = foreground
        self.background_events = background
        logger.info(f"[PIPELINE] FILTER: foreground={len(foreground)}, background={len(background)}")

        # 7. RANK
        ranked = self._rank_events(foreground, target_date)
        self.ranked_events = ranked
        logger.info(f"[PIPELINE] RANK: {len(ranked)}")

        # 8. FINAL
        final = self._build_final(ranked, max_events=7)
        self.final_events = final
        logger.info(f"[PIPELINE] FINAL: {len(final)}")

        # Логируем диагностику
        if self.debug:
            self._log_pipeline()

        return self._format_context(target_date)

    def _log_pipeline(self):
        logger.info(f"[PIPELINE] RAW: {len(self.raw_events)}")
        logger.info(f"[PIPELINE] VALIDATED: {len(self.validated_events)}")
        logger.info(f"[PIPELINE] DEDUP: {len(self.dedup_events)}")
        logger.info(f"[PIPELINE] PHASE applied")
        counts = {s: 0 for s in EventStatus}
        for ev in self.activity_events:
            counts[ev.activity_status] += 1
        logger.info(
            f"[ACTIVITY] TODAY={counts.get(EventStatus.TODAY, 0)}, "
            f"ACTIVE={counts.get(EventStatus.ACTIVE, 0)}, "
            f"BACKGROUND={counts.get(EventStatus.BACKGROUND, 0)}, "
            f"IGNORE={counts.get(EventStatus.IGNORE, 0)}"
        )
        pri_counts = {p: 0 for p in PriorityLabel}
        for ev in self.priority_events:
            pri_counts[ev.priority_label] += 1
        logger.info(
            f"[PRIORITY] PRIMARY={pri_counts.get(PriorityLabel.PRIMARY, 0)}, "
            f"STRONG={pri_counts.get(PriorityLabel.STRONG, 0)}, "
            f"SUPPORTING={pri_counts.get(PriorityLabel.SUPPORTING, 0)}, "
            f"BACKGROUND={pri_counts.get(PriorityLabel.BACKGROUND, 0)}"
        )
        logger.info(f"[FILTER] foreground={len(self.filtered_events)}, background={len(self.background_events)}")
        logger.info(f"[RANK] {len(self.ranked_events)}")
        logger.info(f"[FINAL] {len(self.final_events)}")

    def _format_context(self, target_date: datetime) -> str:
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

        if not self.final_events:
            lines.append("### Основные транзиты")
            lines.append("")
            lines.append("Нет значимых транзитов в указанный период.")
        else:
            lines.append("### Основные транзиты")
            lines.append("")
            for ev in self.final_events:
                planet = ev.transit_body
                target = ev.natal_target
                aspect = ev.aspect
                orb = ev.orb
                phase = ev.phase
                status = ev.activity_status
                priority = ev.priority_label.value
                transit_house = ev.transit_house
                natal_house = ev.natal_target_house
                days_to_peak = ev.days_to_peak

                aspect_name = NatalContextBuilder.ASPECT_MAP.get(aspect, aspect)
                phase_text = {
                    'applying': 'сходящийся',
                    'exact': 'точный',
                    'separating': 'расходящийся'
                }.get(phase, '')

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

                if status == EventStatus.TODAY:
                    lines.append("Пик влияния: сегодня")
                elif status == EventStatus.ACTIVE:
                    if abs(days_to_peak) < 1:
                        lines.append("Активен сегодня")
                    else:
                        days = int(abs(days_to_peak))
                        if days_to_peak > 0:
                            lines.append(f"Пик влияния: через {days} дн.")
                        else:
                            lines.append(f"Пик влияния: был {days} дн. назад")
                else:
                    lines.append("Фоновое влияние")

                lines.append("")

        return "\n".join(lines)

    # ==================== QA ОТЧЁТ ====================

    def get_qa_report(self) -> str:
        """Компактный QA-отчёт по 6 контрольным событиям."""
        target_events = [
            ('Sun', 'Mars'),
            ('Uranus', 'ASC'),
            ('Pluto', 'ASC'),
            ('Neptune', 'ASC'),
            ('Mars', 'MC'),
            ('Neptune', 'IC'),
        ]

        # Все события, прошедшие валидацию и дедупликацию
        all_events = self.ranked_events + self.background_events
        final_ids = {id(e) for e in self.final_events}

        # Находим контрольные события
        found = {}
        for ev in all_events:
            key = (ev.transit_body, ev.natal_target)
            if key in target_events and key not in found:
                found[key] = ev

        lines = []
        lines.append("=== QA ОТЧЁТ ===")
        lines.append("")
        lines.append("| planet → target | aspect | orb | phase | peak_date | days_to_peak | activity | priority | FINAL/BACKGROUND | причина |")
        lines.append("|-----------------|--------|-----|-------|-----------|--------------|----------|----------|------------------|---------|")

        for key in target_events:
            ev = found.get(key)
            if ev:
                peak_date = ev.exact_datetime.strftime('%d.%m.%Y') if ev.exact_datetime else 'N/A'
                activity = ev.activity_status.value if ev.activity_status else 'N/A'
                priority = ev.priority_label.value if ev.priority_label else 'N/A'
                is_final = "FINAL" if id(ev) in final_ids else "BACKGROUND"
                reason = ev.filter_reason if ev.filter_reason else ("Not in top 7 by priority" if not is_final else "")
                lines.append(
                    f"| {ev.transit_body} → {ev.natal_target} | {ev.aspect} | {ev.orb:.4f} | {ev.phase} | {peak_date} | {ev.days_to_peak:.2f} | {activity} | {priority} | {is_final} | {reason} |"
                )
            else:
                lines.append(f"| {key[0]} → {key[1]} | НЕ НАЙДЕНО | - | - | - | - | - | - | - | - |")

        lines.append("")

        # Статистика
        if self.activity_events:
            counts = {s: 0 for s in EventStatus}
            for ev in self.activity_events:
                counts[ev.activity_status] += 1
            lines.append(f"RAW total: {len(self.raw_events)}")
            lines.append(f"VALIDATED total: {len(self.validated_events)}")
            lines.append(f"DEDUP total: {len(self.dedup_events)}")
            lines.append(f"PHASE: applying={sum(1 for e in self.phase_events if e.phase=='applying')}, "
                         f"exact={sum(1 for e in self.phase_events if e.phase=='exact')}, "
                         f"separating={sum(1 for e in self.phase_events if e.phase=='separating')}")
            lines.append(f"ACTIVITY: TODAY={counts.get(EventStatus.TODAY, 0)}, "
                         f"ACTIVE={counts.get(EventStatus.ACTIVE, 0)}, "
                         f"BACKGROUND={counts.get(EventStatus.BACKGROUND, 0)}, "
                         f"IGNORE={counts.get(EventStatus.IGNORE, 0)}")
            pri_counts = {p: 0 for p in PriorityLabel}
            for ev in self.activity_events:
                pri_counts[ev.priority_label] += 1
            lines.append(f"PRIORITY: PRIMARY={pri_counts.get(PriorityLabel.PRIMARY, 0)}, "
                         f"STRONG={pri_counts.get(PriorityLabel.STRONG, 0)}, "
                         f"SUPPORTING={pri_counts.get(PriorityLabel.SUPPORTING, 0)}, "
                         f"BACKGROUND={pri_counts.get(PriorityLabel.BACKGROUND, 0)}")
            lines.append(f"FINAL: {len(self.final_events)}")
        else:
            lines.append("Нет данных для статистики.")

        lines.append("")
        lines.append("EXCLUDED:")
        excluded = []
        for ev in self.background_events:
            excluded.append(f"- {ev.transit_body} → {ev.natal_target}: {ev.filter_reason}")
        # Также события из foreground, но не попавшие в финал
        for ev in self.ranked_events:
            if id(ev) not in {id(e) for e in self.final_events}:
                excluded.append(f"- {ev.transit_body} → {ev.natal_target}: Not in top 7 by priority (score={ev.priority_score:.2f})")
        if not excluded:
            excluded.append("Нет исключённых событий.")
        lines.extend(excluded)

        return "\n".join(lines)

    def get_stats(self) -> Dict:
        return {
            'raw': len(self.raw_events),
            'validated': len(self.validated_events),
            'dedup': len(self.dedup_events),
            'classified': {
                'today': sum(1 for e in self.activity_events if e.activity_status == EventStatus.TODAY),
                'active': sum(1 for e in self.activity_events if e.activity_status == EventStatus.ACTIVE),
                'background': sum(1 for e in self.activity_events if e.activity_status == EventStatus.BACKGROUND),
                'ignore': sum(1 for e in self.activity_events if e.activity_status == EventStatus.IGNORE),
            },
            'priority': {
                'primary': sum(1 for e in self.activity_events if e.priority_label == PriorityLabel.PRIMARY),
                'strong': sum(1 for e in self.activity_events if e.priority_label == PriorityLabel.STRONG),
                'supporting': sum(1 for e in self.activity_events if e.priority_label == PriorityLabel.SUPPORTING),
                'background': sum(1 for e in self.activity_events if e.priority_label == PriorityLabel.BACKGROUND),
            },
            'filtered': len(self.filtered_events),
            'background_events': len(self.background_events),
            'final': len(self.final_events),
        }