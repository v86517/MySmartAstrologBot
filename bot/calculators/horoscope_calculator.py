import logging
import zoneinfo
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Tuple, Set
import math
from dataclasses import dataclass
from enum import Enum

from kerykeion import AstrologicalSubject

from bot.calculators.astrology_calculator import AstrologyCalculator
from bot.calculators.natal_context_builder import NatalContextBuilder

logger = logging.getLogger(__name__)


class EventStatus(Enum):
    TODAY = "TODAY"
    APPROACHING = "APPROACHING"
    SEPARATING = "SEPARATING"
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
    applying: bool
    exact_datetime: datetime
    days_to_peak: float
    status: EventStatus
    axis: Optional[str]
    priority_score: float
    filter_reason: Optional[str] = None
    raw_data: Optional[Dict] = None

    def unique_key(self) -> str:
        if self.axis:
            return f"{self.transit_body}:{self.axis}:{self.aspect}"
        return f"{self.transit_body}:{self.natal_target}:{self.aspect}"


class HoroscopeCalculator:
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

    DAY_ORBS = {
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
    DAYS_WINDOW_APPROACHING = 2.0
    DAYS_WINDOW_SEPARATING = 2.0

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

        self.raw_events: List[TransitEvent] = []
        self.validated_events: List[TransitEvent] = []
        self.dedup_events: List[TransitEvent] = []
        self.classified_events: List[TransitEvent] = []
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

    def _determine_applying(self, planet: str, natal_lon: float, aspect_angle: float,
                            exact_dt: datetime) -> bool:
        dt_before = exact_dt - timedelta(days=1)
        dt_after = exact_dt + timedelta(days=1)

        pos_before = self._get_transit_position(dt_before, planet)
        pos_after = self._get_transit_position(dt_after, planet)

        if pos_before is None or pos_after is None:
            return False

        def aspect_error(pos, lon, angle):
            dist = self._angular_distance(pos, lon)
            return dist - angle

        error_before = aspect_error(pos_before, natal_lon, aspect_angle)
        error_after = aspect_error(pos_after, natal_lon, aspect_angle)

        return abs(error_before) > abs(error_after)

    # ---- PIPELINE STAGES ----

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

                    applying = self._determine_applying(
                        planet, t_lon, aspect_angle, exact_dt
                    )

                    delta = exact_dt - forecast_date
                    days_to_peak = delta.total_seconds() / 3600 / 24

                    transit_house = self._get_transit_house(forecast_date, planet)

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
                        days_to_peak=days_to_peak,
                        status=EventStatus.BACKGROUND,
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

    def _classify_events(self, events: List[TransitEvent], forecast_date: datetime) -> List[TransitEvent]:
        for ev in events:
            days = ev.days_to_peak
            if abs(days) <= self.DAYS_WINDOW_TODAY:
                ev.status = EventStatus.TODAY
            elif days > 0 and days <= self.DAYS_WINDOW_APPROACHING:
                ev.status = EventStatus.APPROACHING
            elif days < 0 and abs(days) <= self.DAYS_WINDOW_SEPARATING:
                ev.status = EventStatus.SEPARATING
            else:
                ev.status = EventStatus.BACKGROUND

        if self.debug:
            counts = {s: 0 for s in EventStatus}
            for ev in events:
                counts[ev.status] += 1
            logger.info(
                f"[CLASSIFY] TODAY={counts[EventStatus.TODAY]}, "
                f"APPROACHING={counts[EventStatus.APPROACHING]}, "
                f"SEPARATING={counts[EventStatus.SEPARATING]}, "
                f"BACKGROUND={counts[EventStatus.BACKGROUND]}"
            )

        return events

    def _filter_events(self, events: List[TransitEvent]) -> Tuple[List[TransitEvent], List[TransitEvent]]:
        foreground = []
        background = []
        for ev in events:
            if ev.status == EventStatus.BACKGROUND:
                ev.filter_reason = "BACKGROUND status"
                background.append(ev)
            else:
                foreground.append(ev)
        return foreground, background

    def _rank_events(self, events: List[TransitEvent], forecast_date: datetime) -> List[TransitEvent]:
        for ev in events:
            planet_weight = self.PLANET_WEIGHT.get(ev.transit_body, 5)
            aspect_weight = self.ASPECT_WEIGHT.get(ev.aspect, 0.7)
            target_weight = self.TARGET_WEIGHT.get(ev.natal_target, 5)
            base = (planet_weight * aspect_weight * target_weight) / 100

            orb_factor = max(0.1, 1 - ev.orb / 6.0)
            phase_factor = 1.3 if ev.applying else 0.9
            status_factor = {
                EventStatus.TODAY: 1.5,
                EventStatus.APPROACHING: 1.2,
                EventStatus.SEPARATING: 1.1,
                EventStatus.BACKGROUND: 0.5
            }.get(ev.status, 1.0)
            angle_factor = 1.4 if ev.natal_target in ['ASC', 'MC', 'DSC', 'IC'] else 1.0
            distance_factor = max(0.5, 1 - abs(ev.days_to_peak) / 5.0)

            ev.priority_score = base * orb_factor * phase_factor * status_factor * angle_factor * distance_factor

        events.sort(key=lambda x: x.priority_score, reverse=True)
        return events

    def _build_final(self, events: List[TransitEvent], max_events: int = 5) -> List[TransitEvent]:
        return events[:max_events]

    # ---- MAIN METHOD ----

    def build_context(self, period: str = 'today',
                      target_date: Optional[datetime] = None,
                      days_range: int = 5) -> str:
        if target_date is None:
            target_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        self.raw_events = self._calculate_raw_events(target_date, days_range)
        self.validated_events = self._validate_events(self.raw_events)
        self.dedup_events = self._deduplicate_events(self.validated_events)
        self.classified_events = self._classify_events(self.dedup_events, target_date)
        self.filtered_events, self.background_events = self._filter_events(self.classified_events)
        self.ranked_events = self._rank_events(self.filtered_events, target_date)
        self.final_events = self._build_final(self.ranked_events, max_events=5)

        if self.debug:
            self._log_pipeline()

        return self._format_context(target_date)

    def _log_pipeline(self):
        logger.info(f"[PIPELINE] RAW: {len(self.raw_events)}")
        logger.info(f"[PIPELINE] VALIDATED: {len(self.validated_events)}")
        logger.info(f"[PIPELINE] DEDUP: {len(self.dedup_events)}")
        counts = {s: 0 for s in EventStatus}
        for ev in self.classified_events:
            counts[ev.status] += 1
        logger.info(
            f"[CLASSIFY] TODAY={counts[EventStatus.TODAY]}, "
            f"APPROACHING={counts[EventStatus.APPROACHING]}, "
            f"SEPARATING={counts[EventStatus.SEPARATING]}, "
            f"BACKGROUND={counts[EventStatus.BACKGROUND]}"
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
                applying = ev.applying
                status = ev.status
                transit_house = ev.transit_house
                natal_house = ev.natal_target_house
                days_to_peak = ev.days_to_peak

                aspect_name = NatalContextBuilder.ASPECT_MAP.get(aspect, aspect)
                phase_text = "сходящийся" if applying else "расходящийся"

                line = f"{planet} транзитный — {aspect_name} — натальное {target}"
                line += f", орб {orb:.2f}°, {phase_text}"
                lines.append(line)

                if transit_house:
                    lines.append(f"Транзитная планета активирует {transit_house} дом")
                if natal_house:
                    lines.append(f"Натальный {target} находится в {natal_house} доме")

                if status == EventStatus.TODAY:
                    lines.append("Пик влияния: сегодня")
                elif status == EventStatus.APPROACHING:
                    days = int(abs(days_to_peak))
                    lines.append(f"Пик влияния: через {days} дн.")
                elif status == EventStatus.SEPARATING:
                    days = int(abs(days_to_peak))
                    lines.append(f"Пик влияния: был {days} дн. назад")

                lines.append("")

        return "\n".join(lines)

    # ---- DIAGNOSTIC REPORT ----

    def get_diagnostic_report(self) -> str:
        lines = []
        lines.append("=== ДИАГНОСТИЧЕСКИЙ ОТЧЁТ ===")
        lines.append("")

        lines.append(f"RAW: {len(self.raw_events)}")
        for ev in self.raw_events:
            lines.append(self._format_event(ev))
        lines.append("")

        lines.append(f"VALIDATED: {len(self.validated_events)}")
        for ev in self.validated_events:
            lines.append(self._format_event(ev))
        lines.append("")

        lines.append(f"DEDUP: {len(self.dedup_events)}")
        for ev in self.dedup_events:
            lines.append(self._format_event(ev))
        lines.append("")

        lines.append(f"CLASSIFY:")
        for ev in self.classified_events:
            lines.append(self._format_event(ev))
        lines.append("")

        lines.append(f"FILTER: foreground={len(self.filtered_events)}, background={len(self.background_events)}")
        for ev in self.background_events:
            lines.append(f"  [REMOVED] {self._format_event(ev)}")
        lines.append("")

        lines.append(f"RANK: {len(self.ranked_events)}")
        for ev in self.ranked_events:
            lines.append(self._format_event(ev))
        lines.append("")

        lines.append(f"FINAL: {len(self.final_events)}")
        for ev in self.final_events:
            lines.append(self._format_event(ev))
        lines.append("")

        lines.append(f"BACKGROUND: {len(self.background_events)}")
        for ev in self.background_events:
            lines.append(self._format_event(ev))

        return "\n".join(lines)

    def _format_event(self, ev: TransitEvent) -> str:
        return (f"{ev.transit_body} → {ev.natal_target} | "
                f"aspect={ev.aspect}, orb={ev.orb:.4f}, "
                f"status={ev.status.value if ev.status else 'N/A'}, "
                f"days_to_peak={ev.days_to_peak:.2f}, "
                f"applying={ev.applying}, "
                f"score={ev.priority_score:.2f}" +
                (f", reason={ev.filter_reason}" if ev.filter_reason else ""))

    def get_stats(self) -> Dict:
        return {
            'raw': len(self.raw_events),
            'validated': len(self.validated_events),
            'dedup': len(self.dedup_events),
            'classified': {
                'today': sum(1 for e in self.classified_events if e.status == EventStatus.TODAY),
                'approaching': sum(1 for e in self.classified_events if e.status == EventStatus.APPROACHING),
                'separating': sum(1 for e in self.classified_events if e.status == EventStatus.SEPARATING),
                'background': sum(1 for e in self.classified_events if e.status == EventStatus.BACKGROUND),
            },
            'filtered': len(self.filtered_events),
            'background_events': len(self.background_events),
            'final': len(self.final_events),
        }