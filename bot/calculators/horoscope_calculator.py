from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from kerykeion import AstrologicalSubject

from bot.calculators.astrology_calculator import AstrologyCalculator

logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS
# ============================================================================

SUPPORTED_PERIODS = {"day", "month", "year"}

TRANSIT_PLANETS = (
    "sun",
    "moon",
    "mercury",
    "venus",
    "mars",
    "jupiter",
    "saturn",
    "uranus",
    "neptune",
    "pluto",
)

FAST_PLANETS = {
    "sun",
    "moon",
    "mercury",
    "venus",
    "mars",
}

SLOW_PLANETS = {
    "jupiter",
    "saturn",
    "uranus",
    "neptune",
    "pluto",
}

PERSONAL_TARGETS = {
    "sun",
    "moon",
    "mercury",
    "venus",
    "mars",
}

ANGLE_TARGETS = {
    "ascendant",
    "medium_coeli",
    "descendant",
    "imum_coeli",
}

NATAL_PLANETS = {
    "sun",
    "moon",
    "mercury",
    "venus",
    "mars",
    "jupiter",
    "saturn",
    "uranus",
    "neptune",
    "pluto",
    "chiron",
    "true_north_lunar_node",
}

NATAL_TARGETS = NATAL_PLANETS | ANGLE_TARGETS

MAJOR_ASPECT_ANGLES = {
    "conjunction": 0.0,
    "sextile": 60.0,
    "square": 90.0,
    "trine": 120.0,
    "opposition": 180.0,
}

DEFAULT_ASPECT_ORBS = {
    "conjunction": 5.0,
    "opposition": 5.0,
    "square": 4.0,
    "trine": 4.0,
    "sextile": 3.0,
}

ASPECT_WEIGHT = {
    "conjunction": 1.00,
    "opposition": 0.95,
    "square": 0.90,
    "trine": 0.85,
    "sextile": 0.75,
}

BASE_PLANET_WEIGHT = {
    "pluto": 10.0,
    "neptune": 9.0,
    "uranus": 9.0,
    "saturn": 8.0,
    "jupiter": 7.0,
    "mars": 6.0,
    "venus": 5.0,
    "mercury": 5.0,
    "sun": 5.0,
    "moon": 3.0,
}

PERIOD_PLANET_WEIGHTS = {
    "day": {
        "moon": 10.0,
        "sun": 9.0,
        "mercury": 8.0,
        "venus": 8.0,
        "mars": 8.0,
        "jupiter": 6.0,
        "saturn": 5.0,
        "uranus": 5.0,
        "neptune": 5.0,
        "pluto": 5.0,
    },
    "month": {
        "moon": 7.0,
        "sun": 7.0,
        "mercury": 6.0,
        "venus": 6.0,
        "mars": 6.0,
        "jupiter": 8.0,
        "saturn": 8.0,
        "uranus": 8.0,
        "neptune": 8.0,
        "pluto": 8.0,
    },
    "year": {
        "moon": 3.0,
        "sun": 5.0,
        "mercury": 4.0,
        "venus": 4.0,
        "mars": 5.0,
        "jupiter": 8.0,
        "saturn": 9.0,
        "uranus": 9.0,
        "neptune": 9.0,
        "pluto": 10.0,
    },
}

TARGET_WEIGHT = {
    "sun": 10.0,
    "moon": 10.0,
    "ascendant": 10.0,
    "medium_coeli": 9.0,
    "descendant": 8.0,
    "imum_coeli": 7.0,
    "mercury": 8.0,
    "venus": 8.0,
    "mars": 8.0,
    "jupiter": 6.0,
    "saturn": 6.0,
    "uranus": 5.0,
    "neptune": 5.0,
    "pluto": 5.0,
    "chiron": 3.0,
    "true_north_lunar_node": 3.0,
}

PLANET_RU = {
    "sun": "Солнце",
    "moon": "Луна",
    "mercury": "Меркурий",
    "venus": "Венера",
    "mars": "Марс",
    "jupiter": "Юпитер",
    "saturn": "Сатурн",
    "uranus": "Уран",
    "neptune": "Нептун",
    "pluto": "Плутон",
    "chiron": "Хирон",
    "true_north_lunar_node": "Северный лунный узел",
}

TARGET_RU = {
    **PLANET_RU,
    "ascendant": "ASC",
    "medium_coeli": "MC",
    "descendant": "DSC",
    "imum_coeli": "IC",
}

ASPECT_RU = {
    "conjunction": "соединение",
    "opposition": "оппозиция",
    "square": "квадрат",
    "trine": "трин",
    "sextile": "секстиль",
}

PHASE_RU = {
    "applying": "сходящийся (влияние нарастает)",
    "exact": "точный (кульминация)",
    "separating": "расходящийся (влияние спадает)",
    "stationary": "стационарный",
    "unknown": "не определена",
}

THEME_FOR_TARGET = {
    "sun": "identity",
    "moon": "emotions",
    "mercury": "communication",
    "venus": "relationships",
    "mars": "action",
    "jupiter": "growth",
    "saturn": "responsibility",
    "uranus": "change",
    "neptune": "meaning",
    "pluto": "transformation",
    "chiron": "healing",
    "true_north_lunar_node": "direction",
    "ascendant": "self",
    "medium_coeli": "career",
    "descendant": "relationships",
    "imum_coeli": "home",
}


# ============================================================================
# HELPERS
# ============================================================================

def normalize_name(value: Any) -> str:
    if value is None:
        return ""
    return (
        str(value)
        .strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("'", "")
    )


def to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def normalize_longitude(value: float) -> float:
    return value % 360.0


def angular_distance(a: float, b: float) -> float:
    diff = abs(normalize_longitude(a) - normalize_longitude(b))
    return min(diff, 360.0 - diff)


def signed_angle_difference(a: float, b: float) -> float:
    return ((a - b + 180.0) % 360.0) - 180.0


def get_attr_safe(obj: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def datetime_key(dt: datetime) -> str:
    dt = ensure_utc(dt)
    return dt.isoformat(timespec="seconds")


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def midpoint(a: datetime, b: datetime) -> datetime:
    return a + (b - a) / 2


# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass(frozen=True)
class EngineConfig:
    aspect_orbs: Mapping[str, float] = field(
        default_factory=lambda: dict(DEFAULT_ASPECT_ORBS)
    )

    exact_tolerance_deg: float = 0.05
    exact_tolerance_seconds: float = 180.0
    root_tolerance_seconds: float = 30.0

    day_step_minutes: int = 30
    month_step_hours: int = 12
    year_step_hours: int = 48  # было 24

    include_moon_in_year: bool = False
    include_fast_planets_year: bool = True

    boundary_search_hours_fast: int = 168
    boundary_search_days_slow: int = 365
    boundary_search_max_iterations: int = 12

    retrograde_coarse_hours: int = 48
    retrograde_mid_hours: int = 12
    retrograde_final_seconds: int = 60
    retrograde_refine_hours: int = 72
    retrograde_speed_epsilon: float = 0.00001

    foreground_max_orb: float = 3.0
    very_tight_orb: float = 0.5
    slow_planet_tight_orb: float = 1.5
    fast_planet_tight_orb: float = 1.5
    angle_applying_orb: float = 2.5

    max_events_per_period: int = 500
    max_events_per_theme: int = 8

    max_final_events_day: int = 15
    max_final_events_month: int = 15
    max_final_events_year: int = 30

    max_scan_days: int = 5000

    applying_bonus: float = 1.5
    separating_bonus: float = 0.15
    angle_bonus: float = 2.5
    personal_target_bonus: float = 1.0
    retrograde_bonus: float = 0.5
    repeated_hit_bonus: float = 1.25

    day_exact_orb_limit: float = 1.0
    day_moon_orb_limit: float = 5.0
    day_fast_orb_limit: float = 3.0
    day_slow_orb_limit: float = 5.0
    day_score_threshold: float = 10.0

    month_exact_orb_limit: float = 1.0
    month_fast_orb_limit: float = 2.0
    month_slow_orb_limit: float = 6.0
    month_score_threshold: float = 15.0

    year_exact_orb_limit: float = 0.5
    year_fast_orb_limit: float = 1.0
    year_slow_orb_limit: float = 8.0
    year_score_threshold: float = 10.0

    month_candidate_merge_gap_hours: float = 2.0
    month_max_refinement_candidates: int = 50
    month_max_moon_hits_per_key: int = 2

    year_candidate_merge_gap_hours: float = 72.0
    year_max_refinement_candidates: int = 60  # Уменьшено с 150 до 100, потом до 60

    boundary_tolerance_seconds: int = 60
    log_snapshots: bool = False
    debug_geometry: bool = False

    def period_step_seconds(self, period_type: str) -> int:
        if period_type == "day":
            return self.day_step_minutes * 60
        if period_type == "month":
            return self.month_step_hours * 3600
        if period_type == "year":
            return self.year_step_hours * 3600
        raise ValueError(f"Unsupported period_type={period_type!r}")

    def max_final_events(self, period_type: str) -> int:
        if period_type == "day":
            return self.max_final_events_day
        if period_type == "month":
            return self.max_final_events_month
        if period_type == "year":
            return self.max_final_events_year
        raise ValueError(f"Unsupported period_type={period_type!r}")


DEFAULT_CONFIG = EngineConfig()


# ============================================================================
# DATA OBJECTS
# ============================================================================

@dataclass(frozen=True)
class ForecastPeriod:
    period_type: str
    start_utc: datetime
    end_utc: datetime

    def __post_init__(self) -> None:
        start = ensure_utc(self.start_utc)
        end = ensure_utc(self.end_utc)

        if self.period_type not in SUPPORTED_PERIODS:
            raise ValueError(f"Unsupported period_type={self.period_type!r}")

        if end <= start:
            raise ValueError("Forecast period end must be greater than start.")

        if (end - start).days > DEFAULT_CONFIG.max_scan_days:
            raise ValueError("Forecast period exceeds max_scan_days.")


@dataclass
class PlanetSnapshot:
    timestamp: datetime
    longitude: float
    speed: float
    retrograde: bool
    house: Any = None


@dataclass
class TransitEvent:
    transit_body: str
    natal_target: str
    aspect: str
    aspect_angle: float
    start_utc: Optional[datetime]
    exact_utc: Optional[datetime]
    end_utc: Optional[datetime]
    orb_at_exact: float
    phase: str
    transit_longitude: float
    natal_longitude: float
    transit_house: Any = None
    natal_house: Any = None
    is_retrograde: bool = False
    transit_speed: float = 0.0
    score: float = 0.0
    activity: str = "BACKGROUND"
    reason: str = ""
    hit_index: int = 1
    theme: str = ""
    exact_hit: bool = False
    boundary_limited: bool = False
    nearest_utc: Optional[datetime] = None
    nearest_orb: float = 999.0
    source_type: str = "transit"
    target_type: str = "natal"
    boundary_type: str = "inside"

    @property
    def unique_key(self) -> str:
        return f"{self.transit_body}:{self.natal_target}:{self.aspect}:{self.hit_index}"

    @property
    def semantic_key(self) -> Tuple[str, str, str]:
        return (self.transit_body, self.natal_target, self.aspect)

    @property
    def display_name(self) -> str:
        source = PLANET_RU.get(self.transit_body, self.transit_body)
        target = TARGET_RU.get(self.natal_target, self.natal_target)
        aspect = ASPECT_RU.get(self.aspect, self.aspect)
        return f"{source} ({self.source_type}) — {aspect} — {target} ({self.target_type})"


@dataclass
class TransitEpisode:
    transit_body: str
    natal_target: str
    aspect: str
    theme: str
    first_start_utc: Optional[datetime]
    last_end_utc: Optional[datetime]
    exact_hits: List[datetime] = field(default_factory=list)
    nearest_approaches: List[Tuple[datetime, float]] = field(default_factory=list)
    exact_hits_count: int = 0
    max_score: float = 0.0
    hit_count: int = 0
    retrograde_hits: int = 0
    phase: str = ""
    min_orb: float = 0.0
    boundary_limited: bool = False
    boundary_type: str = "inside"
    source_type: str = "transit"
    target_type: str = "natal"

    @property
    def semantic_key(self) -> Tuple[str, str, str]:
        return (self.transit_body, self.natal_target, self.aspect)

    @property
    def display_name(self) -> str:
        source = PLANET_RU.get(self.transit_body, self.transit_body)
        target = TARGET_RU.get(self.natal_target, self.natal_target)
        aspect = ASPECT_RU.get(self.aspect, self.aspect)
        return f"{source} ({self.source_type}) — {aspect} — {target} ({self.target_type})"


@dataclass
class RetrogradeWindow:
    planet: str
    station_start_utc: datetime
    station_exact_utc: datetime
    station_end_utc: datetime
    before_speed: float
    station_speed: float
    after_speed: float
    retrograde_after: bool

    @property
    def is_stationary(self) -> bool:
        return abs(self.station_speed) < 0.0001


# ============================================================================
# ENGINE
# ============================================================================

class HoroscopeCalculator:
    VERSION = "3.0.0"

    def __init__(
        self,
        user_data: Dict[str, Any],
        lang: str = "ru",
        telegram_id: Optional[int] = None,
        coords: Optional[Tuple[float, float, str]] = None,
        emulation_mode: bool = False,
        gemini_service: Optional[Any] = None,
        config: EngineConfig = DEFAULT_CONFIG,
    ) -> None:
        self.user_data = user_data
        self.lang = lang
        self.telegram_id = telegram_id
        self.coords = coords
        self.emulation_mode = emulation_mode
        self.config = config
        self.gemini_service = gemini_service

        self.astro_calc = AstrologyCalculator(
            user_data,
            lang=lang,
            telegram_id=telegram_id,
            coords=coords,
            emulation_mode=False,
        )
        self.natal_data = self.astro_calc._build_natal_chart()
        self.natal_subject = self.astro_calc._subject

        location = self.natal_data.get("location", {})
        lat = to_float(location.get("lat"))
        lng = to_float(location.get("lng"))

        if lat is None or lng is None:
            if coords is not None:
                lat, lng, _ = coords
            else:
                raise ValueError(
                    "Natal coordinates are required for transit calculations."
                )

        self.lat = float(lat)
        self.lng = float(lng)

        self._snapshot_cache: Dict[str, AstrologicalSubject] = {}
        self._planet_snapshot_cache: Dict[Tuple[str, str], PlanetSnapshot] = {}
        self._retrograde_cache: Dict[Tuple[str, str, str], RetrogradeWindow] = {}
        self._natal_points = self._extract_natal_points()

        self.events: List[TransitEvent] = []
        self.episodes: List[TransitEpisode] = []
        self.retrograde_windows: Dict[str, List[RetrogradeWindow]] = defaultdict(list)

        self.stats: Dict[str, int] = {
            "snapshot_requests": 0,
            "snapshot_created": 0,
            "snapshot_cache_hits": 0,
            "candidate_windows": 0,
            "exact_hits": 0,
            "near_hits": 0,
            "boundary_candidates": 0,
            "false_exact_rejected": 0,
            "retrograde_candidates": 0,
            "retrograde_refinements": 0,
            "month_raw_candidate_windows": 0,
            "month_merged_candidate_windows": 0,
            "month_pre_ranked_candidates": 0,
            "month_refinement_candidates": 0,
            "month_candidates_skipped_by_budget": 0,
            "month_moon_hits_suppressed": 0,
            "year_raw_candidate_windows": 0,
            "year_merged_candidate_windows": 0,
            "year_pre_ranked_candidates": 0,
            "year_refinement_candidates": 0,
            "year_candidates_skipped_by_budget": 0,
        }

    # ======================================================================
    # NATAL
    # ======================================================================

    def _get_model_dict(self, subject: AstrologicalSubject) -> Dict[str, Any]:
        model = getattr(subject, "model", None)
        if callable(model):
            model = model()
        if model is None:
            model = subject
        if hasattr(model, "model_dump"):
            data = model.model_dump()
        elif hasattr(model, "dict"):
            data = model.dict()
        else:
            data = getattr(model, "__dict__", {})

        return data

    def _point_dict(self, subject: AstrologicalSubject, name: str) -> Optional[Dict[str, Any]]:
        data = self._get_model_dict(subject)
        alt_name = name.capitalize()
        value = data.get(alt_name)
        if value is not None:
            logger.debug("[POINT_DICT] Found '%s' using capitalized key '%s'", name, alt_name)
        else:
            value = data.get(name)
            if value is None:
                if name in ("uranus", "saturn", "jupiter", "neptune", "pluto"):
                    logger.warning("[POINT_DICT] Planet %s not found. Available keys: %s", name, list(data.keys())[:20])
                return None
        if name == "uranus" or alt_name == "Uranus":
            logger.debug("[POINT_DICT] uranus data: %s", value)
        if isinstance(value, dict):
            abs_pos = to_float(value.get("abs_pos"))
            logger.debug("[POINT_DICT] %s: abs_pos=%s", name, abs_pos)
            return value
        abs_pos = to_float(get_attr_safe(value, "abs_pos"))
        logger.debug("[POINT_DICT] %s (object): abs_pos=%s", name, abs_pos)
        return {
            "abs_pos": to_float(get_attr_safe(value, "abs_pos")),
            "position": to_float(get_attr_safe(value, "position")),
            "sign": get_attr_safe(value, "sign"),
            "house": get_attr_safe(value, "house"),
            "speed": to_float(get_attr_safe(value, "speed"), 0.0),
            "retrograde": bool(get_attr_safe(value, "retrograde", False)),
        }

    def _extract_natal_points(self) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        for name in NATAL_TARGETS:
            data = self._point_dict(self.natal_subject, name)
            if not data:
                continue
            longitude = to_float(data.get("abs_pos"))
            if longitude is None:
                continue
            result[name] = {**data, "abs_pos": normalize_longitude(longitude)}
        return result

    # ======================================================================
    # PERIOD
    # ======================================================================

    def _validate_period(self, period: ForecastPeriod) -> None:
        duration = period.end_utc - period.start_utc
        if duration.total_seconds() <= 0:
            raise ValueError("Invalid forecast period.")
        if duration.days > self.config.max_scan_days:
            raise ValueError("Forecast period exceeds configured safety limit.")

    def _planets_for_period(self, period_type: str) -> Tuple[str, ...]:
        if period_type == "day":
            return TRANSIT_PLANETS
        if period_type == "month":
            return TRANSIT_PLANETS
        if period_type == "year":
            planets = list(TRANSIT_PLANETS)
            if not self.config.include_moon_in_year:
                planets.remove("moon")
            return tuple(planets)
        raise ValueError(f"Unsupported period_type={period_type!r}")

    # ======================================================================
    # SNAPSHOT CACHE
    # ======================================================================

    def _snapshot(self, timestamp: datetime) -> AstrologicalSubject:
        timestamp = ensure_utc(timestamp)
        key = datetime_key(timestamp)
        self.stats["snapshot_requests"] += 1

        cached = self._snapshot_cache.get(key)
        if cached is not None:
            self.stats["snapshot_cache_hits"] += 1
            return cached

        logger.debug("[SNAPSHOT] CREATING NEW subject for %s", key)
        subject = AstrologicalSubject(
            name="Transit",
            year=timestamp.year,
            month=timestamp.month,
            day=timestamp.day,
            hour=timestamp.hour,
            minute=timestamp.minute,
            lat=self.lat,
            lng=self.lng,
            tz_str="UTC",
        )

        self._snapshot_cache[key] = subject
        self.stats["snapshot_created"] += 1
        return subject

    def _extract_transit_planet(self, subject: AstrologicalSubject, planet: str) -> Optional[PlanetSnapshot]:
        snapshot_time = datetime(
            subject.year,
            subject.month,
            subject.day,
            subject.hour,
            subject.minute,
            tzinfo=timezone.utc,
        )
        key = (datetime_key(snapshot_time), planet)

        if planet == "uranus":
            cached = None
        else:
            cached = self._planet_snapshot_cache.get(key)

        if cached is not None:
            logger.debug("[EXTRACT] CACHE HIT for %s at %s: lon=%.4f", planet, snapshot_time.isoformat(),
                        cached.longitude)
            return cached

        data = self._point_dict(subject, planet)
        if not data:
            logger.warning("[EXTRACT] No data for planet %s at %s", planet, snapshot_time.isoformat())
            return None

        longitude = to_float(data.get("abs_pos"))
        if longitude is None:
            logger.warning("[EXTRACT] No abs_pos for planet %s", planet)
            return None

        speed = to_float(data.get("speed"), 0.0) or 0.0
        retrograde = bool(data.get("retrograde", False))

        logger.debug("[EXTRACT] NEW data for %s at %s: lon=%.4f (speed=%.4f, retro=%s)",
                    planet,
                    snapshot_time.isoformat(),
                    longitude,
                    speed,
                    retrograde)

        snapshot = PlanetSnapshot(
            timestamp=snapshot_time,
            longitude=normalize_longitude(longitude),
            speed=speed,
            retrograde=retrograde,
            house=data.get("house"),
        )

        self._planet_snapshot_cache[key] = snapshot
        return snapshot

    # ======================================================================
    # SAMPLING
    # ======================================================================

    def _sampling_step(self, period_type: str) -> timedelta:
        return timedelta(seconds=self.config.period_step_seconds(period_type))

    def _generate_sampling_times(self, period: ForecastPeriod) -> List[datetime]:
        step = self._sampling_step(period.period_type)
        result: List[datetime] = []
        cursor = ensure_utc(period.start_utc)
        while cursor < period.end_utc:
            result.append(cursor)
            cursor += step
        if not result or result[-1] != period.end_utc:
            result.append(ensure_utc(period.end_utc))
        return result

    # ======================================================================
    # ASPECT MATH
    # ======================================================================

    def _aspect_orb(
        self,
        planet_longitude: float,
        natal_longitude: float,
        aspect_angle: float,
    ) -> float:
        distance = angular_distance(planet_longitude, natal_longitude)
        return abs(distance - aspect_angle)

    def _aspect_state(
        self,
        planet_longitude: float,
        natal_longitude: float,
    ) -> List[Tuple[str, float]]:
        result: List[Tuple[str, float]] = []
        distance = angular_distance(planet_longitude, natal_longitude)
        for aspect, angle in MAJOR_ASPECT_ANGLES.items():
            orb = abs(distance - angle)
            max_orb = self.config.aspect_orbs.get(aspect, 0.0)
            if orb <= max_orb:
                result.append((aspect, orb))
        return result

    # ======================================================================
    # CANDIDATE DETECTION
    # ======================================================================

    def _detect_candidate_windows(
            self,
            period: ForecastPeriod,
            planets: Sequence[str],
    ) -> List[Tuple[str, str, str, datetime, datetime]]:
        timestamps = self._generate_sampling_times(period)

        active_intervals: Dict[Tuple[str, str, str], Tuple[datetime, datetime]] = {}
        candidates: List[Tuple[str, str, str, datetime, datetime]] = []

        for timestamp in timestamps:
            subject = self._snapshot(timestamp)
            current_keys: set = set()
            for planet in planets:
                transit = self._extract_transit_planet(subject, planet)
                if transit is None:
                    continue
                for target, natal_data in self._natal_points.items():
                    natal_longitude = to_float(natal_data.get("abs_pos"))
                    if natal_longitude is None:
                        continue
                    states = self._aspect_state(transit.longitude, natal_longitude)
                    for aspect, orb in states:
                        key = (planet, target, aspect)
                        current_keys.add(key)
                        if key in active_intervals:
                            start, last = active_intervals[key]
                            active_intervals[key] = (start, timestamp)
                        else:
                            active_intervals[key] = (timestamp, timestamp)

            keys_to_close = [key for key in active_intervals if key not in current_keys]
            for key in keys_to_close:
                start, last = active_intervals.pop(key)
                candidates.append((key[0], key[1], key[2], start, last))

        for key, (start, last) in active_intervals.items():
            candidates.append((key[0], key[1], key[2], start, last))

        if period.period_type == "month":
            self.stats["month_raw_candidate_windows"] = len(candidates)
        elif period.period_type == "year":
            self.stats["year_raw_candidate_windows"] = len(candidates)

        if period.period_type == "month":
            candidates = self._merge_candidate_windows_for_period(
                candidates,
                gap_hours=self.config.month_candidate_merge_gap_hours
            )
            self.stats["month_merged_candidate_windows"] = len(candidates)
        elif period.period_type == "year":
            candidates = self._merge_candidate_windows_for_period(
                candidates,
                gap_hours=self.config.year_candidate_merge_gap_hours
            )
            self.stats["year_merged_candidate_windows"] = len(candidates)

        self.stats["candidate_windows"] = len(candidates)
        logger.info("[CANDIDATES] windows=%d snapshots=%d",
                    len(candidates),
                    self.stats["snapshot_created"])
        return candidates

    # ======================================================================
    # PRE-RANKING
    # ======================================================================

    def _candidate_pre_score(
            self,
            candidate: Tuple[str, str, str, datetime, datetime],
            period_type: str,
    ) -> float:
        planet, target, aspect, start, end = candidate
        planet_weight = PERIOD_PLANET_WEIGHTS.get(period_type, BASE_PLANET_WEIGHT).get(planet, 0.0)
        target_weight = TARGET_WEIGHT.get(target, 0.0)
        aspect_weight = ASPECT_WEIGHT.get(aspect, 0.0)

        mid = start + (end - start) / 2
        subject = self._snapshot(mid)
        transit = self._extract_transit_planet(subject, planet)
        natal = self._natal_points.get(target)
        if transit is None or natal is None:
            return 0.0
        natal_lon = to_float(natal.get("abs_pos"))
        if natal_lon is None:
            return 0.0
        orb = angular_distance(transit.longitude, natal_lon)
        min_orb = min(abs(orb - angle) for angle in MAJOR_ASPECT_ANGLES.values())
        tightness_bonus = max(0.0, 1.0 - min_orb / 10.0) * 2.0

        try:
            before = start + (end - start) * 0.25
            after = start + (end - start) * 0.75
            sub_before = self._snapshot(before)
            sub_after = self._snapshot(after)
            tr_before = self._extract_transit_planet(sub_before, planet)
            tr_after = self._extract_transit_planet(sub_after, planet)
            if tr_before and tr_after:
                orb_before = angular_distance(tr_before.longitude, natal_lon)
                orb_after = angular_distance(tr_after.longitude, natal_lon)
                if orb_before > orb_after:
                    applying_bonus = self.config.applying_bonus
                else:
                    applying_bonus = self.config.separating_bonus
            else:
                applying_bonus = 0.0
        except Exception:
            applying_bonus = 0.0

        score = planet_weight + target_weight + aspect_weight * 3.0 + tightness_bonus + applying_bonus
        return round(score, 2)

    # ======================================================================
    # ROOT / EXACT
    # ======================================================================

    def _aspect_function(
        self,
        timestamp: datetime,
        planet: str,
        target: str,
        aspect: str,
    ) -> float:
        subject = self._snapshot(timestamp)
        transit = self._extract_transit_planet(subject, planet)
        natal = self._natal_points.get(target)
        if transit is None or natal is None:
            raise RuntimeError("Missing planet or natal target.")
        natal_longitude = to_float(natal.get("abs_pos"))
        if natal_longitude is None:
            raise RuntimeError("Missing natal longitude.")
        distance = angular_distance(transit.longitude, natal_longitude)
        target_angle = MAJOR_ASPECT_ANGLES[aspect]
        return distance - target_angle

    def _refine_exact_hit(
        self,
        planet: str,
        target: str,
        aspect: str,
        start: datetime,
        end: datetime,
    ) -> Optional[datetime]:
        start = ensure_utc(start)
        end = ensure_utc(end)
        if end <= start:
            return None

        tolerance = timedelta(seconds=self.config.root_tolerance_seconds)
        left, right = start, end
        phi = (1.0 + math.sqrt(5.0)) / 2.0

        while right - left > tolerance:
            span = (right - left).total_seconds()
            x1 = right - timedelta(seconds=span / phi)
            x2 = left + timedelta(seconds=span / phi)
            f1 = abs(self._aspect_function(x1, planet, target, aspect))
            f2 = abs(self._aspect_function(x2, planet, target, aspect))
            if f1 < f2:
                right = x2
            else:
                left = x1

        result = midpoint(left, right)
        orb = abs(self._aspect_function(result, planet, target, aspect))
        max_orb = self.config.aspect_orbs[aspect]
        if orb > max_orb:
            return None
        return result

    # ======================================================================
    # BOUNDARY SEARCH
    # ======================================================================

    def _boundary_radius(self, planet: str, period_type: str) -> timedelta:
        if planet in SLOW_PLANETS:
            if period_type == "year":
                return timedelta(days=30)
            return timedelta(days=self.config.boundary_search_days_slow)
        return timedelta(hours=self.config.boundary_search_hours_fast)

    def _find_boundary(
        self,
        planet: str,
        target: str,
        aspect: str,
        center: datetime,
        direction: int,
        period: ForecastPeriod,
    ) -> Optional[datetime]:
        radius = self._boundary_radius(planet, period.period_type)
        boundary = center + direction * radius
        boundary = max(period.start_utc, min(boundary, period.end_utc))
        if boundary == center:
            return None

        center_orb = abs(self._aspect_function(center, planet, target, aspect))
        boundary_orb = abs(self._aspect_function(boundary, planet, target, aspect))
        max_orb = self.config.aspect_orbs[aspect]

        if center_orb <= max_orb and boundary_orb <= max_orb:
            return boundary
        if center_orb > max_orb and boundary_orb > max_orb:
            return None

        left, right = min(center, boundary), max(center, boundary)
        for _ in range(50):
            if right - left <= timedelta(seconds=self.config.root_tolerance_seconds):
                break
            mid = midpoint(left, right)
            orb = abs(self._aspect_function(mid, planet, target, aspect))
            if orb <= max_orb:
                if direction < 0:
                    left = mid
                else:
                    right = mid
            else:
                if direction < 0:
                    right = mid
                else:
                    left = mid
        return left if direction < 0 else right

    # ======================================================================
    # EVENT CONSTRUCTION
    # ======================================================================

    def _phase_from_derivative(self, planet: str, target: str, aspect: str, t: datetime) -> str:
        try:
            orb = abs(self._aspect_function(t, planet, target, aspect))
            if orb <= self.config.exact_tolerance_deg:
                return "exact"
        except Exception:
            pass

        dt = timedelta(minutes=5)
        try:
            orb_before = abs(self._aspect_function(t - dt, planet, target, aspect))
            orb_after = abs(self._aspect_function(t + dt, planet, target, aspect))
            if orb_before > orb_after:
                return "applying"
            elif orb_before < orb_after:
                return "separating"
            else:
                return "exact"
        except Exception:
            return "unknown"

    def _determine_exact_status(self, event: TransitEvent, period: ForecastPeriod) -> None:
        start = event.start_utc if event.start_utc is not None else period.start_utc
        end = event.end_utc if event.end_utc is not None else period.end_utc

        t_min = self._refine_exact_hit(event.transit_body, event.natal_target, event.aspect, start, end)
        if t_min is None:
            t_min = start + (end - start) / 2
        orb_min = abs(self._aspect_function(t_min, event.transit_body, event.natal_target, event.aspect))

        boundary_epsilon = timedelta(seconds=self.config.boundary_tolerance_seconds)
        start_diff = abs((t_min - period.start_utc).total_seconds())
        end_diff = abs((t_min - period.end_utc).total_seconds())

        if start_diff < boundary_epsilon.total_seconds():
            event.boundary_type = "near_start"
            event.boundary_limited = True
        elif end_diff < boundary_epsilon.total_seconds():
            event.boundary_type = "near_end"
            event.boundary_limited = True
        else:
            event.boundary_type = "inside"
            event.boundary_limited = False

        if event.boundary_limited:
            self.stats["boundary_candidates"] += 1

        if orb_min <= self.config.exact_tolerance_deg:
            event.exact_hit = True
            event.exact_utc = t_min
            event.orb_at_exact = orb_min
            self.stats["exact_hits"] += 1
        else:
            event.exact_hit = False
            event.exact_utc = None
            event.orb_at_exact = orb_min
            self.stats["near_hits"] += 1

        event.nearest_utc = t_min
        event.nearest_orb = orb_min
        event.phase = self._phase_from_derivative(event.transit_body, event.natal_target, event.aspect, t_min)

    def _build_event(
        self,
        planet: str,
        target: str,
        aspect: str,
        exact: datetime,
        start: Optional[datetime],
        end: Optional[datetime],
    ) -> Optional[TransitEvent]:
        subject = self._snapshot(exact)
        transit = self._extract_transit_planet(subject, planet)
        natal = self._natal_points.get(target)
        if transit is None or natal is None:
            return None
        natal_longitude = to_float(natal.get("abs_pos"))
        if natal_longitude is None:
            return None

        orb = abs(self._aspect_function(exact, planet, target, aspect))
        phase = self._phase_from_derivative(planet, target, aspect, exact)
        theme = THEME_FOR_TARGET.get(target, "general")

        event = TransitEvent(
            transit_body=planet,
            natal_target=target,
            aspect=aspect,
            aspect_angle=MAJOR_ASPECT_ANGLES[aspect],
            start_utc=start,
            exact_utc=None,
            end_utc=end,
            orb_at_exact=orb,
            phase=phase,
            transit_longitude=transit.longitude,
            natal_longitude=natal_longitude,
            transit_house=transit.house,
            natal_house=natal.get("house"),
            is_retrograde=transit.retrograde,
            transit_speed=transit.speed,
            theme=theme,
            source_type="transit",
            target_type="natal",
        )
        return event

    # ======================================================================
    # SCORING & CLASSIFICATION
    # ======================================================================

    @staticmethod
    def _orb_strength(orb: float) -> float:
        if orb <= 0.1:
            return 1.0
        if orb <= 0.5:
            return 0.9
        if orb <= 1.0:
            return 0.75
        if orb <= 2.0:
            return 0.55
        if orb <= 3.0:
            return 0.35
        return 0.0

    def _score(self, event: TransitEvent, period_type: str) -> float:
        planet_weights = PERIOD_PLANET_WEIGHTS.get(period_type, BASE_PLANET_WEIGHT)
        planet_weight = planet_weights.get(event.transit_body, 0.0)
        target_weight = TARGET_WEIGHT.get(event.natal_target, 0.0) * 0.35
        aspect_weight = ASPECT_WEIGHT.get(event.aspect, 0.0) * 3.0
        orb_factor = self._orb_strength(event.orb_at_exact) * 5.0

        score = planet_weight + target_weight + aspect_weight + orb_factor

        if event.natal_target in ANGLE_TARGETS:
            score += self.config.angle_bonus
        if event.natal_target in PERSONAL_TARGETS:
            score += self.config.personal_target_bonus
        if event.phase == "applying":
            score += self.config.applying_bonus
        elif event.phase == "separating":
            score += self.config.separating_bonus
        if event.is_retrograde:
            score += self.config.retrograde_bonus

        return round(score, 3)

    def _classify_event(self, event: TransitEvent, period_type: str) -> None:
        event.score = self._score(event, period_type)

        if event.orb_at_exact > self.config.foreground_max_orb:
            event.activity = "BACKGROUND"
            event.reason = "orb_too_wide"
            return

        planet = event.transit_body
        target = event.natal_target
        orb = event.orb_at_exact

        if planet in SLOW_PLANETS and target in ANGLE_TARGETS:
            event.activity = "FOREGROUND"
            event.reason = "slow_planet_to_angle"
            return
        if planet in SLOW_PLANETS and orb <= self.config.slow_planet_tight_orb:
            event.activity = "FOREGROUND"
            event.reason = "slow_planet_tight_orb"
            return
        if orb <= self.config.very_tight_orb:
            event.activity = "FOREGROUND"
            event.reason = "very_tight_orb"
            return
        if target in ANGLE_TARGETS and event.phase == "applying" and orb <= self.config.angle_applying_orb:
            event.activity = "FOREGROUND"
            event.reason = "angle_applying"
            return
        if event.phase == "applying" and orb <= self.config.fast_planet_tight_orb:
            event.activity = "FOREGROUND"
            event.reason = "applying_tight"
            return

        event.activity = "BACKGROUND"
        event.reason = "ordinary_background"

    # ======================================================================
    # FILTERING FOR FINAL SELECTION (PER PERIOD)
    # ======================================================================

    def _select_final_events(self, events: List[TransitEvent], period_type: str) -> List[TransitEvent]:
        if period_type == "day":
            return self._filter_day_events(events)
        elif period_type == "month":
            return self._filter_month_events(events)
        elif period_type == "year":
            return self._filter_year_events(events)
        else:
            return events

    def _filter_day_events(self, events: List[TransitEvent]) -> List[TransitEvent]:
        selected = []
        exact_limit = self.config.day_exact_orb_limit
        selected.extend([e for e in events if e.orb_at_exact <= exact_limit])

        moon_limit = self.config.day_moon_orb_limit
        moon_aspects = [e for e in events if e.transit_body == "moon" and e.orb_at_exact <= moon_limit]
        selected.extend(moon_aspects)

        fast_limit = self.config.day_fast_orb_limit
        fast_except_moon = [p for p in FAST_PLANETS if p != "moon"]
        fast_aspects = [e for e in events if e.transit_body in fast_except_moon and e.orb_at_exact <= fast_limit]
        selected.extend(fast_aspects)

        slow_limit = self.config.day_slow_orb_limit
        score_threshold = self.config.day_score_threshold
        slow_aspects = [
            e for e in events
            if e.transit_body in SLOW_PLANETS
            and e.orb_at_exact <= slow_limit
            and e.score > score_threshold
        ]
        selected.extend(slow_aspects)

        unique = {}
        for e in selected:
            key = e.semantic_key
            if key not in unique or e.score > unique[key].score:
                unique[key] = e
        selected = list(unique.values())

        selected.sort(key=lambda e: e.score, reverse=True)
        limit = self.config.max_final_events_day
        return selected[:limit]

    def _filter_month_events(self, events: List[TransitEvent]) -> List[TransitEvent]:
        selected = []
        exact_limit = self.config.month_exact_orb_limit
        selected.extend([e for e in events if e.orb_at_exact <= exact_limit])

        fast_limit = self.config.month_fast_orb_limit
        fast_except_moon = [p for p in FAST_PLANETS if p != "moon"]
        fast_aspects = [e for e in events if e.transit_body in fast_except_moon and e.orb_at_exact <= fast_limit]
        selected.extend(fast_aspects)

        slow_limit = self.config.month_slow_orb_limit
        score_threshold = self.config.month_score_threshold
        slow_aspects = [
            e for e in events
            if e.transit_body in SLOW_PLANETS
            and e.orb_at_exact <= slow_limit
            and e.score > score_threshold
        ]
        selected.extend(slow_aspects)

        unique = {}
        for e in selected:
            key = e.semantic_key
            if key not in unique or e.score > unique[key].score:
                unique[key] = e
        selected = list(unique.values())

        selected.sort(key=lambda e: e.score, reverse=True)
        limit = self.config.max_final_events_month
        return selected[:limit]

    def _filter_year_events(self, events: List[TransitEvent]) -> List[TransitEvent]:
        selected = []
        exact_limit = self.config.year_exact_orb_limit
        selected.extend([e for e in events if e.orb_at_exact <= exact_limit])

        fast_limit = self.config.year_fast_orb_limit
        fast_except_moon = [p for p in FAST_PLANETS if p != "moon"]
        fast_aspects = [e for e in events if e.transit_body in fast_except_moon and e.orb_at_exact <= fast_limit]
        selected.extend(fast_aspects)

        slow_limit = self.config.year_slow_orb_limit
        score_threshold = self.config.year_score_threshold
        slow_aspects = [
            e for e in events
            if e.transit_body in SLOW_PLANETS
            and e.orb_at_exact <= slow_limit
            and e.score > score_threshold
        ]
        selected.extend(slow_aspects)

        unique = {}
        for e in selected:
            key = e.semantic_key
            if key not in unique or e.score > unique[key].score:
                unique[key] = e
        selected = list(unique.values())

        selected.sort(key=lambda e: e.score, reverse=True)
        limit = self.config.max_final_events_year
        return selected[:limit]

    # ======================================================================
    # EXACT TRANSIT PIPELINE
    # ======================================================================

    def _resolve_candidate(
        self,
        planet: str,
        target: str,
        aspect: str,
        start: datetime,
        end: datetime,
        period: ForecastPeriod,
    ) -> Optional[TransitEvent]:
        exact = self._refine_exact_hit(planet, target, aspect, start, end)
        if exact is None:
            return None

        # Для года пропускаем поиск границ
        if period.period_type == "year":
            event = self._build_event(
                planet=planet,
                target=target,
                aspect=aspect,
                exact=exact,
                start=None,
                end=None,
            )
        else:
            boundary_start = self._find_boundary(planet, target, aspect, exact, -1, period)
            boundary_end = self._find_boundary(planet, target, aspect, exact, +1, period)
            event = self._build_event(
                planet=planet,
                target=target,
                aspect=aspect,
                exact=exact,
                start=boundary_start,
                end=boundary_end,
            )

        if event is not None:
            self._determine_exact_status(event, period)
        return event

    # ======================================================================
    # RETROGRADE
    # ======================================================================

    def _planet_speed(self, planet: str, timestamp: datetime) -> float:
        subject = self._snapshot(timestamp)
        transit = self._extract_transit_planet(subject, planet)
        if transit is None:
            return 0.0
        return transit.speed

    def _detect_station_candidates(
        self,
        planet: str,
        period: ForecastPeriod,
    ) -> List[Tuple[datetime, datetime]]:
        step = timedelta(hours=self.config.retrograde_coarse_hours)
        cursor = period.start_utc
        previous_time: Optional[datetime] = None
        previous_speed: Optional[float] = None
        result = []

        while cursor <= period.end_utc:
            speed = self._planet_speed(planet, cursor)
            if previous_speed is not None and previous_time is not None:
                if previous_speed * speed <= 0:
                    result.append((previous_time, cursor))
            previous_time = cursor
            previous_speed = speed
            cursor += step

        self.stats["retrograde_candidates"] += len(result)
        return result

    def _refine_station_mid(
        self,
        planet: str,
        start: datetime,
        end: datetime,
    ) -> Tuple[datetime, datetime]:
        step = timedelta(hours=self.config.retrograde_mid_hours)
        cursor = start
        best_time = start
        best_abs_speed = float("inf")
        while cursor <= end:
            speed = abs(self._planet_speed(planet, cursor))
            if speed < best_abs_speed:
                best_abs_speed = speed
                best_time = cursor
            cursor += step
        radius = timedelta(hours=self.config.retrograde_refine_hours)
        return max(start, best_time - radius), min(end, best_time + radius)

    def _refine_station_final(
        self,
        planet: str,
        start: datetime,
        end: datetime,
    ) -> datetime:
        tolerance = timedelta(seconds=self.config.retrograde_final_seconds)
        left, right = start, end
        while right - left > tolerance:
            mid = midpoint(left, right)
            left_probe = midpoint(left, mid)
            right_probe = midpoint(mid, right)
            left_speed = abs(self._planet_speed(planet, left_probe))
            right_speed = abs(self._planet_speed(planet, right_probe))
            if left_speed < right_speed:
                right = mid
            else:
                left = mid
        return midpoint(left, right)

    def _detect_retrograde_for_planet(
        self,
        planet: str,
        period: ForecastPeriod,
    ) -> List[RetrogradeWindow]:
        cache_key = (
            period.period_type,
            datetime_key(period.start_utc),
            datetime_key(period.end_utc),
        )
        existing = self._retrograde_cache.get((planet, *cache_key))
        if existing is not None:
            return [existing]

        candidates = self._detect_station_candidates(planet, period)
        windows: List[RetrogradeWindow] = []

        for coarse_start, coarse_end in candidates:
            mid_start, mid_end = self._refine_station_mid(planet, coarse_start, coarse_end)
            station = self._refine_station_final(planet, mid_start, mid_end)
            before = station - timedelta(hours=6)
            after = station + timedelta(hours=6)
            before_speed = self._planet_speed(planet, before)
            station_speed = self._planet_speed(planet, station)
            after_speed = self._planet_speed(planet, after)
            retrograde_after = before_speed >= 0 and after_speed < 0
            retrograde_before = before_speed < 0 and after_speed >= 0
            if not (retrograde_after or retrograde_before):
                continue

            window_radius = timedelta(hours=self.config.retrograde_refine_hours)
            window = RetrogradeWindow(
                planet=planet,
                station_start_utc=max(period.start_utc, station - window_radius),
                station_exact_utc=station,
                station_end_utc=min(period.end_utc, station + window_radius),
                before_speed=before_speed,
                station_speed=station_speed,
                after_speed=after_speed,
                retrograde_after=retrograde_after,
            )
            windows.append(window)
            self.stats["retrograde_refinements"] += 1

        self.retrograde_windows[planet].extend(windows)
        return windows

    def _detect_retrogrades(self, period: ForecastPeriod, planets: Sequence[str]) -> None:
        for planet in planets:
            if planet == "moon":
                continue
            windows = self._detect_retrograde_for_planet(planet, period)
            if windows:
                logger.info("[RETROGRADE] %s: %d station(s) found", planet, len(windows))
            else:
                logger.debug("[RETROGRADE] %s: no stations", planet)

    def _get_retrograde_planets_at(self, timestamp: datetime) -> List[str]:
        retro_planets = []
        for planet in TRANSIT_PLANETS:
            speed = self._planet_speed(planet, timestamp)
            if speed < 0:
                retro_planets.append(planet)
        return retro_planets

    def _get_retrograde_state(self, period: ForecastPeriod) -> Dict[str, Any]:
        start_retro = self._get_retrograde_planets_at(period.start_utc)
        end_retro = self._get_retrograde_planets_at(period.end_utc)
        return {
            "start": start_retro,
            "end": end_retro,
        }

    # ======================================================================
    # DEDUPLICATION
    # ======================================================================

    def _deduplicate_events(self, events: Sequence[TransitEvent]) -> List[TransitEvent]:
        logger.info("[DEDUP] Input events: %d", len(events))
        grouped: Dict[Tuple[str, str, str], List[TransitEvent]] = defaultdict(list)
        for event in events:
            grouped[event.semantic_key].append(event)

        result: List[TransitEvent] = []
        for _, group in grouped.items():
            group.sort(key=lambda e: e.exact_utc or datetime.max.replace(tzinfo=timezone.utc))
            unique: List[TransitEvent] = []
            for event in group:
                if not unique:
                    unique.append(event)
                    continue
                previous = unique[-1]
                if (
                        event.exact_utc
                        and previous.exact_utc
                        and abs((event.exact_utc - previous.exact_utc).total_seconds())
                        <= self.config.exact_tolerance_seconds
                ):
                    if event.score > previous.score:
                        unique[-1] = event
                else:
                    unique.append(event)
            for index, event in enumerate(unique, start=1):
                event.hit_index = index
            result.extend(unique)

        logger.info("[DEDUP] Output events: %d (removed %d duplicates)", len(result), len(events) - len(result))
        return result

    # ======================================================================
    # RETROGRADE ANNOTATION
    # ======================================================================

    def _is_retrograde_at(self, planet: str, timestamp: datetime) -> bool:
        subject = self._snapshot(timestamp)
        transit = self._extract_transit_planet(subject, planet)
        if transit is None:
            return False
        return transit.retrograde

    def _annotate_retrograde(self, events: Sequence[TransitEvent]) -> None:
        for event in events:
            if event.exact_utc is None:
                continue
            event.is_retrograde = self._is_retrograde_at(event.transit_body, event.exact_utc)

    # ======================================================================
    # THEMATIC AGGREGATION
    # ======================================================================

    def _aggregate_themes(self, events: Sequence[TransitEvent], period_type: str) -> List[TransitEpisode]:
        logger.info("[AGGREGATE] Input events: %d", len(events))
        grouped: Dict[Tuple[str, str, str], List[TransitEvent]] = defaultdict(list)
        for event in events:
            grouped[event.semantic_key].append(event)

        episodes: List[TransitEpisode] = []
        for key, group in grouped.items():
            group = sorted(group, key=lambda e: e.exact_utc or datetime.max.replace(tzinfo=timezone.utc))
            first = group[0]

            exact_hits = [e.nearest_utc for e in group if e.exact_hit and e.nearest_utc is not None]
            exact_hits_count = len(exact_hits)

            nearest_approaches = [(e.nearest_utc, e.nearest_orb) for e in group if e.nearest_utc is not None]

            min_orb = min(e.nearest_orb for e in group if e.nearest_orb < 999.0) if nearest_approaches else 0.0
            boundary_limited = any(e.boundary_limited for e in group)
            boundary_types = set(e.boundary_type for e in group)
            boundary_type = boundary_types.pop() if len(boundary_types) == 1 else "mixed"

            phase = first.phase
            max_score = max(e.score for e in group)
            hit_count = len(group)
            retrograde_hits = sum(1 for e in group if e.is_retrograde)

            episode = TransitEpisode(
                transit_body=first.transit_body,
                natal_target=first.natal_target,
                aspect=first.aspect,
                theme=first.theme,
                first_start_utc=min((e.start_utc for e in group if e.start_utc is not None), default=None),
                last_end_utc=max((e.end_utc for e in group if e.end_utc is not None), default=None),
                exact_hits=exact_hits,
                nearest_approaches=nearest_approaches,
                exact_hits_count=exact_hits_count,
                max_score=max_score,
                hit_count=hit_count,
                retrograde_hits=retrograde_hits,
                phase=phase,
                min_orb=min_orb,
                boundary_limited=boundary_limited,
                boundary_type=boundary_type,
                source_type="transit",
                target_type="natal",
            )
            if episode.hit_count > 1:
                episode.max_score += self.config.repeated_hit_bonus * min(episode.hit_count - 1, 3)
            episodes.append(episode)

        if period_type == "month":
            moon_episodes = [e for e in episodes if e.transit_body == "moon"]
            other_episodes = [e for e in episodes if e.transit_body != "moon"]

            moon_by_key: Dict[Tuple[str, str], List[TransitEpisode]] = defaultdict(list)
            for e in moon_episodes:
                key = (e.natal_target, e.aspect)
                moon_by_key[key].append(e)

            kept_moon = []
            suppressed_count = 0
            for key, episodes_list in moon_by_key.items():
                episodes_list.sort(key=lambda e: e.max_score, reverse=True)
                kept = episodes_list[:self.config.month_max_moon_hits_per_key]
                suppressed = episodes_list[self.config.month_max_moon_hits_per_key:]
                kept_moon.extend(kept)
                suppressed_count += len(suppressed)

            self.stats["month_moon_hits_suppressed"] = suppressed_count
            episodes = other_episodes + kept_moon

        logger.info("[AGGREGATE] Episodes created: %d", len(episodes))
        return episodes

    # ======================================================================
    # RANKING
    # ======================================================================

    def _episode_score(self, episode: TransitEpisode) -> float:
        return round(episode.max_score, 3)

    def _rank_episodes(self, episodes: Sequence[TransitEpisode]) -> List[TransitEpisode]:
        logger.info("[RANK] Ranking %d episodes...", len(episodes))
        ranked = sorted(
            episodes,
            key=lambda e: (self._episode_score(e), e.hit_count, e.retrograde_hits),
            reverse=True,
        )
        if ranked:
            logger.info("[RANK] Top episode: %s (score=%.2f, hits=%d)",
                        ranked[0].display_name,
                        self._episode_score(ranked[0]),
                        ranked[0].hit_count)
        return ranked

    # ======================================================================
    # PLANET CATEGORY
    # ======================================================================

    def _planet_category(self, planet: str) -> str:
        if planet == "moon":
            return "очень быстрая (часы)"
        if planet in ("sun", "mercury", "venus", "mars"):
            return "быстрая (дни)"
        if planet in ("jupiter", "saturn", "uranus", "neptune", "pluto"):
            return "медленная (недели/месяцы)"
        return "средняя"

    # ======================================================================
    # FINAL PIPELINE
    # ======================================================================

    def calculate(
            self,
            period: ForecastPeriod,
            max_display: Optional[int] = None,
    ) -> List[TransitEpisode]:
        self._validate_period(period)

        self.events.clear()
        self.episodes.clear()
        self.retrograde_windows.clear()

        self.stats.update({
            "snapshot_requests": 0,
            "snapshot_created": 0,
            "snapshot_cache_hits": 0,
            "candidate_windows": 0,
            "exact_hits": 0,
            "near_hits": 0,
            "boundary_candidates": 0,
            "false_exact_rejected": 0,
            "retrograde_candidates": 0,
            "retrograde_refinements": 0,
            "month_raw_candidate_windows": 0,
            "month_merged_candidate_windows": 0,
            "month_pre_ranked_candidates": 0,
            "month_refinement_candidates": 0,
            "month_candidates_skipped_by_budget": 0,
            "month_moon_hits_suppressed": 0,
            "year_raw_candidate_windows": 0,
            "year_merged_candidate_windows": 0,
            "year_pre_ranked_candidates": 0,
            "year_refinement_candidates": 0,
            "year_candidates_skipped_by_budget": 0,
        })

        logger.info("=== TRANSIT ENGINE START ===")
        logger.info("period=%s start=%s end=%s",
                    period.period_type,
                    datetime_key(period.start_utc),
                    datetime_key(period.end_utc))

        planets = self._planets_for_period(period.period_type)
        logger.info("[PLANETS] %s", ",".join(planets))

        logger.info("[STEP 1] Detecting candidate windows...")
        candidates = self._detect_candidate_windows(period, planets)
        logger.info("[STEP 1] Candidate windows found: %d", len(candidates))

        # PRE-RANKING ДЛЯ МЕСЯЦА
        if period.period_type == "month" and len(candidates) > self.config.month_max_refinement_candidates:
            scored = []
            for cand in candidates:
                score = self._candidate_pre_score(cand, period.period_type)
                scored.append((cand, score))
            scored.sort(key=lambda x: x[1], reverse=True)

            budget = self.config.month_max_refinement_candidates
            top_candidates = [cand for cand, _ in scored[:budget]]
            skipped = len(candidates) - len(top_candidates)

            self.stats["month_pre_ranked_candidates"] = len(scored)
            self.stats["month_refinement_candidates"] = len(top_candidates)
            self.stats["month_candidates_skipped_by_budget"] = skipped

            logger.info("[STEP 1b] Month pre-ranking: %d candidates, selected %d, skipped %d",
                        len(scored), len(top_candidates), skipped)
            candidates = top_candidates

        # PRE-RANKING ДЛЯ ГОДА
        if period.period_type == "year" and len(candidates) > self.config.year_max_refinement_candidates:
            scored = []
            for cand in candidates:
                score = self._candidate_pre_score(cand, period.period_type)
                scored.append((cand, score))
            scored.sort(key=lambda x: x[1], reverse=True)

            budget = self.config.year_max_refinement_candidates
            top_candidates = [cand for cand, _ in scored[:budget]]
            skipped = len(candidates) - len(top_candidates)

            self.stats["year_pre_ranked_candidates"] = len(scored)
            self.stats["year_refinement_candidates"] = len(top_candidates)
            self.stats["year_candidates_skipped_by_budget"] = skipped

            logger.info("[STEP 1b] Year pre-ranking: %d candidates, selected %d, skipped %d",
                        len(scored), len(top_candidates), skipped)
            candidates = top_candidates

        # STEP 2
        logger.info("[STEP 2] Resolving exact hits...")
        events: List[TransitEvent] = []
        resolved_count = 0
        for planet, target, aspect, start, end in candidates:
            if len(events) >= self.config.max_events_per_period:
                logger.warning("[STEP 2] Event safety limit reached.")
                break
            event = self._resolve_candidate(planet, target, aspect, start, end, period)
            if event is None:
                continue
            if event.exact_utc is not None:
                if not (period.start_utc <= event.exact_utc <= period.end_utc):
                    continue
            events.append(event)
            resolved_count += 1

        logger.info("[STEP 2] Exact hits resolved: %d (before dedup)", resolved_count)

        events = self._deduplicate_events(events)
        real_exact = sum(1 for e in events if e.exact_hit)
        self.stats["exact_hits"] = real_exact
        self.stats["false_exact_rejected"] = len(events) - real_exact
        logger.info("[STEP 2] After dedup: %d events, exact hits: %d", len(events), real_exact)

        # STEP 3
        logger.info("[STEP 3] Detecting retrograde stations...")
        self._detect_retrogrades(period, planets)
        retrograde_count = sum(len(windows) for windows in self.retrograde_windows.values())
        logger.info("[STEP 3] Retrograde stations found: %d", retrograde_count)

        self._annotate_retrograde(events)

        # STEP 4
        logger.info("[STEP 4] Classifying events with period-specific weights...")
        for event in events:
            self._classify_event(event, period.period_type)
        logger.info("[STEP 4] Classification complete.")

        self.events = events

        # STEP 5
        logger.info("[STEP 5] Filtering events for final selection...")
        filtered_events = self._select_final_events(events, period.period_type)
        logger.info("[STEP 5] Filtered events: %d (from %d)", len(filtered_events), len(events))

        # STEP 6
        logger.info("[STEP 6] Aggregating themes from filtered events...")
        episodes = self._aggregate_themes(filtered_events, period.period_type)
        logger.info("[STEP 6] Thematic episodes created: %d", len(episodes))

        logger.info("[STEP 7] Ranking episodes...")
        ranked = self._rank_episodes(episodes)

        if max_display is not None:
            limit = max_display
        else:
            limit = self.config.max_final_events(period.period_type)

        final = ranked[:limit]
        logger.info("[STEP 7] Final episodes selected: %d (limit=%d)", len(final), limit)

        logger.info(
            "=== TRANSIT ENGINE END ==="
            " snapshots_created=%d snapshot_requests=%d cache_hits=%d candidates=%d exact_hits=%d episodes=%d final=%d",
            self.stats["snapshot_created"],
            self.stats["snapshot_requests"],
            self.stats["snapshot_cache_hits"],
            self.stats["candidate_windows"],
            self.stats["exact_hits"],
            len(episodes),
            len(final),
        )

        return final

    # ======================================================================
    # BUILD CONTEXT (prompt)
    # ======================================================================

    def build_context(
            self,
            period_type: str,
            period_start_utc: datetime,
            period_end_utc: datetime,
            max_display: int = 12,
    ) -> str:
        logger.info("=== BUILD CONTEXT START ===")
        logger.info("period_type=%s start=%s end=%s max_display=%d",
                    period_type,
                    period_start_utc.isoformat(),
                    period_end_utc.isoformat(),
                    max_display)

        period = ForecastPeriod(
            period_type=period_type,
            start_utc=ensure_utc(period_start_utc),
            end_utc=ensure_utc(period_end_utc),
        )

        episodes = self.calculate(period, max_display=max_display)
        prompt = self._build_prompt(period, episodes)

        if self.emulation_mode:
            logger.info("Emulation mode: returning prompt without Gemini")
            return f"🔍 РЕЖИМ ЭМУЛЯЦИИ (промпт не отправлен в нейросеть):\n\n{prompt}"

        if self.gemini_service is None:
            logger.warning("Gemini service not available, returning prompt only")
            return prompt

        logger.info("Sending prompt to Gemini...")
        try:
            response = self.gemini_service.send_raw_prompt(prompt)
            logger.info("Gemini response received")
            return response
        except Exception as e:
            logger.error(f"Error sending to Gemini: {e}", exc_info=True)
            return f"❌ Ошибка при обращении к Gemini: {str(e)}\n\n{prompt}"

    def _build_prompt(
            self,
            period: ForecastPeriod,
            episodes: List[TransitEpisode],
    ) -> str:
        return self.build_horoscope_context(
            period.period_type,
            period.start_utc,
            period.end_utc,
            len(episodes)
        )

    # ======================================================================
    # QA
    # ======================================================================

    def get_stats(self) -> Dict[str, Any]:
        return {
            **self.stats,
            "events": len(self.events),
            "episodes": len(self.episodes),
            "snapshot_cache_size": len(self._snapshot_cache),
        }

    def get_qa_report(self) -> str:
        lines = [
            "=== TRANSIT ENGINE QA ===",
            f"Snapshots created: {self.stats['snapshot_created']}",
            f"Snapshot requests: {self.stats['snapshot_requests']}",
            f"Cache hits: {self.stats['snapshot_cache_hits']}",
            f"Candidate windows: {self.stats['candidate_windows']}",
            f"Exact hits: {self.stats['exact_hits']}",
            f"Near hits: {self.stats['near_hits']}",
            f"Boundary candidates: {self.stats['boundary_candidates']}",
            f"False exact candidates rejected: {self.stats['false_exact_rejected']}",
            f"Retrograde candidates: {self.stats['retrograde_candidates']}",
            f"Retrograde refinements: {self.stats['retrograde_refinements']}",
            f"Events: {len(self.events)}",
            f"Episodes: {len(self.episodes)}",
            "",
            "=== EVENTS ===",
        ]

        for event in sorted(
            self.events,
            key=lambda e: e.exact_utc or datetime.max.replace(tzinfo=timezone.utc),
        ):
            exact = event.exact_utc.isoformat(timespec="seconds") if event.exact_utc else "N/A"
            lines.append(
                f"{event.display_name} | "
                f"exact={exact} | "
                f"orb={event.orb_at_exact:.4f} | "
                f"phase={event.phase} | "
                f"retrograde={event.is_retrograde} | "
                f"score={event.score:.3f}"
            )

        lines.append("")
        lines.append("=== RETROGRADE WINDOWS ===")
        for planet, windows in sorted(self.retrograde_windows.items()):
            for window in windows:
                lines.append(
                    f"{planet}: "
                    f"{window.station_exact_utc.isoformat(timespec='seconds')} | "
                    f"before={window.before_speed:.8f} | "
                    f"station={window.station_speed:.8f} | "
                    f"after={window.after_speed:.8f} | "
                    f"retrograde_after={window.retrograde_after}"
                )

        return "\n".join(lines)

    # ======================================================================
    # HOROSCOPE CONTEXT BUILDER
    # ======================================================================

    def build_horoscope_context(
            self,
            period_type: str,
            period_start_utc: datetime,
            period_end_utc: datetime,
            max_display: int = 12,
    ) -> str:
        period = ForecastPeriod(
            period_type=period_type,
            start_utc=ensure_utc(period_start_utc),
            end_utc=ensure_utc(period_end_utc),
        )

        episodes = self.calculate(period, max_display=max_display)
        return self._build_context_string(period, episodes)

    def _build_context_string(
            self,
            period: ForecastPeriod,
            episodes: List[TransitEpisode],
    ) -> str:
        lines = []

        # ----- ПАРАМЕТРЫ РАСЧЁТА -----
        lines.append("### Параметры расчёта")
        lines.append("")
        period_name = {
            "day": "сутки",
            "month": "месяц",
            "year": "год"
        }.get(period.period_type, period.period_type)
        lines.append(f"Тип: Транзитный прогноз")
        lines.append(f"Период: {period_name}")
        lines.append(f"Начало периода UTC: {period.start_utc.isoformat()}")
        lines.append(f"Конец периода UTC: {period.end_utc.isoformat()}")
        lines.append("Зодиак: Tropical")
        lines.append("Система домов: Placidus")
        lines.append("Перспектива: Geocentric")
        lines.append("")

        # ----- ДАННЫЕ РОЖДЕНИЯ (UTC) -----
        user = self.user_data
        birth_date_local = user.get('birth_date', 'не указана')
        birth_time_local = user.get('birth_time', 'не указано')
        birth_place = user.get('birth_place', '')
        lat = user.get('birth_lat')
        lng = user.get('birth_lng')
        utc_str = user.get('birth_timezone')

        # Попытка получить UTC из БД
        if utc_str:
            try:
                utc_dt = datetime.fromisoformat(utc_str.replace('Z', '+00:00'))
                birth_date_utc = utc_dt.strftime('%d.%m.%Y')
                birth_time_utc = utc_dt.strftime('%H:%M')
            except (ValueError, TypeError):
                birth_date_utc = birth_date_local
                birth_time_utc = birth_time_local
        else:
            # Если UTC нет в БД — вычисляем на лету (как в астрологии)
            birth_date_utc = birth_date_local
            birth_time_utc = birth_time_local
            if birth_date_local != 'не указана' and birth_time_local != 'не указано' and birth_place:
                try:
                    from bot.utils.place_resolver import PlaceResolver
                    from datetime import datetime as dt
                    import zoneinfo
                    import asyncio

                    resolver = PlaceResolver()
                    parts = [p.strip() for p in birth_place.split(',') if p.strip()]
                    city = parts[0] if parts else "Москва"
                    country = parts[1] if len(parts) > 1 else "RU"
                    lat_calc, lng_calc, iana_tz = resolver.resolve(city, country)

                    local_dt = dt.strptime(f"{birth_date_local} {birth_time_local}", "%d.%m.%Y %H:%M")
                    tz = zoneinfo.ZoneInfo(iana_tz)
                    local_with_tz = local_dt.replace(tzinfo=tz)
                    utc_dt = local_with_tz.astimezone(timezone.utc)

                    birth_date_utc = utc_dt.strftime('%d.%m.%Y')
                    birth_time_utc = utc_dt.strftime('%H:%M')

                    # Сохраняем координаты и UTC в БД (фоново)
                    if self.telegram_id:
                        asyncio.create_task(
                            save_user_coords(
                                self.telegram_id,
                                lat_calc,
                                lng_calc,
                                utc_dt.isoformat()
                            )
                        )
                        # Обновляем локальные переменные для вывода координат
                        lat = lat_calc
                        lng = lng_calc
                except Exception as e:
                    logger.warning(f"Не удалось вычислить UTC для гороскопа: {e}")
                    # остаются локальные дата/время

        # Координаты для вывода
        if lat is not None and lng is not None:
            coords = f"{lat:.4f}° N, {lng:.4f}° E"
        else:
            coords = "не указаны"

        lines.append("### Данные рождения человека")
        lines.append("")
        lines.append(f"Дата рождения: {birth_date_utc}")
        lines.append(f"Время рождения: {birth_time_utc}")
        lines.append(f"Координаты рождения: {coords}")
        lines.append("Часовой пояс: UTC")
        lines.append("")

        # ----- НАТАЛЬНЫЕ ТОЧКИ -----
        lines.append("### Натальные точки")
        for target, data in sorted(self._natal_points.items()):
            longitude = to_float(data.get("abs_pos"))
            if longitude is None:
                continue
            sign = data.get("sign", "")
            position = to_float(data.get("position"), 0.0) or 0.0
            house = data.get("house")
            lines.append(
                f"{TARGET_RU.get(target, target)}: "
                f"{sign} {position:.2f}°"
                + (f", дом {house}" if house else "")
            )
        lines.append("")

        # ----- РЕТРОГРАДНЫЕ ПЛАНЕТЫ -----
        retro_state = self._get_retrograde_state(period)
        lines.append("### Ретроградные планеты")
        if retro_state["start"] or retro_state["end"]:
            start_names = [PLANET_RU.get(p, p) for p in retro_state["start"]]
            end_names = [PLANET_RU.get(p, p) for p in retro_state["end"]]
            lines.append(f"На начало периода: {', '.join(start_names) if start_names else 'нет'}")
            lines.append(f"На конец периода: {', '.join(end_names) if end_names else 'нет'}")
        else:
            lines.append("Нет ретроградных планет в течение периода.")
        lines.append("")

        # ----- ГЛАВНЫЕ ТРАНЗИТНЫЕ ТЕМЫ -----
        lines.append("### Главные транзитные темы")
        if not episodes:
            lines.append("Нет транзитов, прошедших порог значимости.")
        else:
            for index, episode in enumerate(episodes, start=1):
                source_label = f"{PLANET_RU.get(episode.transit_body, episode.transit_body)} ({episode.source_type})"
                target_label = f"{TARGET_RU.get(episode.natal_target, episode.natal_target)} ({episode.target_type})"
                aspect_label = ASPECT_RU.get(episode.aspect, episode.aspect)
                planet_category = self._planet_category(episode.transit_body)

                lines.append(f"{index}. {source_label} — {aspect_label} — {target_label}")
                lines.append(f"   Тема: {episode.theme}")

                if episode.exact_hits_count > 0:
                    lines.append(f"   Количество точных проходов: {episode.exact_hits_count}")
                else:
                    lines.append("   Точных проходов в периоде нет")

                if episode.exact_hits:
                    exact_dt = episode.exact_hits[0]
                    exact_str = exact_dt.strftime("%d.%m.%Y %H:%M") + " UTC"
                    lines.append(f"   Точное время пика: {exact_str}")
                    if len(episode.exact_hits) > 1:
                        all_exact = ", ".join(dt.strftime("%d.%m %H:%M") for dt in episode.exact_hits)
                        lines.append(f"   Все пики: {all_exact} UTC")
                else:
                    if episode.nearest_approaches:
                        nearest_time, nearest_orb = episode.nearest_approaches[0]
                        nearest_str = nearest_time.strftime("%d.%m.%Y %H:%M") + " UTC"
                        boundary_desc = {
                            "inside": "",
                            "near_start": " (около начала периода)",
                            "near_end": " (около конца периода)",
                            "mixed": " (на границе)",
                        }.get(episode.boundary_type, "")
                        lines.append(
                            f"   Ближайшая точка в периоде: {nearest_str} (орб {nearest_orb:.2f}°){boundary_desc}")

                phase_ru = PHASE_RU.get(episode.phase, episode.phase)
                lines.append(f"   Фаза: {phase_ru}")
                lines.append(f"   Орб: {episode.min_orb:.2f}°")
                lines.append(f"   Тип планеты: {planet_category}")
                lines.append("")

        # ----- РЕТРОГРАДНЫЕ СТАНЦИИ -----
        lines.append("### Ретроградные станции")
        retrogrades_found = False
        for planet, windows in sorted(self.retrograde_windows.items()):
            for window in windows:
                retrogrades_found = True
                direction = "начало ретроградности" if window.retrograde_after else "окончание ретроградности"
                lines.append(
                    f"- {PLANET_RU.get(planet, planet)}: {direction}; "
                    f"станция {window.station_exact_utc.isoformat(timespec='minutes')} UTC"
                )
        if not retrogrades_found:
            lines.append("Нет.")
        lines.append("")

        return "\n".join(lines)

    # ======================================================================
    # CANDIDATE MERGING
    # ======================================================================

    def _merge_candidate_windows_for_period(
            self,
            candidates: List[Tuple[str, str, str, datetime, datetime]],
            gap_hours: float,
    ) -> List[Tuple[str, str, str, datetime, datetime]]:
        if not candidates:
            return []

        gap = timedelta(hours=gap_hours)
        grouped: Dict[Tuple[str, str, str], List[Tuple[datetime, datetime]]] = defaultdict(list)

        for planet, target, aspect, start, end in candidates:
            grouped[(planet, target, aspect)].append((start, end))

        merged = []
        for key, windows in grouped.items():
            windows.sort()
            current_start, current_end = windows[0]
            for start, end in windows[1:]:
                if start <= current_end + gap:
                    current_end = max(current_end, end)
                else:
                    merged.append((key[0], key[1], key[2], current_start, current_end))
                    current_start, current_end = start, end
            merged.append((key[0], key[1], key[2], current_start, current_end))

        return merged