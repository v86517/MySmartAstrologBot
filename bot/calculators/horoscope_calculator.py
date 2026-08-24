import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Tuple, Callable
import math

from kerykeion import AstrologicalSubject

from bot.calculators.astrology_calculator import AstrologyCalculator

logger = logging.getLogger(__name__)

# ============================================================================
# 1. КОНСТАНТЫ И БАЗОВЫЕ ФУНКЦИИ
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

MAX_ORBS = {
    'conjunction': 8.0,
    'opposition': 8.0,
    'trine': 6.0,
    'square': 6.0,
    'sextile': 5.0,
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
DAYS_WINDOW_ACTIVE = 2.0
EXACT_TOLERANCE = 0.01  # градусы, при которых считаем exact
SEARCH_DAYS = 30        # диапазон поиска peak ±30 дней

# ============================================================================
# 2. БАЗОВЫЕ ВЫЧИСЛИТЕЛЬНЫЕ ФУНКЦИИ (без состояния)
# ============================================================================

def normalize_longitude(sign: str, degree: float) -> float:
    """Преобразует знак и градус в абсолютную долготу 0..360."""
    start = SIGN_OFFSET.get(sign)
    if start is None:
        raise ValueError(f"Unknown sign: {sign}")
    degree = degree % 30.0
    return (start + degree) % 360.0


def calculate_aspect(transit_lon: float, natal_lon: float, orb_limit: float = 8.0) -> Optional['AspectResult']:
    """
    Единственная функция определения аспекта.
    Возвращает один аспект с минимальным орбом (winner-takes-all).
    """
    raw_delta = abs(transit_lon - natal_lon) % 360.0
    angular_distance = min(raw_delta, 360.0 - raw_delta)

    candidates = []
    for aspect, angle in ASPECT_ANGLES.items():
        orb = abs(angular_distance - angle)
        if orb <= orb_limit:
            candidates.append((aspect, angle, orb))

    if not candidates:
        return None

    # Выбираем аспект с минимальным орбом
    best = min(candidates, key=lambda x: x[2])
    return AspectResult(
        aspect=best[0],
        aspect_angle=best[1],
        orb=best[2],
        angular_distance=angular_distance,
        raw_delta=raw_delta
    )


@dataclass(frozen=True)
class AspectResult:
    aspect: str
    aspect_angle: float
    orb: float
    angular_distance: float
    raw_delta: float


def resolve_axis_target(target_name: str, aspect: str, orb: float) -> Tuple[Optional[str], str, str, float]:
    """
    Для угловых целей (ASC/DSC, MC/IC) возвращает:
    - ось (например, 'ASC_DSC')
    - первичную цель ('ASC' или 'MC')
    - скорректированный аспект (если цель была DSC/IC, меняем на противоположный)
    - тот же орб
    Для обычных целей возвращает (None, target_name, aspect, orb).
    """
    opposite_map = {
        'conjunction': 'opposition',
        'opposition': 'conjunction',
        'square': 'square',
        'trine': 'trine',
        'sextile': 'sextile'
    }
    if target_name in ('ASC', 'DSC'):
        axis = 'ASC_DSC'
        primary = 'ASC'
        if target_name == 'DSC':
            aspect = opposite_map.get(aspect, aspect)
        return axis, primary, aspect, orb
    elif target_name in ('MC', 'IC'):
        axis = 'MC_IC'
        primary = 'MC'
        if target_name == 'IC':
            aspect = opposite_map.get(aspect, aspect)
        return axis, primary, aspect, orb
    else:
        return None, target_name, aspect, orb


def get_house_for_longitude(lon: float, house_cusps: List[Dict]) -> int:
    """Определяет номер дома для долготы по натальным куспидам."""
    if not house_cusps:
        return 0
    sorted_cusps = sorted(house_cusps, key=lambda x: x['degree'])
    for i, cusp in enumerate(sorted_cusps):
        next_cusp = sorted_cusps[(i + 1) % 12]
        start = cusp['degree']
        end = next_cusp['degree']
        if end < start:  # переход через 0°
            if lon >= start or lon < end:
                return cusp['number']
        else:
            if start <= lon < end:
                return cusp['number']
    return 0


def find_exact_datetime(
    transit_planet: str,
    natal_lon: float,
    aspect_angle: float,
    start_dt: datetime,
    end_dt: datetime,
    get_position_func: Callable[[str, datetime], Optional[float]]
) -> Optional[datetime]:
    """
    Численный поиск момента минимального орба (точный аспект).
    Возвращает datetime точного аспекта или None.
    """
    if start_dt >= end_dt:
        return None

    # Грубый поиск с шагом 6 часов
    step = timedelta(hours=6)
    best_dt = start_dt
    best_orb = float('inf')

    current = start_dt
    while current <= end_dt:
        lon = get_position_func(transit_planet, current)
        if lon is not None:
            raw = abs(lon - natal_lon) % 360.0
            dist = min(raw, 360.0 - raw)
            orb = abs(dist - aspect_angle)
            if orb < best_orb:
                best_orb = orb
                best_dt = current
        current += step

    # Уточнение: шаг 30 минут, затем 1 минута
    for fine_step in [timedelta(minutes=30), timedelta(minutes=1)]:
        left = best_dt - 3 * fine_step
        right = best_dt + 3 * fine_step
        current = left
        while current <= right:
            lon = get_position_func(transit_planet, current)
            if lon is not None:
                raw = abs(lon - natal_lon) % 360.0
                dist = min(raw, 360.0 - raw)
                orb = abs(dist - aspect_angle)
                if orb < best_orb:
                    best_orb = orb
                    best_dt = current
            current += fine_step

    # Проверяем, что найденный орб меньше допустимого для этого аспекта
    for asp, angle in ASPECT_ANGLES.items():
        if abs(angle - aspect_angle) < 0.001:
            max_orb = MAX_ORBS.get(asp, 6.0)
            if best_orb <= max_orb:
                return best_dt
            else:
                return None
    return None


def determine_phase_and_peak(
    transit_planet: str,
    natal_lon: float,
    aspect_angle: float,
    forecast_dt: datetime,
    get_position_func: Callable[[str, datetime], Optional[float]]
) -> Tuple[str, Optional[datetime], float]:
    """
    Возвращает (phase, exact_datetime, days_to_peak).
    phase: 'applying', 'exact', 'separating' или 'unknown'.
    """
    # Ищем точное время в диапазоне ±SEARCH_DAYS от forecast
    start = forecast_dt - timedelta(days=SEARCH_DAYS)
    end = forecast_dt + timedelta(days=SEARCH_DAYS)
    exact_dt = find_exact_datetime(transit_planet, natal_lon, aspect_angle, start, end, get_position_func)

    if exact_dt is None:
        # Если не нашли, пробуем более широкий диапазон (±60 дней)
        start2 = forecast_dt - timedelta(days=60)
        end2 = forecast_dt + timedelta(days=60)
        exact_dt = find_exact_datetime(transit_planet, natal_lon, aspect_angle, start2, end2, get_position_func)
        if exact_dt is None:
            return 'unknown', None, 0.0

    # Функция для вычисления орба в заданный момент
    def orb_at(dt: datetime) -> Optional[float]:
        lon = get_position_func(transit_planet, dt)
        if lon is None:
            return None
        raw = abs(lon - natal_lon) % 360.0
        dist = min(raw, 360.0 - raw)
        return abs(dist - aspect_angle)

    orb_now = orb_at(forecast_dt)
    if orb_now is None:
        return 'unknown', exact_dt, 0.0

    # Сравниваем орб через 6 часов
    future_dt = forecast_dt + timedelta(hours=6)
    orb_future = orb_at(future_dt)

    if orb_future is None:
        # Если не можем определить будущее, используем точный момент
        phase = 'exact' if orb_now <= EXACT_TOLERANCE else 'unknown'
    else:
        # Определяем фазу по динамике орба
        if orb_future < orb_now - 0.0001:
            phase = 'applying'
        elif orb_future > orb_now + 0.0001:
            phase = 'separating'
        else:
            phase = 'exact'

    # Если фаза unknown, но орб очень мал — считаем exact
    if phase == 'unknown' and orb_now <= EXACT_TOLERANCE:
        phase = 'exact'

    days_to_peak = (exact_dt - forecast_dt).total_seconds() / 86400.0

    # Проверка согласованности: если exact_dt < forecast_dt, то phase должна быть separating
    # (если только не следующий проход, но в нашем случае мы ищем ближайший минимум)
    if exact_dt < forecast_dt and phase != 'separating':
        phase = 'separating'
    elif exact_dt > forecast_dt and phase != 'applying':
        phase = 'applying'

    return phase, exact_dt, days_to_peak


def deduplicate_events(events: List['TransitEvent']) -> List['TransitEvent']:
    """
    Дедупликация событий на основе (transit_planet, axis_or_target, aspect).
    Для осей (ASC_DSC, MC_IC) оставляем событие с минимальным орбом.
    Для обычных целей – (transit_planet, natal_target, aspect).
    """
    groups = {}
    for ev in events:
        if ev.axis:
            key = (ev.transit_body, ev.axis, ev.aspect)
        else:
            key = (ev.transit_body, ev.natal_target, ev.aspect)
        if key not in groups or ev.orb < groups[key].orb:
            groups[key] = ev
    return list(groups.values())


# ============================================================================
# 3. DATACLASS TRANSIT EVENT
# ============================================================================

@dataclass
class TransitEvent:
    transit_body: str
    natal_target: str
    transit_longitude: float
    natal_target_longitude: float
    aspect: str
    aspect_angle: float
    orb: float
    angular_distance: float
    raw_delta: float
    phase: str = 'unknown'
    exact_datetime: Optional[datetime] = None
    days_to_peak: float = 0.0
    transit_house: int = 0
    natal_target_house: int = 0
    axis: Optional[str] = None          # 'ASC_DSC' или 'MC_IC'
    is_retrograde: bool = False
    transit_speed: float = 0.0
    activity_status: str = 'BACKGROUND'  # 'TODAY', 'ACTIVE', 'BACKGROUND', 'IGNORE'
    priority_label: str = 'BACKGROUND'
    priority_score: float = 0.0
    filter_reason: str = ''

    def unique_key(self) -> str:
        if self.axis:
            return f"{self.transit_body}:{self.axis}:{self.aspect}"
        return f"{self.transit_body}:{self.natal_target}:{self.aspect}"


# ============================================================================
# 4. ОСНОВНОЙ КЛАСС HoroscopeCalculator
# ============================================================================

class HoroscopeCalculator:
    """
    Калькулятор гороскопа с исправленным pipeline транзитных аспектов.
    """

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

        # Натальные данные
        self.natal_planets = self.natal_data['planets']
        self.natal_angles = self.natal_data['angles']
        self.natal_houses = self.natal_data['houses']  # список {'number': int, 'degree': float}

        # Кеш транзитных позиций
        self._transit_cache = {}

        # Списки событий на каждом этапе
        self.raw_events: List[TransitEvent] = []
        self.phase_events: List[TransitEvent] = []
        self.house_events: List[TransitEvent] = []
        self.dedup_events: List[TransitEvent] = []
        self.activity_events: List[TransitEvent] = []
        self.filtered_events: List[TransitEvent] = []
        self.ranked_events: List[TransitEvent] = []
        self.final_events: List[TransitEvent] = []
        self.background_events: List[TransitEvent] = []

        # Строим натальные цели
        self.natal_targets = self._build_natal_targets()

    # ------------------- ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ -------------------

    def _build_natal_targets(self) -> List[Dict]:
        """Формирует список натальных целей (планеты + углы + узлы)."""
        targets = []
        main_names = {'Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                      'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto'}
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

        # Углы
        for angle in ['ASC', 'MC', 'DSC', 'IC']:
            if angle in self.natal_angles and self.natal_angles[angle] is not None:
                a = self.natal_angles[angle]
                lon = normalize_longitude(a['sign'], a['position'])
                targets.append({
                    'name': angle,
                    'longitude': lon,
                    'house': None,
                    'is_angle': True,
                    'weight': TARGET_WEIGHT.get(angle, 9)
                })

        # Дополнительные точки (узлы, Хирон, Лилит)
        extra_names = ['True_North_Lunar_Node', 'True_South_Lunar_Node', 'Chiron', 'True_Lilith']
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
        """Создаёт транзитный субъект на заданную дату (UTC)."""
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
        """Возвращает словарь {планета: долгота} на заданную дату (с кешем)."""
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
        """Извлекает скорость транзитной планеты из субъекта."""
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

    def _calculate_raw_events(self, forecast_date: datetime, days_range: int = 5) -> List[TransitEvent]:
        """
        Этап 1: вычисление сырых транзитных аспектов.
        Использует единую функцию calculate_aspect.
        """
        start = forecast_date - timedelta(days=days_range)
        end = forecast_date + timedelta(days=days_range)

        raw_events = []
        transit_planets = ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                           'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']

        for planet in transit_planets:
            forecast_lon = self._get_transit_position(planet, forecast_date)
            if forecast_lon is None:
                continue

            speed = self._get_transit_speed(planet, forecast_date)
            retro = self._is_retrograde(planet, forecast_date)

            for target in self.natal_targets:
                natal_lon = target['longitude']
                # Единое вычисление аспекта
                aspect_res = calculate_aspect(forecast_lon, natal_lon, MAX_ORBS.get('conjunction', 8.0))
                if aspect_res is None:
                    continue

                # Обработка осей для угловых целей
                axis, primary_target, aspect_corrected, orb = resolve_axis_target(
                    target['name'], aspect_res.aspect, aspect_res.orb
                )
                if axis is not None:
                    target_name = primary_target
                    aspect = aspect_corrected
                    orb_value = orb
                    aspect_angle = ASPECT_ANGLES[aspect]
                else:
                    target_name = target['name']
                    aspect = aspect_res.aspect
                    orb_value = aspect_res.orb
                    aspect_angle = aspect_res.aspect_angle

                event = TransitEvent(
                    transit_body=planet,
                    natal_target=target_name,
                    transit_longitude=forecast_lon,
                    natal_target_longitude=natal_lon,
                    aspect=aspect,
                    aspect_angle=aspect_angle,
                    orb=orb_value,
                    angular_distance=aspect_res.angular_distance,
                    raw_delta=aspect_res.raw_delta,
                    transit_speed=speed,
                    is_retrograde=retro,
                    axis=axis,
                    transit_house=0,
                    natal_target_house=target.get('house', 0),
                    phase='unknown',
                    exact_datetime=None,
                    days_to_peak=0.0,
                    activity_status='BACKGROUND',
                    priority_label='BACKGROUND',
                    priority_score=0.0
                )
                raw_events.append(event)

        logger.info(f"[PIPELINE] RAW: {len(raw_events)} событий")
        self.raw_events = raw_events
        return raw_events

    def _apply_phase_and_peak(self, events: List[TransitEvent], forecast_date: datetime) -> List[TransitEvent]:
        """
        Этап 2: определение фазы и точного времени для каждого события.
        """
        for ev in events:
            phase, exact_dt, days_to_peak = determine_phase_and_peak(
                ev.transit_body,
                ev.natal_target_longitude,
                ev.aspect_angle,
                forecast_date,
                self._get_transit_position
            )
            ev.phase = phase
            ev.exact_datetime = exact_dt
            ev.days_to_peak = days_to_peak

            # Проверка инвариантов
            if ev.phase not in ('applying', 'exact', 'separating', 'unknown'):
                logger.error(f"Invalid phase {ev.phase} for {ev.transit_body}->{ev.natal_target}")
            if ev.phase == 'unknown' and ev.activity_status != 'IGNORE':
                # Это недопустимо для активного события — сигнализируем
                logger.warning(f"Phase unknown for active event {ev.transit_body}->{ev.natal_target}")

        logger.info("[PIPELINE] PHASE/PEAK applied")
        self.phase_events = events
        return events

    def _calculate_houses(self, events: List[TransitEvent], forecast_date: datetime) -> List[TransitEvent]:
        """
        Этап 3: вычисление транзитного дома для каждого события.
        """
        # Преобразуем натальные дома в список {'number': int, 'degree': float}
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

        logger.info("[PIPELINE] HOUSES calculated")
        self.house_events = events
        return events

    def _deduplicate_events(self, events: List[TransitEvent]) -> List[TransitEvent]:
        """
        Этап 4: дедупликация событий.
        Использует ось (если есть) или пару (транзит, цель, аспект).
        """
        deduped = deduplicate_events(events)
        logger.info(f"[PIPELINE] DEDUP: {len(deduped)} (из {len(events)})")
        self.dedup_events = deduped
        return deduped

    def _classify_activity_and_priority(self, events: List[TransitEvent], forecast_date: datetime) -> List[TransitEvent]:
        """
        Этап 5: классификация активности (TODAY, ACTIVE, BACKGROUND, IGNORE)
        и вычисление приоритета (без изменения астрономических полей).
        """
        for ev in events:
            # Активность
            max_orb = MAX_ORBS.get(ev.aspect, 6.0)
            if ev.orb > max_orb:
                ev.activity_status = 'IGNORE'
                ev.filter_reason = f"orb {ev.orb:.2f} > max {max_orb}"
            else:
                threshold = ACTIVE_ORB_THRESHOLDS.get(ev.transit_body, 2.5)
                if abs(ev.days_to_peak) <= DAYS_WINDOW_TODAY:
                    ev.activity_status = 'TODAY'
                elif ev.orb <= threshold:
                    ev.activity_status = 'ACTIVE'
                else:
                    ev.activity_status = 'BACKGROUND'
                    ev.filter_reason = f"orb {ev.orb:.2f} > threshold {threshold}"

            # Приоритет
            planet_w = PLANET_WEIGHT.get(ev.transit_body, 5)
            target_w = TARGET_WEIGHT.get(ev.natal_target, 5)
            aspect_w = ASPECT_WEIGHT.get(ev.aspect, 0.7)
            orb_factor = max(0.1, 1 - ev.orb / 6.0)
            phase_factor = 1.2 if ev.phase == 'applying' else 0.9 if ev.phase == 'separating' else 1.0
            status_factor = {'TODAY': 1.5, 'ACTIVE': 1.2, 'BACKGROUND': 0.5, 'IGNORE': 0.0}.get(ev.activity_status, 1.0)
            angle_factor = 1.4 if ev.axis is not None else 1.0
            distance_factor = max(0.5, 1 - abs(ev.days_to_peak) / 5.0)

            ev.priority_score = (
                (planet_w * target_w * aspect_w / 100.0)
                * orb_factor * phase_factor * status_factor * angle_factor * distance_factor
            )

            # Label
            if ev.activity_status == 'TODAY':
                ev.priority_label = 'PRIMARY'
            elif ev.activity_status == 'ACTIVE':
                if ev.orb < 1.0 or ev.axis is not None:
                    ev.priority_label = 'STRONG'
                else:
                    ev.priority_label = 'SUPPORTING'
            else:
                ev.priority_label = 'BACKGROUND'

        counts = {'TODAY': 0, 'ACTIVE': 0, 'BACKGROUND': 0, 'IGNORE': 0}
        for e in events:
            counts[e.activity_status] += 1
        logger.info(f"[PIPELINE] ACTIVITY: TODAY={counts['TODAY']}, ACTIVE={counts['ACTIVE']}, "
                    f"BACKGROUND={counts['BACKGROUND']}, IGNORE={counts['IGNORE']}")

        self.activity_events = events
        return events

    def _filter_events(self, events: List[TransitEvent]) -> Tuple[List[TransitEvent], List[TransitEvent]]:
        """
        Этап 6: фильтрация — отделяем фоновые и игнорируемые события.
        Возвращает (foreground, background).
        """
        foreground = []
        background = []
        for ev in events:
            if ev.activity_status in ('IGNORE', 'BACKGROUND'):
                background.append(ev)
            else:
                foreground.append(ev)
        logger.info(f"[PIPELINE] FILTER: foreground={len(foreground)}, background={len(background)}")
        self.filtered_events = foreground
        self.background_events = background
        return foreground, background

    def _rank_events(self, events: List[TransitEvent]) -> List[TransitEvent]:
        """
        Этап 7: ранжирование по priority_score (убывание).
        """
        sorted_events = sorted(events, key=lambda x: x.priority_score, reverse=True)
        logger.info(f"[PIPELINE] RANK: {len(sorted_events)}")
        self.ranked_events = sorted_events
        return sorted_events

    def _build_final(self, events: List[TransitEvent], max_events: int = 7) -> List[TransitEvent]:
        """
        Этап 8: выбор топ-N событий для финального вывода.
        """
        final = events[:max_events]
        logger.info(f"[PIPELINE] FINAL: {len(final)}")
        self.final_events = final

        # ---- Инварианты ----
        for ev in final:
            assert ev.orb >= 0, f"Negative orb for {ev.transit_body}->{ev.natal_target}"
            assert ev.aspect in ASPECT_ANGLES, f"Invalid aspect {ev.aspect}"
            assert ev.phase in ('applying', 'exact', 'separating'), f"Invalid phase {ev.phase}"
            assert ev.exact_datetime is not None, f"Missing exact_datetime for {ev.transit_body}->{ev.natal_target}"
            assert ev.transit_longitude is not None, f"Missing transit_longitude"
            assert ev.natal_target_longitude is not None, f"Missing natal_longitude"
            assert ev.angular_distance is not None, f"Missing angular_distance"

            # Математический инвариант
            expected_orb = abs(ev.angular_distance - ASPECT_ANGLES[ev.aspect])
            assert abs(expected_orb - ev.orb) < 1e-6, (
                f"Orb mismatch for {ev.transit_body}->{ev.natal_target}: "
                f"expected {expected_orb:.6f}, got {ev.orb:.6f}"
            )

            # Согласованность фазы и peak
            if ev.phase == 'exact':
                assert abs(ev.days_to_peak) <= EXACT_TOLERANCE, (
                    f"Exact phase but days_to_peak={ev.days_to_peak} for {ev.transit_body}->{ev.natal_target}"
                )
            if ev.exact_datetime < forecast_date and ev.phase != 'separating':
                # Если точное время в прошлом, фаза должна быть separating
                logger.warning(f"Phase mismatch: {ev.transit_body}->{ev.natal_target} has peak in past but phase={ev.phase}")
            if ev.exact_datetime > forecast_date and ev.phase != 'applying':
                logger.warning(f"Phase mismatch: {ev.transit_body}->{ev.natal_target} has peak in future but phase={ev.phase}")

        return final

    # ------------------- ПУБЛИЧНЫЙ МЕТОД -------------------

    def build_context(self, period: str = 'today',
                      target_date: Optional[datetime] = None,
                      days_range: int = 5) -> str:
        """
        Основной метод: выполняет весь pipeline и возвращает текстовый контекст.
        """
        if target_date is None:
            target_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        # 1. Сырые события
        raw = self._calculate_raw_events(target_date, days_range)

        # 2. Фаза и пик
        phase_events = self._apply_phase_and_peak(raw, target_date)

        # 3. Дома
        house_events = self._calculate_houses(phase_events, target_date)

        # 4. Дедупликация
        dedup_events = self._deduplicate_events(house_events)

        # 5. Активность и приоритет
        activity_events = self._classify_activity_and_priority(dedup_events, target_date)

        # 6. Фильтрация
        foreground, background = self._filter_events(activity_events)

        # 7. Ранжирование
        ranked = self._rank_events(foreground)

        # 8. Финальный отбор
        final = self._build_final(ranked, max_events=7)

        # Сохраняем background отдельно для отчёта
        self.background_events = background + [ev for ev in ranked if ev not in final]

        # DEBUG-вывод для каждого финального события
        self._log_debug_events(final)

        return self._format_context(target_date)

    # ------------------- DEBUG-ЛОГИРОВАНИЕ -------------------

    def _log_debug_events(self, events: List[TransitEvent]):
        """Выводит подробный debug для каждого финального события."""
        for ev in events:
            logger.debug(f"""
=== TRANSIT DEBUG ===
Transit planet: {ev.transit_body}
Natal target: {ev.natal_target}
Forecast datetime: {ev.exact_datetime.strftime('%Y-%m-%d %H:%M') if ev.exact_datetime else 'N/A'}
Transit longitude: {ev.transit_longitude:.4f}
Natal longitude: {ev.natal_target_longitude:.4f}
Angular distance: {ev.angular_distance:.4f}
Aspect angle: {ev.aspect_angle:.1f}
Aspect: {ev.aspect}
Orb: {ev.orb:.4f}
Transit speed: {ev.transit_speed:.4f}
Phase: {ev.phase}
Exact datetime: {ev.exact_datetime.strftime('%Y-%m-%d %H:%M') if ev.exact_datetime else 'N/A'}
Peak date: {ev.exact_datetime.strftime('%Y-%m-%d') if ev.exact_datetime else 'N/A'}
Days to peak: {ev.days_to_peak:.2f}
Transit house: {ev.transit_house}
Natal target house: {ev.natal_target_house}
Retrograde: {ev.is_retrograde}
Activity: {ev.activity_status}
Priority: {ev.priority_label}
Priority score: {ev.priority_score:.4f}
""")

    # ------------------- ФОРМАТИРОВАНИЕ КОНТЕКСТА -------------------

    def _format_context(self, target_date: datetime) -> str:
        lines = []
        lines.append(f"### Прогноз на день")
        lines.append(f"Дата: {target_date.strftime('%d.%m.%Y')}")
        lines.append("")

        lines.append("### Натальные данные")
        lines.append("")
        # Углы
        for angle in ['ASC', 'MC', 'DSC', 'IC']:
            if angle in self.natal_angles and self.natal_angles[angle] is not None:
                a = self.natal_angles[angle]
                sign = a.get('sign', '')
                pos = a.get('position', 0.0)
                lines.append(f"{angle}: {sign} {pos:.2f}°")
        lines.append("")
        # Основные планеты
        main_names = ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                      'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']
        for p in self.natal_planets:
            if p['name'] in main_names:
                sign = p['sign']
                deg = p['degree']
                house = p.get('house', 0)
                retro = p.get('retrograde', False)
                line = f"{p['name']}: {sign} {deg:.2f}°, {house} дом"
                if retro:
                    line += ", ретроградный"
                lines.append(line)
        lines.append("")

        # Основные транзиты — используем ТОЛЬКО final_events
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
                transit_house = ev.transit_house
                natal_house = ev.natal_target_house
                days_to_peak = ev.days_to_peak

                # Локализация (можно вынести в отдельный модуль)
                aspect_names = {'conjunction': 'соединение', 'opposition': 'оппозиция',
                                'trine': 'трин', 'square': 'квадрат', 'sextile': 'секстиль'}
                aspect_ru = aspect_names.get(aspect, aspect)
                phase_text = {'applying': 'сходящийся', 'exact': 'точный', 'separating': 'расходящийся'}.get(phase, '')

                line = f"{planet} транзитный — {aspect_ru} — натальное {target}"
                if phase_text:
                    line += f", орб {orb:.2f}°, {phase_text}"
                else:
                    line += f", орб {orb:.2f}°"
                lines.append(line)

                if transit_house:
                    lines.append(f"Транзитная планета активирует {transit_house} дом")
                if natal_house:
                    lines.append(f"Натальный {target} находится в {natal_house} доме")

                if ev.activity_status == 'TODAY':
                    lines.append("Пик влияния: сегодня")
                elif ev.activity_status == 'ACTIVE':
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

    # ------------------- QA ОТЧЁТ И СТАТИСТИКА -------------------

    def get_qa_report(self) -> str:
        """Возвращает отладочный отчёт по ключевым транзитам."""
        target_events = [
            ('Sun', 'Mars'),
            ('Uranus', 'ASC'),
            ('Pluto', 'ASC'),
            ('Neptune', 'ASC'),
            ('Mars', 'MC'),
            ('Neptune', 'MC'),
        ]
        all_events = self.ranked_events + self.background_events
        final_ids = {id(e) for e in self.final_events}

        found = {}
        for ev in all_events:
            key = (ev.transit_body, ev.natal_target)
            if key in target_events and key not in found:
                found[key] = ev

        lines = []
        lines.append("=== QA ОТЧЁТ ===")
        lines.append("")
        lines.append("| planet → target | transit_lon | natal_lon | angular_dist | aspect | orb | phase | exact_datetime | peak_date | days_to_peak | activity | priority | FINAL/BACKGROUND | причина |")
        lines.append("|-----------------|-------------|-----------|--------------|--------|-----|-------|----------------|-----------|--------------|----------|----------|------------------|---------|")

        for key in target_events:
            ev = found.get(key)
            if ev:
                peak_date = ev.exact_datetime.strftime('%Y-%m-%d') if ev.exact_datetime else 'N/A'
                exact_dt = ev.exact_datetime.strftime('%Y-%m-%d %H:%M') if ev.exact_datetime else 'N/A'
                is_final = "FINAL" if id(ev) in final_ids else "BACKGROUND"
                reason = ev.filter_reason if ev.filter_reason else ("Not in top 7 by priority" if not is_final else "")
                lines.append(
                    f"| {ev.transit_body} → {ev.natal_target} | {ev.transit_longitude:.2f} | {ev.natal_target_longitude:.2f} | {ev.angular_distance:.2f} | {ev.aspect} | {ev.orb:.4f} | {ev.phase} | {exact_dt} | {peak_date} | {ev.days_to_peak:.2f} | {ev.activity_status} | {ev.priority_label} | {is_final} | {reason} |"
                )
            else:
                lines.append(f"| {key[0]} → {key[1]} | - | - | - | - | - | - | - | - | - | - | - | НЕ НАЙДЕНО | - |")

        lines.append("")
        lines.append(f"RAW total: {len(self.raw_events)}")
        lines.append(f"PHASE applied")
        lines.append(f"DEDUP total: {len(self.dedup_events)}")
        counts = {'TODAY': 0, 'ACTIVE': 0, 'BACKGROUND': 0, 'IGNORE': 0}
        for e in self.activity_events:
            counts[e.activity_status] += 1
        lines.append(f"ACTIVITY: TODAY={counts['TODAY']}, ACTIVE={counts['ACTIVE']}, BACKGROUND={counts['BACKGROUND']}, IGNORE={counts['IGNORE']}")
        pri_counts = {'PRIMARY': 0, 'STRONG': 0, 'SUPPORTING': 0, 'BACKGROUND': 0}
        for e in self.activity_events:
            pri_counts[e.priority_label] += 1
        lines.append(f"PRIORITY: PRIMARY={pri_counts['PRIMARY']}, STRONG={pri_counts['STRONG']}, SUPPORTING={pri_counts['SUPPORTING']}, BACKGROUND={pri_counts['BACKGROUND']}")
        lines.append(f"FINAL: {len(self.final_events)}")
        lines.append("")
        lines.append("EXCLUDED:")
        excluded = []
        for ev in self.background_events:
            if ev not in self.final_events:
                excluded.append(f"- {ev.transit_body} → {ev.natal_target}: {ev.filter_reason}")
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
            'phase_applied': len(self.phase_events),
            'dedup': len(self.dedup_events),
            'activity': {
                'today': sum(1 for e in self.activity_events if e.activity_status == 'TODAY'),
                'active': sum(1 for e in self.activity_events if e.activity_status == 'ACTIVE'),
                'background': sum(1 for e in self.activity_events if e.activity_status == 'BACKGROUND'),
                'ignore': sum(1 for e in self.activity_events if e.activity_status == 'IGNORE'),
            },
            'priority': {
                'primary': sum(1 for e in self.activity_events if e.priority_label == 'PRIMARY'),
                'strong': sum(1 for e in self.activity_events if e.priority_label == 'STRONG'),
                'supporting': sum(1 for e in self.activity_events if e.priority_label == 'SUPPORTING'),
                'background': sum(1 for e in self.activity_events if e.priority_label == 'BACKGROUND'),
            },
            'filtered': len(self.filtered_events),
            'background_events': len(self.background_events),
            'final': len(self.final_events),
        }