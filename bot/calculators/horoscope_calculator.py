import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Tuple, Callable

from kerykeion import AstrologicalSubject

from bot.calculators.astrology_calculator import AstrologyCalculator

logger = logging.getLogger(__name__)

# ============================================================================
# 1. КОНСТАНТЫ И ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================

SIGN_OFFSET = {
    'Aries': 0, 'Taurus': 30, 'Gemini': 60, 'Cancer': 90,
    'Leo': 120, 'Virgo': 150, 'Libra': 180, 'Scorpio': 210,
    'Sagittarius': 240, 'Capricorn': 270, 'Aquarius': 300, 'Pisces': 330,
    'Ari': 0, 'Tau': 30, 'Gem': 60, 'Can': 90,
    'Leo': 120, 'Vir': 150, 'Lib': 180, 'Sco': 210,
    'Sag': 240, 'Cap': 270, 'Aqu': 300, 'Pis': 330
}

ASPECT_ANGLES = {
    'conjunction': 0.0,
    'sextile': 60.0,
    'square': 90.0,
    'trine': 120.0,
    'opposition': 180.0,
}

MAX_ORB = {
    'conjunction': 5.0,
    'opposition': 5.0,
    'trine': 4.0,
    'square': 4.0,
    'sextile': 3.0,
}

ACTIVE_ORB = {
    'conjunction': 2.0,
    'opposition': 2.0,
    'trine': 1.5,
    'square': 1.5,
    'sextile': 1.0,
}

PLANET_ACTIVE_ORB = {
    'Sun': 1.5,
    'Moon': 1.5,
    'Uranus': 2.0,
    'Neptune': 2.0,
    'Pluto': 2.0,
}
ANGLE_ACTIVE_ORB = {
    'ASC': 1.5,
    'MC': 1.5,
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
    'Neptune': 5, 'Pluto': 5,
    'Chiron': 3, 'True_North_Lunar_Node': 3, 'True_South_Lunar_Node': 3
}

ASPECT_WEIGHT = {
    'conjunction': 1.0,
    'opposition': 0.95,
    'trine': 0.90,
    'square': 0.85,
    'sextile': 0.75
}

# Окна для TODAY (дни до/после exact)
TODAY_WINDOW = {
    'fast': 1.0,      # Sun, Moon, Mercury, Venus, Mars
    'medium': 2.0,    # Jupiter, Saturn
    'slow': 5.0,      # Uranus, Neptune, Pluto
}
APPROACHING_WINDOW = {
    'fast': 7.0,
    'medium': 30.0,
    'slow': 90.0,
}
RECENT_WINDOW = {
    'fast': 3.0,
    'medium': 14.0,
    'slow': 60.0,
}

EXACT_TOLERANCE = 0.01
EPSILON = 0.05  # для мягкого сравнения орбов с порогами

# ============================================================================
# 2. БАЗОВЫЕ ФУНКЦИИ (чистые)
# ============================================================================

def normalize_longitude(sign: str, degree: float) -> float:
    start = SIGN_OFFSET.get(sign)
    if start is None:
        raise ValueError(f"Unknown sign: {sign}")
    degree = degree % 30.0
    return (start + degree) % 360.0


def angular_distance(a: float, b: float) -> float:
    diff = abs(a - b) % 360.0
    return min(diff, 360.0 - diff)


def calculate_aspect(transit_lon: float, natal_lon: float) -> Optional[Dict]:
    dist = angular_distance(transit_lon, natal_lon)
    best_aspect = None
    best_orb = float('inf')
    best_angle = None
    for aspect, angle in ASPECT_ANGLES.items():
        orb = abs(dist - angle)
        if orb < best_orb:
            best_orb = orb
            best_aspect = aspect
            best_angle = angle
    if best_aspect is None or best_orb > MAX_ORB.get(best_aspect, 6.0):
        return None
    return {
        'aspect': best_aspect,
        'aspect_angle': best_angle,
        'orb': best_orb,
        'angular_distance': dist,
        'raw_delta': abs(transit_lon - natal_lon) % 360.0
    }


def resolve_axis(target_name: str, aspect: str, orb: float, natal_lon: float) -> Tuple[Optional[str], str, str, float, float]:
    """
    Возвращает (ось, primary_target, скорректированный_аспект, орб, скорректированная_натальная_долгота).
    Для DSC/IC долгота заменяется на противоположную (ASC/MC).
    """
    opposite = {
        'conjunction': 'opposition',
        'opposition': 'conjunction',
        'square': 'square',
        'trine': 'trine',
        'sextile': 'sextile'
    }
    if target_name in ('ASC', 'DSC'):
        axis = 'ASC_DSC'
        primary = 'ASC'
        new_lon = natal_lon
        if target_name == 'DSC':
            aspect = opposite.get(aspect, aspect)
            new_lon = (natal_lon - 180) % 360.0
        return axis, primary, aspect, orb, new_lon
    if target_name in ('MC', 'IC'):
        axis = 'MC_IC'
        primary = 'MC'
        new_lon = natal_lon
        if target_name == 'IC':
            aspect = opposite.get(aspect, aspect)
            new_lon = (natal_lon - 180) % 360.0
        return axis, primary, aspect, orb, new_lon
    return None, target_name, aspect, orb, natal_lon


def get_house_for_longitude(lon: float, house_cusps: List[Dict]) -> int:
    if not house_cusps:
        return 0
    sorted_cusps = sorted(house_cusps, key=lambda x: x['degree'])
    for i, cusp in enumerate(sorted_cusps):
        next_cusp = sorted_cusps[(i + 1) % 12]
        start = cusp['degree']
        end = next_cusp['degree']
        if end < start:
            if lon >= start or lon < end:
                return cusp['number']
        else:
            if start <= lon < end:
                return cusp['number']
    return 0


def find_all_exacts(
        transit_planet: str,
        natal_lon: float,
        aspect_angle: float,
        forecast_dt: datetime,
        get_position_func: Callable[[str, datetime], Optional[float]],
        search_days: int = 365,
        orb_threshold: float = 0.1
) -> List[datetime]:
    """
    Находит все точные моменты аспекта (орб <= orb_threshold) на интервале.
    """
    start = forecast_dt - timedelta(days=search_days)
    end = forecast_dt + timedelta(days=search_days)
    step = timedelta(days=1)

    points = []
    current = start
    while current <= end:
        lon = get_position_func(transit_planet, current)
        if lon is not None:
            dist = angular_distance(lon, natal_lon)
            orb = abs(dist - aspect_angle)
            points.append((current, orb))
        current += step

    if len(points) < 3:
        return []

    minima = []
    for i in range(1, len(points) - 1):
        if points[i][1] < points[i - 1][1] and points[i][1] < points[i + 1][1]:
            minima.append(points[i][0])

    if not minima:
        return []

    exacts = []
    for dt0 in minima:
        # Уточнение с шагом 1 час
        left = dt0 - timedelta(hours=12)
        right = dt0 + timedelta(hours=12)
        step_hour = timedelta(hours=1)
        best_dt = dt0
        best_orb = float('inf')
        current = left
        while current <= right:
            lon = get_position_func(transit_planet, current)
            if lon is not None:
                dist = angular_distance(lon, natal_lon)
                orb = abs(dist - aspect_angle)
                if orb < best_orb:
                    best_orb = orb
                    best_dt = current
            current += step_hour

        # Уточнение с шагом 1 минута
        left2 = best_dt - timedelta(minutes=30)
        right2 = best_dt + timedelta(minutes=30)
        step_min = timedelta(minutes=1)
        current = left2
        while current <= right2:
            lon = get_position_func(transit_planet, current)
            if lon is not None:
                dist = angular_distance(lon, natal_lon)
                orb = abs(dist - aspect_angle)
                if orb < best_orb:
                    best_orb = orb
                    best_dt = current
            current += step_min

        if best_orb <= orb_threshold:
            exacts.append(best_dt)

    exacts.sort()
    return exacts


def determine_phase_and_peak(
        transit_planet: str,
        natal_lon: float,
        aspect_angle: float,
        forecast_dt: datetime,
        get_position_func: Callable[[str, datetime], Optional[float]]
) -> Tuple[str, Optional[datetime], Optional[datetime], float]:
    """
    Возвращает (phase, previous_exact, next_exact, days_to_nearest).
    """
    exacts = find_all_exacts(transit_planet, natal_lon, aspect_angle, forecast_dt, get_position_func)
    if not exacts:
        return 'unknown', None, None, 0.0

    prev = None
    nxt = None
    for dt in exacts:
        if dt <= forecast_dt:
            prev = dt
        else:
            nxt = dt
            break

    if prev is None and nxt is None:
        return 'unknown', None, None, 0.0
    elif prev is None:
        nearest = nxt
        days_to = (nearest - forecast_dt).total_seconds() / 86400.0
        phase = 'applying'
    elif nxt is None:
        nearest = prev
        days_to = (nearest - forecast_dt).total_seconds() / 86400.0
        phase = 'separating'
    else:
        dist_prev = abs((prev - forecast_dt).total_seconds())
        dist_nxt = abs((nxt - forecast_dt).total_seconds())
        if dist_prev < dist_nxt:
            nearest = prev
            days_to = -dist_prev / 86400.0
            phase = 'separating'
        else:
            nearest = nxt
            days_to = dist_nxt / 86400.0
            phase = 'applying'

    if abs(days_to) <= EXACT_TOLERANCE:
        phase = 'exact'

    return phase, prev, nxt, days_to


def get_planet_category(planet: str) -> str:
    fast = {'Sun', 'Moon', 'Mercury', 'Venus', 'Mars'}
    medium = {'Jupiter', 'Saturn'}
    if planet in fast:
        return 'fast'
    elif planet in medium:
        return 'medium'
    else:
        return 'slow'


def classify_activity(phase: str, days_to_peak: float, planet: str) -> str:
    """
    Возвращает: TODAY, APPROACHING, RECENT, BACKGROUND.
    """
    if phase == 'unknown':
        return 'BACKGROUND'
    cat = get_planet_category(planet)
    today_window = TODAY_WINDOW[cat]
    if abs(days_to_peak) <= today_window:
        return 'TODAY'
    if phase == 'applying':
        approaching_window = APPROACHING_WINDOW[cat]
        if 0 < days_to_peak <= approaching_window:
            return 'APPROACHING'
    if phase == 'separating':
        recent_window = RECENT_WINDOW[cat]
        if -recent_window <= days_to_peak < 0:
            return 'RECENT'
    return 'BACKGROUND'


def compute_orb_strength(orb: float, aspect: str) -> float:
    max_orb = MAX_ORB.get(aspect, 6.0)
    if max_orb <= 0:
        return 0.0
    strength = 1.0 - (orb / max_orb)
    return max(0.0, min(1.0, strength))


def compute_timing_strength(activity: str) -> float:
    mapping = {
        'TODAY': 1.0,
        'APPROACHING': 0.7,
        'RECENT': 0.6,
        'BACKGROUND': 0.3,
    }
    return mapping.get(activity, 0.1)


# ============================================================================
# 3. DATACLASS TRANSIT EVENT (расширенный)
# ============================================================================

@dataclass
class TransitEvent:
    transit_body: str
    natal_target: str
    transit_longitude: float
    natal_target_longitude: float
    angular_distance: float
    aspect: str
    aspect_angle: float
    orb: float
    phase: str = 'unknown'
    previous_exact: Optional[datetime] = None
    next_exact: Optional[datetime] = None
    nearest_exact: Optional[datetime] = None
    days_to_nearest: float = 0.0
    activity: str = 'BACKGROUND'
    orb_strength: float = 0.0
    timing_strength: float = 0.0
    priority_score: float = 0.0
    transit_house: int = 0
    natal_target_house: int = 0
    axis: Optional[str] = None
    is_retrograde: bool = False
    transit_speed: float = 0.0
    filter_reason: str = ''

    @property
    def unique_key(self) -> str:
        if self.axis:
            return f"{self.transit_body}:{self.axis}:{self.aspect}"
        return f"{self.transit_body}:{self.natal_target}:{self.aspect}"


# ============================================================================
# 4. ОСНОВНОЙ КЛАСС HoroscopeCalculator
# ============================================================================

class HoroscopeCalculator:
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

        self._transit_cache = {}

        self.raw_events: List[TransitEvent] = []
        self.phase_events: List[TransitEvent] = []
        self.house_events: List[TransitEvent] = []
        self.dedup_events: List[TransitEvent] = []
        self.activity_events: List[TransitEvent] = []
        self.filtered_events: List[TransitEvent] = []
        self.ranked_events: List[TransitEvent] = []
        self.final_events: List[TransitEvent] = []
        self.background_events: List[TransitEvent] = []
        self.all_relevant: List[TransitEvent] = []

        self.natal_targets = self._build_natal_targets()

    # ------------------- ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ -------------------

    def _build_natal_targets(self) -> List[Dict]:
        targets = []
        main_names = {'Sun','Moon','Mercury','Venus','Mars',
                      'Jupiter','Saturn','Uranus','Neptune','Pluto'}
        for p in self.natal_planets:
            name = p['name']
            if name in main_names:
                lon = normalize_longitude(p['sign'], p['degree'])
                targets.append({
                    'name': name,
                    'longitude': lon,
                    'house': p.get('house', 0),
                    'is_angle': False,
                    'weight': TARGET_WEIGHT.get(name, 5)
                })
        for angle in ['ASC','MC','DSC','IC']:
            if angle in self.natal_angles and self.natal_angles[angle] is not None:
                a = self.natal_angles[angle]
                lon = a.get('abs_pos') or a.get('position')
                if lon is None:
                    lon = normalize_longitude(a['sign'], a['position'])
                lon = lon % 360.0
                targets.append({
                    'name': angle,
                    'longitude': lon,
                    'house': None,
                    'is_angle': True,
                    'weight': TARGET_WEIGHT.get(angle, 9)
                })
        extra_names = ['True_North_Lunar_Node','True_South_Lunar_Node','Chiron','True_Lilith']
        for p in self.natal_planets:
            if p['name'] in extra_names:
                lon = normalize_longitude(p['sign'], p['degree'])
                targets.append({
                    'name': p['name'],
                    'longitude': lon,
                    'house': p.get('house', 0),
                    'is_angle': False,
                    'weight': TARGET_WEIGHT.get(p['name'], 3)
                })
        return targets

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
        for planet in ['Sun','Moon','Mercury','Venus','Mars',
                       'Jupiter','Saturn','Uranus','Neptune','Pluto']:
            p_key = planet.lower()
            if p_key in data:
                obj = data[p_key]
                if isinstance(obj, dict):
                    sign = obj.get('sign', '')
                    degree = obj.get('position', 0.0)
                    if sign:
                        positions[planet] = normalize_longitude(sign, degree)
                else:
                    if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                        sign = getattr(obj, 'sign', '')
                        degree = getattr(obj, 'position', 0.0)
                        if sign:
                            positions[planet] = normalize_longitude(sign, degree)
        self._transit_cache[key] = positions
        return positions

    def _get_transit_position(self, planet: str, date: datetime) -> Optional[float]:
        positions = self._get_transit_positions(date)
        return positions.get(planet)

    def _get_transit_speed(self, planet: str, date: datetime) -> float:
        subject = self._get_transit_subject(date)
        model = subject.model() if callable(subject.model) else subject.model
        data = model.dict() if hasattr(model, 'dict') else model.__dict__
        p_key = planet.lower()
        if p_key in data:
            obj = data[p_key]
            if isinstance(obj, dict):
                return obj.get('speed', 0.0)
            else:
                return getattr(obj, 'speed', 0.0)
        return 0.0

    def _is_retrograde(self, planet: str, date: datetime) -> bool:
        subject = self._get_transit_subject(date)
        model = subject.model() if callable(subject.model) else subject.model
        data = model.dict() if hasattr(model, 'dict') else model.__dict__
        p_key = planet.lower()
        if p_key in data:
            obj = data[p_key]
            if isinstance(obj, dict):
                return obj.get('retrograde', False)
            else:
                return getattr(obj, 'retrograde', False)
        return False

    # ------------------- ОСНОВНЫЕ ЭТАПЫ PIPELINE -------------------

    def _calculate_raw_events(self, forecast_date: datetime) -> List[TransitEvent]:
        raw = []
        transit_planets = ['Sun','Moon','Mercury','Venus','Mars',
                           'Jupiter','Saturn','Uranus','Neptune','Pluto']
        for planet in transit_planets:
            forecast_lon = self._get_transit_position(planet, forecast_date)
            if forecast_lon is None:
                continue
            speed = self._get_transit_speed(planet, forecast_date)
            retro = self._is_retrograde(planet, forecast_date)

            for target in self.natal_targets:
                natal_lon = target['longitude']
                aspect_res = calculate_aspect(forecast_lon, natal_lon)
                if aspect_res is None:
                    continue

                axis, primary, asp_corrected, orb, new_natal_lon = resolve_axis(
                    target['name'], aspect_res['aspect'], aspect_res['orb'], natal_lon
                )
                if axis is not None:
                    target_name = primary
                    aspect = asp_corrected
                    orb_value = orb
                    aspect_angle = ASPECT_ANGLES[aspect]
                    natal_lon_used = new_natal_lon
                    dist = angular_distance(forecast_lon, natal_lon_used)
                    raw_delta = abs(forecast_lon - natal_lon_used) % 360.0
                else:
                    target_name = target['name']
                    aspect = aspect_res['aspect']
                    orb_value = aspect_res['orb']
                    aspect_angle = aspect_res['aspect_angle']
                    natal_lon_used = natal_lon
                    dist = aspect_res['angular_distance']
                    raw_delta = aspect_res['raw_delta']

                event = TransitEvent(
                    transit_body=planet,
                    natal_target=target_name,
                    transit_longitude=forecast_lon,
                    natal_target_longitude=natal_lon_used,
                    angular_distance=dist,
                    aspect=aspect,
                    aspect_angle=aspect_angle,
                    orb=orb_value,
                    transit_speed=speed,
                    is_retrograde=retro,
                    axis=axis,
                    transit_house=0,
                    natal_target_house=target.get('house', 0),
                )
                raw.append(event)
        logger.info(f"[RAW] {len(raw)} events")
        self.raw_events = raw
        return raw

    def _apply_phase_and_peak(self, events: List[TransitEvent], forecast_date: datetime) -> List[TransitEvent]:
        for ev in events:
            # Используем 365 дней для всех планет, чтобы гарантировать нахождение exact
            phase, prev, nxt, days_to = determine_phase_and_peak(
                ev.transit_body,
                ev.natal_target_longitude,
                ev.aspect_angle,
                forecast_date,
                self._get_transit_position
            )
            ev.phase = phase
            ev.previous_exact = prev
            ev.next_exact = nxt
            if prev is not None and nxt is not None:
                if abs((prev - forecast_date).total_seconds()) < abs((nxt - forecast_date).total_seconds()):
                    ev.nearest_exact = prev
                else:
                    ev.nearest_exact = nxt
            elif prev is not None:
                ev.nearest_exact = prev
            elif nxt is not None:
                ev.nearest_exact = nxt
            else:
                ev.nearest_exact = None
            ev.days_to_nearest = days_to

            if phase == 'unknown':
                logger.warning(f"Unknown phase for {ev.transit_body}->{ev.natal_target}")
        self.phase_events = events
        return events

    def _calculate_houses(self, events: List[TransitEvent]) -> List[TransitEvent]:
        house_cusps = []
        for h in self.natal_houses:
            num = h.get('number', 0)
            deg = h.get('degree', 0.0)
            if num and deg:
                house_cusps.append({'number': num, 'degree': deg})
        for ev in events:
            ev.transit_house = get_house_for_longitude(ev.transit_longitude, house_cusps)
            if ev.natal_target_house is None:
                ev.natal_target_house = 0
        self.house_events = events
        return events

    def _deduplicate_events(self, events: List[TransitEvent]) -> List[TransitEvent]:
        groups = {}
        for ev in events:
            key = ev.unique_key
            if key not in groups or ev.orb < groups[key].orb:
                groups[key] = ev
        deduped = list(groups.values())
        logger.info(f"[DEDUP] {len(deduped)} from {len(events)}")
        self.dedup_events = deduped
        return deduped

    def _classify_activity_and_priority(self, events: List[TransitEvent], forecast_date: datetime) -> List[TransitEvent]:
        for ev in events:
            # Проверяем максимальный орб
            max_orb = MAX_ORB.get(ev.aspect, 6.0)
            if ev.orb > max_orb:
                ev.activity = 'BACKGROUND'
                ev.filter_reason = f'orb {ev.orb:.2f} > max {max_orb}'
                ev.orb_strength = 0.0
                ev.timing_strength = 0.0
                ev.priority_score = 0.0
                continue

            # Активность
            if ev.phase == 'unknown':
                ev.activity = 'BACKGROUND'
                ev.filter_reason = 'phase unknown'
                ev.orb_strength = 0.0
                ev.timing_strength = 0.0
                ev.priority_score = 0.0
                continue

            # Проверяем активный орб (с EPSILON)
            active_orb = ACTIVE_ORB.get(ev.aspect, 2.0)
            if ev.transit_body in PLANET_ACTIVE_ORB:
                active_orb = min(active_orb, PLANET_ACTIVE_ORB[ev.transit_body])
            if ev.natal_target in ANGLE_ACTIVE_ORB:
                active_orb = min(active_orb, ANGLE_ACTIVE_ORB[ev.natal_target])

            # Если орб сильно превышает активный, помечаем как BACKGROUND
            if ev.orb > active_orb + EPSILON:
                ev.activity = 'BACKGROUND'
                ev.filter_reason = f'orb {ev.orb:.2f} > active {active_orb}'
            else:
                # Определяем activity по дням до nearest exact
                ev.activity = classify_activity(ev.phase, ev.days_to_nearest, ev.transit_body)

            # Силы
            ev.orb_strength = compute_orb_strength(ev.orb, ev.aspect)
            ev.timing_strength = compute_timing_strength(ev.activity)

            # Приоритет
            planet_w = PLANET_WEIGHT.get(ev.transit_body, 5)
            target_w = TARGET_WEIGHT.get(ev.natal_target, 5)
            aspect_w = ASPECT_WEIGHT.get(ev.aspect, 0.7)
            # Если activity BACKGROUND, снижаем timing strength
            timing = ev.timing_strength
            if ev.activity == 'BACKGROUND':
                timing *= 0.5  # дополнительный штраф

            ev.priority_score = (
                ev.orb_strength * timing * planet_w * target_w * aspect_w
            )

        self.activity_events = events
        return events

    def _filter_events(self, events: List[TransitEvent]) -> Tuple[List[TransitEvent], List[TransitEvent]]:
        foreground = []
        background = []
        for ev in events:
            if ev.activity in ('BACKGROUND', 'IGNORE') or ev.phase == 'unknown' or ev.orb_strength == 0:
                background.append(ev)
            else:
                foreground.append(ev)
        logger.info(f"[FILTER] foreground={len(foreground)}, background={len(background)}")
        self.filtered_events = foreground
        self.background_events = background
        return foreground, background

    def _rank_events(self, events: List[TransitEvent]) -> List[TransitEvent]:
        sorted_events = sorted(events, key=lambda x: x.priority_score, reverse=True)
        self.ranked_events = sorted_events
        return sorted_events

    def _build_final(self, events: List[TransitEvent], max_display: int = 7) -> List[TransitEvent]:
        # Группируем по activity
        today = [e for e in events if e.activity == 'TODAY']
        approaching = [e for e in events if e.activity == 'APPROACHING']
        recent = [e for e in events if e.activity == 'RECENT']
        background = [e for e in events if e.activity == 'BACKGROUND']

        # Сортируем внутри групп по priority_score
        today.sort(key=lambda x: x.priority_score, reverse=True)
        approaching.sort(key=lambda x: x.priority_score, reverse=True)
        recent.sort(key=lambda x: x.priority_score, reverse=True)
        background.sort(key=lambda x: x.priority_score, reverse=True)

        final = []
        # 1. TODAY (максимум 3)
        final.extend(today[:3])
        # 2. APPROACHING (добиваем до 7)
        if len(final) < max_display:
            needed = max_display - len(final)
            final.extend(approaching[:needed])
        # 3. RECENT (если ещё есть место)
        if len(final) < max_display:
            needed = max_display - len(final)
            final.extend(recent[:needed])
        # 4. BACKGROUND (только если мало событий, например, меньше 3)
        if len(final) < 3:
            needed = 3 - len(final)
            final.extend(background[:needed])

        # Убираем дубли по уникальному ключу (на всякий случай)
        seen = set()
        unique_final = []
        for ev in final:
            key = ev.unique_key
            if key not in seen:
                seen.add(key)
                unique_final.append(ev)

        self.final_events = unique_final[:max_display]
        self.all_relevant = events
        logger.info(f"[FINAL] {len(self.final_events)} events")
        return self.final_events

    # ------------------- ПУБЛИЧНЫЙ МЕТОД -------------------

    def build_context(self, period: str = 'today',
                      target_date: Optional[datetime] = None,
                      days_range: int = 5) -> str:
        if target_date is None:
            target_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        raw = self._calculate_raw_events(target_date)
        phase_events = self._apply_phase_and_peak(raw, target_date)
        house_events = self._calculate_houses(phase_events)
        dedup = self._deduplicate_events(house_events)
        activity = self._classify_activity_and_priority(dedup, target_date)
        foreground, background = self._filter_events(activity)
        ranked = self._rank_events(foreground)
        final = self._build_final(ranked, max_display=7)

        self.background_events = background + [e for e in ranked if e not in final]
        self._log_debug_events(final)
        return self._format_context(target_date)

    def _log_debug_events(self, events: List[TransitEvent]):
        for ev in events:
            prev_str = ev.previous_exact.strftime('%Y-%m-%d') if ev.previous_exact else 'N/A'
            next_str = ev.next_exact.strftime('%Y-%m-%d') if ev.next_exact else 'N/A'
            nearest_str = ev.nearest_exact.strftime('%Y-%m-%d') if ev.nearest_exact else 'N/A'
            logger.info(
                f"[DEBUG] {ev.transit_body}->{ev.natal_target} | "
                f"lon={ev.transit_longitude:.2f} target={ev.natal_target_longitude:.2f} "
                f"dist={ev.angular_distance:.2f} aspect={ev.aspect} orb={ev.orb:.4f} "
                f"phase={ev.phase} prev={prev_str} next={next_str} nearest={nearest_str} "
                f"days={ev.days_to_nearest:.2f} activity={ev.activity} score={ev.priority_score:.3f}"
            )

    def _format_context(self, target_date: datetime) -> str:
        lines = []
        lines.append(f"### Прогноз на день")
        lines.append(f"Дата: {target_date.strftime('%d.%m.%Y')}")
        lines.append("")
        lines.append("### Натальные данные")
        lines.append("")
        for angle in ['ASC','MC','DSC','IC']:
            if angle in self.natal_angles and self.natal_angles[angle] is not None:
                a = self.natal_angles[angle]
                sign = a.get('sign', '')
                pos = a.get('position', 0.0)
                lines.append(f"{angle}: {sign} {pos:.2f}°")
        lines.append("")
        main_names = ['Sun','Moon','Mercury','Venus','Mars',
                      'Jupiter','Saturn','Uranus','Neptune','Pluto']
        for p in self.natal_planets:
            if p['name'] in main_names:
                sign = p['sign']; deg = p['degree']; house = p.get('house',0); retro = p.get('retrograde',False)
                line = f"{p['name']}: {sign} {deg:.2f}°, {house} дом"
                if retro: line += ", ретроградный"
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
                aspect_names = {'conjunction':'соединение','opposition':'оппозиция',
                                'trine':'трин','square':'квадрат','sextile':'секстиль'}
                phase_text = {'applying':'сходящийся','exact':'точный','separating':'расходящийся'}.get(ev.phase,'')
                aspect_ru = aspect_names.get(ev.aspect, ev.aspect)
                line = f"{ev.transit_body} транзитный — {aspect_ru} — натальное {ev.natal_target}"
                if phase_text:
                    line += f", орб {ev.orb:.2f}°, {phase_text}"
                else:
                    line += f", орб {ev.orb:.2f}°"
                lines.append(line)
                if ev.transit_house:
                    lines.append(f"Транзитная планета активирует {ev.transit_house} дом")
                if ev.natal_target_house:
                    lines.append(f"Натальный {ev.natal_target} находится в {ev.natal_target_house} доме")
                # Описание активности
                if ev.activity == 'TODAY':
                    if abs(ev.days_to_nearest) <= 0.01:
                        lines.append("Пик влияния: сегодня (точный аспект)")
                    else:
                        days = int(abs(ev.days_to_nearest))
                        if ev.days_to_nearest > 0:
                            lines.append(f"Пик влияния: через {days} дн.")
                        else:
                            lines.append(f"Пик влияния: был {days} дн. назад")
                elif ev.activity == 'APPROACHING':
                    days = int(ev.days_to_nearest)
                    lines.append(f"Пик влияния: через {days} дн.")
                elif ev.activity == 'RECENT':
                    days = int(abs(ev.days_to_nearest))
                    lines.append(f"Пик влияния: был {days} дн. назад")
                else:
                    lines.append("Фоновое влияние")
                lines.append("")
        return "\n".join(lines)

    # ------------------- QA ОТЧЁТ -------------------

    def get_qa_report(self) -> str:
        target_pairs = [
            ('Sun','Mars'), ('Uranus','ASC'), ('Pluto','ASC'),
            ('Neptune','ASC'), ('Mars','MC'), ('Neptune','MC')
        ]
        all_events = self.ranked_events + self.background_events
        final_ids = {id(e) for e in self.final_events}
        found = {}
        for ev in all_events:
            key = (ev.transit_body, ev.natal_target)
            if key in target_pairs and key not in found:
                found[key] = ev

        lines = []
        lines.append("=== QA ОТЧЁТ ===")
        lines.append("")
        lines.append("| planet → target | transit_lon | target_lon | angular_dist | aspect | orb | phase | prev_exact | next_exact | nearest | days_to | activity | priority | FINAL |")
        lines.append("|-----------------|-------------|------------|--------------|--------|-----|-------|------------|------------|---------|---------|----------|----------|-------|")
        for key in target_pairs:
            ev = found.get(key)
            if ev:
                prev = ev.previous_exact.strftime('%Y-%m-%d') if ev.previous_exact else 'N/A'
                nxt = ev.next_exact.strftime('%Y-%m-%d') if ev.next_exact else 'N/A'
                near = ev.nearest_exact.strftime('%Y-%m-%d') if ev.nearest_exact else 'N/A'
                is_final = "FINAL" if id(ev) in final_ids else "BACKGROUND"
                lines.append(
                    f"| {ev.transit_body} → {ev.natal_target} | {ev.transit_longitude:.2f} | {ev.natal_target_longitude:.2f} | {ev.angular_distance:.2f} | {ev.aspect} | {ev.orb:.4f} | {ev.phase} | {prev} | {nxt} | {near} | {ev.days_to_nearest:.2f} | {ev.activity} | {ev.priority_score:.3f} | {is_final} |"
                )
            else:
                lines.append(f"| {key[0]} → {key[1]} | - | - | - | - | - | - | - | - | - | - | - | - | НЕ НАЙДЕНО |")
        lines.append("")
        lines.append(f"RAW: {len(self.raw_events)}")
        lines.append(f"DEDUP: {len(self.dedup_events)}")
        lines.append(f"ACTIVITY: TODAY={sum(1 for e in self.activity_events if e.activity=='TODAY')}, APPROACHING={sum(1 for e in self.activity_events if e.activity=='APPROACHING')}, RECENT={sum(1 for e in self.activity_events if e.activity=='RECENT')}, BACKGROUND={sum(1 for e in self.activity_events if e.activity=='BACKGROUND')}")
        lines.append(f"ALL_RELEVANT: {len(self.all_relevant)}")
        lines.append(f"FINAL: {len(self.final_events)}")
        return "\n".join(lines)

    def get_stats(self) -> Dict:
        return {
            'raw': len(self.raw_events),
            'dedup': len(self.dedup_events),
            'activity': {
                'today': sum(1 for e in self.activity_events if e.activity == 'TODAY'),
                'approaching': sum(1 for e in self.activity_events if e.activity == 'APPROACHING'),
                'recent': sum(1 for e in self.activity_events if e.activity == 'RECENT'),
                'background': sum(1 for e in self.activity_events if e.activity == 'BACKGROUND'),
            },
            'all_relevant': len(self.all_relevant),
            'final': len(self.final_events),
        }