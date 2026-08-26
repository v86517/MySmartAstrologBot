"""
production_transit_engine.py

Production-grade transit engine for:
    - daily horoscope
    - monthly horoscope
    - yearly horoscope

Architecture:

    AstrologyCalculator
            |
            v
      NatalSnapshot
            |
            v
    TransitWindowEngine
            |
            +--> exact aspect detection
            +--> ingress / egress
            +--> repeated hits
            +--> 3-pass retrograde detection
            |
            v
      TransitEvent
            |
            +--> scoring
            +--> classification
            +--> semantic deduplication
            +--> thematic aggregation
            |
            v
      HoroscopeContext

Internal time:
    UTC only.

External API:
    accepts timezone-aware datetime values.

Kerykeion:
    v5 API / AstrologicalSubjectFactory.
"""

from __future__ import annotations

import hashlib
import logging
import math
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import lru_cache
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from kerykeion import AstrologicalSubjectFactory

from bot.calculators.astrology_calculator import AstrologyCalculator


logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS
# ============================================================================

UTC = timezone.utc

TRANSIT_PLANETS: Tuple[str, ...] = (
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

NATAL_PLANETS: Tuple[str, ...] = (
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
)

ANGLES: Tuple[str, ...] = (
    "ascendant",
    "medium_coeli",
    "descendant",
    "imum_coeli",
)

NATAL_TARGETS = frozenset(NATAL_PLANETS + ANGLES)

MAJOR_ASPECTS: Dict[str, float] = {
    "conjunction": 0.0,
    "sextile": 60.0,
    "square": 90.0,
    "trine": 120.0,
    "opposition": 180.0,
}

ASPECT_ORBS: Dict[str, float] = {
    "conjunction": 5.0,
    "opposition": 5.0,
    "square": 4.0,
    "trine": 4.0,
    "sextile": 3.0,
}

ASPECT_WEIGHT: Dict[str, float] = {
    "conjunction": 1.00,
    "opposition": 0.95,
    "square": 0.90,
    "trine": 0.85,
    "sextile": 0.75,
}

PLANET_WEIGHT: Dict[str, float] = {
    "pluto": 10.0,
    "neptune": 9.0,
    "uranus": 9.0,
    "saturn": 8.0,
    "jupiter": 7.0,
    "mars": 6.0,
    "venus": 5.0,
    "mercury": 5.0,
    "sun": 5.0,
    "moon": 4.0,
}

TARGET_WEIGHT: Dict[str, float] = {
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

SLOW_PLANETS = frozenset(
    {
        "jupiter",
        "saturn",
        "uranus",
        "neptune",
        "pluto",
    }
)

PERSONAL_PLANETS = frozenset(
    {
        "sun",
        "moon",
        "mercury",
        "venus",
        "mars",
    }
)

SOCIAL_PLANETS = frozenset(
    {
        "jupiter",
        "saturn",
    }
)

OUTER_PLANETS = frozenset(
    {
        "uranus",
        "neptune",
        "pluto",
    }
)

FAST_PLANETS = frozenset(
    set(TRANSIT_PLANETS) - set(SLOW_PLANETS)
)

PLANET_RU: Dict[str, str] = {
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

TARGET_RU: Dict[str, str] = {
    **PLANET_RU,
    "ascendant": "ASC",
    "medium_coeli": "MC",
    "descendant": "DSC",
    "imum_coeli": "IC",
}

ASPECT_RU: Dict[str, str] = {
    "conjunction": "соединение",
    "opposition": "оппозиция",
    "square": "квадрат",
    "trine": "трин",
    "sextile": "секстиль",
}

PHASE_RU: Dict[str, str] = {
    "applying": "сходящийся",
    "exact": "точный",
    "separating": "расходящийся",
    "static": "стационарный",
    "unknown": "не определена",
}


# ============================================================================
# ENUMS
# ============================================================================

class PeriodType(str, Enum):
    DAY = "day"
    MONTH = "month"
    YEAR = "year"


class Activity(str, Enum):
    FOREGROUND = "FOREGROUND"
    BACKGROUND = "BACKGROUND"


class Motion(str, Enum):
    DIRECT = "direct"
    RETROGRADE = "retrograde"
    STATIONARY = "stationary"
    UNKNOWN = "unknown"


class EventPhase(str, Enum):
    APPLYING = "applying"
    EXACT = "exact"
    SEPARATING = "separating"
    STATIC = "static"
    UNKNOWN = "unknown"


# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass(frozen=True)
class EngineConfig:
    """
    Centralized production configuration.

    Do not scatter these constants through the engine.
    """

    # -----------------------------
    # Aspect detection
    # -----------------------------

    aspect_orbs: Mapping[str, float] = field(
        default_factory=lambda: dict(ASPECT_ORBS)
    )

    # Exact means numerical minimum <= this value.
    exact_tolerance_deg: float = 0.005

    # Time precision of exact hit.
    exact_tolerance_seconds: float = 30.0

    # Root finding.
    root_tolerance_seconds: float = 30.0

    # -----------------------------
    # Sampling
    # -----------------------------

    day_step_minutes: int = 15
    month_step_hours: int = 3
    year_step_hours: int = 12

    # Minimum sampling for fast planets.
    fast_planet_step_minutes: int = 30

    # Maximum step for outer planets.
    slow_planet_step_hours: int = 24

    # -----------------------------
    # Boundary search
    # -----------------------------

    boundary_search_days_fast: float = 10.0
    boundary_search_days_slow: float = 900.0

    # -----------------------------
    # Retrograde
    # -----------------------------

    retrograde_coarse_hours: int = 24
    retrograde_mid_hours: int = 6
    retrograde_final_seconds: int = 60

    retrograde_speed_epsilon: float = 0.00001

    # -----------------------------
    # Event classification
    # -----------------------------

    foreground_max_orb: float = 3.0
    very_tight_orb: float = 0.5
    slow_planet_tight_orb: float = 1.5
    fast_planet_tight_orb: float = 1.5
    angle_applying_orb: float = 2.5

    # -----------------------------
    # Forecast limits
    # -----------------------------

    max_events_per_period: int = 1000
    max_events_per_theme: int = 10

    max_final_events_day: int = 12
    max_final_events_month: int = 25
    max_final_events_year: int = 40

    # -----------------------------
    # Ranking
    # -----------------------------

    applying_bonus: float = 1.5
    separating_bonus: float = 0.15
    angle_bonus: float = 2.5
    personal_target_bonus: float = 1.0
    retrograde_bonus: float = 0.5
    repeated_hit_bonus: float = 1.25

    # -----------------------------
    # Safety
    # -----------------------------

    max_scan_days: int = 5000

    @property
    def max_final_events(self) -> int:
        return max(
            self.max_final_events_day,
            self.max_final_events_month,
            self.max_final_events_year,
        )


DEFAULT_CONFIG = EngineConfig()


# ============================================================================
# PERIOD
# ============================================================================

@dataclass(frozen=True)
class ForecastPeriod:
    period_type: PeriodType
    start_utc: datetime
    end_utc: datetime

    def __post_init__(self) -> None:
        start = ensure_utc(self.start_utc)
        end = ensure_utc(self.end_utc)

        if end <= start:
            raise ValueError("period_end_utc must be greater than period_start_utc")

        duration = end - start

        if duration.total_seconds() <= 0:
            raise ValueError("Forecast period cannot be empty.")

        if duration.days > DEFAULT_CONFIG.max_scan_days:
            raise ValueError("Forecast period is unreasonably large.")

        object.__setattr__(self, "start_utc", start)
        object.__setattr__(self, "end_utc", end)

    @property
    def duration(self) -> timedelta:
        return self.end_utc - self.start_utc

    @property
    def days(self) -> float:
        return self.duration.total_seconds() / 86400.0

    @classmethod
    def from_values(
        cls,
        period_type: str,
        period_start_utc: datetime,
        period_end_utc: datetime,
    ) -> "ForecastPeriod":
        try:
            ptype = PeriodType(period_type)
        except ValueError as exc:
            raise ValueError(
                f"Unsupported period_type={period_type!r}. "
                f"Expected day/month/year."
            ) from exc

        return cls(
            period_type=ptype,
            start_utc=period_start_utc,
            end_utc=period_end_utc,
        )


# ============================================================================
# BASIC HELPERS
# ============================================================================

def ensure_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("Expected datetime.")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            "Datetime must be timezone-aware. "
            "Naive datetimes are forbidden in production."
        )

    return value.astimezone(UTC)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


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


def to_float(
    value: Any,
    default: Optional[float] = None,
) -> Optional[float]:
    if value is None:
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_longitude(value: float) -> float:
    return value % 360.0


def signed_angular_distance(a: float, b: float) -> float:
    """
    Signed shortest angular difference a-b in [-180, +180).
    """

    return ((a - b + 180.0) % 360.0) - 180.0


def angular_distance(a: float, b: float) -> float:
    return abs(signed_angular_distance(a, b))


def aspect_orb(
    transit_longitude: float,
    natal_longitude: float,
    aspect_angle: float,
) -> float:
    """
    Exact deviation from requested aspect.

    Works correctly for 0° and 180° as well as normal aspects.
    """

    separation = angular_distance(
        transit_longitude,
        natal_longitude,
    )

    return abs(separation - aspect_angle)


def sha1_key(*parts: Any) -> str:
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


# ============================================================================
# KERYKEION DATA ACCESS
# ============================================================================

def get_point(subject: Any, name: str) -> Any:
    """
    Supports:
        subject.sun
        subject.model().sun
        subject.model_dump()
        dict-like models
    """

    name = normalize_name(name)

    if hasattr(subject, name):
        return getattr(subject, name)

    model = getattr(subject, "model", None)

    if callable(model):
        try:
            model = model()
        except Exception:
            model = None

    if model is not None and hasattr(model, name):
        return getattr(model, name)

    if isinstance(model, Mapping):
        return model.get(name)

    return None


def get_point_value(
    subject: Any,
    point_name: str,
    field_name: str,
    default: Any = None,
) -> Any:
    point = get_point(subject, point_name)

    if point is None:
        return default

    if isinstance(point, Mapping):
        return point.get(field_name, default)

    return getattr(point, field_name, default)


def point_longitude(
    subject: Any,
    point_name: str,
) -> Optional[float]:
    value = get_point_value(
        subject,
        point_name,
        "abs_pos",
        None,
    )

    value = to_float(value)

    if value is None:
        return None

    return normalize_longitude(value)


def point_speed(
    subject: Any,
    point_name: str,
) -> Optional[float]:
    return to_float(
        get_point_value(
            subject,
            point_name,
            "speed",
            None,
        )
    )


def point_retrograde(
    subject: Any,
    point_name: str,
) -> Optional[bool]:
    value = get_point_value(
        subject,
        point_name,
        "retrograde",
        None,
    )

    if value is None:
        return None

    return bool(value)


def point_house(
    subject: Any,
    point_name: str,
) -> Any:
    return get_point_value(
        subject,
        point_name,
        "house",
        None,
    )


# ============================================================================
# NATAL SNAPSHOT
# ============================================================================

@dataclass(frozen=True)
class NatalTarget:
    name: str
    longitude: float
    house: Any = None
    is_angle: bool = False

    @property
    def canonical_name(self) -> str:
        return normalize_name(self.name)


@dataclass(frozen=True)
class NatalSnapshot:
    targets: Tuple[NatalTarget, ...]

    @classmethod
    def from_subject(
        cls,
        subject: Any,
    ) -> "NatalSnapshot":

        result: List[NatalTarget] = []

        for name in NATAL_PLANETS:
            longitude = point_longitude(subject, name)

            if longitude is None:
                continue

            result.append(
                NatalTarget(
                    name=name,
                    longitude=longitude,
                    house=point_house(subject, name),
                    is_angle=False,
                )
            )

        for name in ANGLES:
            longitude = point_longitude(subject, name)

            if longitude is None:
                continue

            result.append(
                NatalTarget(
                    name=name,
                    longitude=longitude,
                    house=None,
                    is_angle=True,
                )
            )

        return cls(
            targets=tuple(result)
        )

    def get(
        self,
        name: str,
    ) -> Optional[NatalTarget]:
        normalized = normalize_name(name)

        for target in self.targets:
            if target.name == normalized:
                return target

        return None


# ============================================================================
# TRANSIT SNAPSHOT
# ============================================================================

@dataclass(frozen=True)
class TransitPointSnapshot:
    planet: str
    timestamp_utc: datetime
    longitude: float
    speed: Optional[float]
    retrograde: Optional[bool]
    house: Any = None

    @property
    def motion(self) -> Motion:
        if self.retrograde is True:
            return Motion.RETROGRADE

        if self.speed is not None:
            if abs(self.speed) <= 0.00001:
                return Motion.STATIONARY
            if self.speed < 0:
                return Motion.RETROGRADE
            return Motion.DIRECT

        return Motion.UNKNOWN


# ============================================================================
# RETROGRADE
# ============================================================================

@dataclass(frozen=True)
class StationEvent:
    planet: str
    timestamp_utc: datetime
    from_motion: Motion
    to_motion: Motion
    speed: Optional[float]

    @property
    def station_type(self) -> str:
        if self.to_motion == Motion.RETROGRADE:
            return "retrograde_station"

        if self.to_motion == Motion.DIRECT:
            return "direct_station"

        return "station"


@dataclass(frozen=True)
class RetrogradeWindow:
    planet: str
    start_utc: datetime
    end_utc: datetime
    start_station: Optional[StationEvent]
    end_station: Optional[StationEvent]

    @property
    def duration_days(self) -> float:
        return (
            self.end_utc - self.start_utc
        ).total_seconds() / 86400.0

    def contains(self, timestamp: datetime) -> bool:
        timestamp = ensure_utc(timestamp)
        return self.start_utc <= timestamp <= self.end_utc


# ============================================================================
# TRANSIT WINDOW
# ============================================================================

@dataclass
class TransitWindow:
    """
    One continuous activation window of one natal transit aspect.

    Example:

        Saturn square natal Sun

    can produce:

        Window #1:
            ingress -> exact #1 -> egress

        Window #2:
            ingress -> exact #2 -> egress

        Window #3:
            ingress -> exact #3 -> egress

    because of retrograde motion.
    """

    transit_body: str
    natal_target: str
    aspect: str

    aspect_angle: float
    max_orb: float

    start_utc: datetime
    end_utc: datetime

    ingress_utc: Optional[datetime] = None
    egress_utc: Optional[datetime] = None

    exact_hits_utc: List[datetime] = field(default_factory=list)

    minimum_orb: float = 999.0
    minimum_orb_utc: Optional[datetime] = None

    phase_at_period_start: EventPhase = EventPhase.UNKNOWN
    phase_at_period_end: EventPhase = EventPhase.UNKNOWN

    retrograde_present: bool = False
    retrograde_windows: List[RetrogradeWindow] = field(
        default_factory=list
    )

    activity: Activity = Activity.BACKGROUND
    score: float = 0.0
    reason: str = ""

    themes: Tuple[str, ...] = ()

    transit_house_at_exact: Any = None
    natal_house: Any = None

    repeated_hit_index: int = 1
    repeated_hit_count: int = 1

    source: str = "TransitWindowEngine"

    @property
    def event_key(self) -> str:
        return sha1_key(
            self.transit_body,
            self.natal_target,
            self.aspect,
            self.start_utc.isoformat(),
            self.end_utc.isoformat(),
        )

    @property
    def semantic_key(self) -> Tuple[str, str, str]:
        return (
            self.transit_body,
            self.natal_target,
            self.aspect,
        )

    @property
    def exact_count(self) -> int:
        return len(self.exact_hits_utc)

    @property
    def duration_days(self) -> float:
        return (
            self.end_utc - self.start_utc
        ).total_seconds() / 86400.0

    @property
    def primary_exact_utc(self) -> Optional[datetime]:
        if not self.exact_hits_utc:
            return self.minimum_orb_utc

        return min(
            self.exact_hits_utc,
            key=lambda value: abs(
                (
                    value - self.start_utc
                ).total_seconds()
            ),
        )

    @property
    def display_name(self) -> str:
        return (
            f"{PLANET_RU.get(self.transit_body, self.transit_body)} "
            f"{ASPECT_RU.get(self.aspect, self.aspect)} "
            f"{TARGET_RU.get(self.natal_target, self.natal_target)}"
        )


# ============================================================================
# THEMATIC AGGREGATION
# ============================================================================

@dataclass
class ThemeAggregate:
    theme: str

    event_count: int = 0
    total_score: float = 0.0
    peak_score: float = 0.0

    exact_dates: List[datetime] = field(default_factory=list)

    event_keys: List[str] = field(default_factory=list)

    dominant_planets: List[str] = field(default_factory=list)
    dominant_targets: List[str] = field(default_factory=list)

    @property
    def strongest_event_key(self) -> Optional[str]:
        if not self.event_keys:
            return None

        return self.event_keys[0]


# ============================================================================
# THEMES
# ============================================================================

THEME_RULES: Dict[str, Dict[str, Any]] = {
    "identity": {
        "targets": {
            "sun",
            "ascendant",
            "medium_coeli",
        },
        "planets": {
            "sun",
            "uranus",
            "pluto",
            "saturn",
        },
    },
    "relationships": {
        "targets": {
            "venus",
            "mars",
            "descendant",
            "sun",
            "moon",
        },
        "planets": {
            "venus",
            "mars",
            "jupiter",
            "saturn",
            "uranus",
            "neptune",
            "pluto",
        },
    },
    "love": {
        "targets": {
            "venus",
            "descendant",
            "moon",
        },
        "planets": {
            "venus",
            "mars",
            "jupiter",
            "saturn",
            "uranus",
            "neptune",
            "pluto",
        },
    },
    "career": {
        "targets": {
            "medium_coeli",
            "sun",
            "saturn",
            "mars",
            "jupiter",
        },
        "planets": {
            "jupiter",
            "saturn",
            "uranus",
            "pluto",
        },
    },
    "money": {
        "targets": {
            "venus",
            "jupiter",
            "saturn",
            "pluto",
        },
        "planets": {
            "jupiter",
            "saturn",
            "pluto",
                "uranus",
        },
    },
    "home": {
        "targets": {
            "imum_coeli",
            "moon",
        },
        "planets": {
            "saturn",
            "uranus",
            "neptune",
            "pluto",
        },
    },
    "communication": {
        "targets": {
            "mercury",
            "sun",
            "moon",
        },
        "planets": {
            "mercury",
            "uranus",
            "neptune",
            "saturn",
        },
    },
    "energy": {
        "targets": {
            "mars",
            "sun",
            "ascendant",
        },
        "planets": {
            "mars",
            "sun",
            "saturn",
            "uranus",
            "pluto",
        },
    },
    "emotions": {
        "targets": {
            "moon",
            "venus",
            "ascendant",
        },
        "planets": {
            "moon",
            "saturn",
            "neptune",
            "pluto",
            "uranus",
        },
    },
    "growth": {
        "targets": {
            "jupiter",
            "sun",
            "medium_coeli",
            "ascendant",
        },
        "planets": {
            "jupiter",
            "uranus",
            "saturn",
            "pluto",
        },
    },
}


def classify_themes(
    transit_body: str,
    natal_target: str,
) -> Tuple[str, ...]:
    themes: List[str] = []

    for theme, rule in THEME_RULES.items():
        if (
            natal_target in rule["targets"]
            or transit_body in rule["planets"]
        ):
            themes.append(theme)

    # Hard fallback.
    if not themes:
        themes.append("general")

    return tuple(themes)


# ============================================================================
# TRANSIT WINDOW ENGINE
# ============================================================================

class TransitWindowEngine:
    """
    Core temporal engine.

    Responsibilities:

        1. calculate transit planetary positions
        2. detect aspect activation windows
        3. locate ingress
        4. locate exact hits
        5. locate egress
        6. detect repeated hits caused by retrograde
        7. detect retrograde periods
        8. attach motion information
    """

    def __init__(
        self,
        natal_subject: Any,
        natal_snapshot: NatalSnapshot,
        coords: Tuple[float, float],
        config: EngineConfig = DEFAULT_CONFIG,
        timezone_name: str = "UTC",
    ):
        self.natal_subject = natal_subject
        self.natal_snapshot = natal_snapshot

        self.lat = float(coords[0])
        self.lng = float(coords[1])

        self.config = config
        self.timezone_name = timezone_name

        self._subject_cache: Dict[
            Tuple[int, int, int, int, int, int],
            Any,
        ] = {}

        self._snapshot_cache: Dict[
            Tuple[str, datetime],
            TransitPointSnapshot,
        ] = {}

        self._retrograde_cache: Dict[
            Tuple[str, datetime, datetime],
            Tuple[RetrogradeWindow, ...],
        ] = {}

        self._lock = threading.RLock()

    # ----------------------------------------------------------------------
    # SUBJECT
    # ----------------------------------------------------------------------

    def _subject_cache_key(
        self,
        timestamp: datetime,
    ) -> Tuple[int, int, int, int, int, int]:

        timestamp = ensure_utc(timestamp)

        return (
            timestamp.year,
            timestamp.month,
            timestamp.day,
            timestamp.hour,
            timestamp.minute,
            timestamp.second,
        )

    def _get_transit_subject(self, timestamp: datetime) -> Any:
        timestamp = ensure_utc(timestamp)
        key = self._subject_cache_key(timestamp)

        with self._lock:
            cached = self._subject_cache.get(key)
            if cached is not None:
                return cached

        # Используем прямой конструктор вместо фабрики
        from kerykeion import AstrologicalSubject
        subject = AstrologicalSubject(
            name="Transit",
            year=timestamp.year,
            month=timestamp.month,
            day=timestamp.day,
            hour=timestamp.hour,
            minute=timestamp.minute,
            lat=self.lat,
            lng=self.lng,
            tz_str="UTC"
        )

        self._subject_cache[key] = subject
        return subject

    # def _get_transit_subject(
    #     self,
    #     timestamp: datetime,
    # ) -> Any:
    #
    #     timestamp = ensure_utc(timestamp)
    #     key = self._subject_cache_key(timestamp)
    #
    #     with self._lock:
    #         cached = self._subject_cache.get(key)
    #
    #         if cached is not None:
    #             return cached
    #
    #         subject = AstrologicalSubjectFactory.from_birth_data(
    #             name="Transit",
    #             year=timestamp.year,
    #             month=timestamp.month,
    #             day=timestamp.day,
    #             hour=timestamp.hour,
    #             minute=timestamp.minute,
    #             seconds=timestamp.second,
    #             lng=self.lng,
    #             lat=self.lat,
    #             tz_str="UTC",
    #             online=False,
    #         )
    #
    #         self._subject_cache[key] = subject
    #
    #         return subject

    # ----------------------------------------------------------------------
    # POINT SNAPSHOT
    # ----------------------------------------------------------------------

    def get_point_snapshot(
            self,
            planet: str,
            timestamp: datetime,
    ) -> TransitPointSnapshot:

        planet = normalize_name(planet)
        timestamp = ensure_utc(timestamp)

        cache_key = (planet, timestamp)

        with self._lock:
            cached = self._snapshot_cache.get(cache_key)
            if cached is not None:
                return cached

        logger.info("[SNAPSHOT] Getting %s at %s", planet, timestamp.isoformat())

        subject = self._get_transit_subject(timestamp)

        longitude = point_longitude(
            subject,
            planet,
        )

        if longitude is None:
            raise RuntimeError(
                f"Kerykeion returned no longitude for {planet} "
                f"at {timestamp.isoformat()}."
            )

        snapshot = TransitPointSnapshot(
            planet=planet,
            timestamp_utc=timestamp,
            longitude=longitude,
            speed=point_speed(subject, planet),
            retrograde=point_retrograde(subject, planet),
            house=point_house(subject, planet),
        )

        with self._lock:
            self._snapshot_cache[cache_key] = snapshot

        return snapshot

    # ----------------------------------------------------------------------
    # RESOLUTION
    # ----------------------------------------------------------------------

    def _base_step(
        self,
        period_type: PeriodType,
    ) -> timedelta:

        if period_type == PeriodType.DAY:
            return timedelta(
                minutes=self.config.day_step_minutes
            )

        if period_type == PeriodType.MONTH:
            return timedelta(
                hours=self.config.month_step_hours
            )

        return timedelta(
            hours=self.config.year_step_hours
        )

    def _planet_step(
        self,
        period_type: PeriodType,
        planet: str,
    ) -> timedelta:

        base = self._base_step(period_type)

        if planet in FAST_PLANETS:
            return min(
                base,
                timedelta(
                    minutes=self.config.fast_planet_step_minutes
                ),
            )

        return min(
            base,
            timedelta(
                hours=self.config.slow_planet_step_hours
            ),
        )

    # ----------------------------------------------------------------------
    # TIME GRID
    # ----------------------------------------------------------------------

    @staticmethod
    def _build_grid(
        start: datetime,
        end: datetime,
        step: timedelta,
    ) -> List[datetime]:

        start = ensure_utc(start)
        end = ensure_utc(end)

        if step.total_seconds() <= 0:
            raise ValueError("step must be positive")

        values: List[datetime] = [start]
        cursor = start

        while cursor < end:
            next_cursor = cursor + step

            if next_cursor >= end:
                break

            values.append(next_cursor)
            cursor = next_cursor

        if values[-1] != end:
            values.append(end)

        return values

    # ----------------------------------------------------------------------
    # ASPECT STATE
    # ----------------------------------------------------------------------

    def _aspect_state(
        self,
        planet: str,
        natal_target: NatalTarget,
        aspect: str,
        timestamp: datetime,
    ) -> Tuple[float, float]:

        snapshot = self.get_point_snapshot(
            planet,
            timestamp,
        )

        orb = aspect_orb(
            snapshot.longitude,
            natal_target.longitude,
            MAJOR_ASPECTS[aspect],
        )

        return orb, snapshot.longitude

    # ----------------------------------------------------------------------
    # ACTIVE STATE
    # ----------------------------------------------------------------------

    def _is_active(
        self,
        orb: float,
        max_orb: float,
    ) -> bool:
        return orb <= max_orb + 1e-9

    # ----------------------------------------------------------------------
    # ROOT FINDING
    # ----------------------------------------------------------------------

    def _bisect_threshold(
        self,
        planet: str,
        target: NatalTarget,
        aspect: str,
        left: datetime,
        right: datetime,
        threshold: float,
    ) -> datetime:

        left = ensure_utc(left)
        right = ensure_utc(right)

        left_orb, _ = self._aspect_state(
            planet,
            target,
            aspect,
            left,
        )

        right_orb, _ = self._aspect_state(
            planet,
            target,
            aspect,
            right,
        )

        left_active = left_orb <= threshold
        right_active = right_orb <= threshold

        if left_active == right_active:
            return left if left_active else right

        tolerance = timedelta(
            seconds=self.config.root_tolerance_seconds
        )

        while right - left > tolerance:
            middle = left + (
                right - left
            ) / 2

            middle_orb, _ = self._aspect_state(
                planet,
                target,
                aspect,
                middle,
            )

            middle_active = middle_orb <= threshold

            if middle_active == left_active:
                left = middle
                left_active = middle_active
            else:
                right = middle
                right_active = middle_active

        return left + (right - left) / 2

    # ----------------------------------------------------------------------
    # EXACT ASPECT MINIMIZATION
    # ----------------------------------------------------------------------

    def _golden_section_minimum(
        self,
        planet: str,
        target: NatalTarget,
        aspect: str,
        left: datetime,
        right: datetime,
    ) -> Tuple[datetime, float]:

        """
        Finds minimum orb without assuming a sign-changing root.

        This matters around retrograde motion:
        an aspect can touch exact and reverse without behaving like
        a normal monotonic root.
        """

        total_seconds = (
            right - left
        ).total_seconds()

        if total_seconds <= 0:
            orb, _ = self._aspect_state(
                planet,
                target,
                aspect,
                left,
            )
            return left, orb

        phi = (1.0 + math.sqrt(5.0)) / 2.0

        x1_seconds = total_seconds / phi
        x2_seconds = total_seconds - x1_seconds

        x1 = left + timedelta(
            seconds=x1_seconds
        )

        x2 = left + timedelta(
            seconds=x2_seconds
        )

        _, f1 = self._aspect_state(
            planet,
            target,
            aspect,
            x1,
        )

        _, f2 = self._aspect_state(
            planet,
            target,
            aspect,
            x2,
        )

        tolerance = timedelta(
            seconds=self.config.exact_tolerance_seconds
        )

        while right - left > tolerance:
            if f1 > f2:
                left = x1
                x1 = x2
                f1 = f2

                x2 = right - (
                    right - left
                ) / phi

                _, f2 = self._aspect_state(
                    planet,
                    target,
                    aspect,
                    x2,
                )

            else:
                right = x2
                x2 = x1
                f2 = f1

                x1 = left + (
                    right - left
                ) / phi

                _, f1 = self._aspect_state(
                    planet,
                    target,
                    aspect,
                    x1,
                )

        result = left + (right - left) / 2

        result_orb, _ = self._aspect_state(
            planet,
            target,
            aspect,
            result,
        )

        return result, result_orb

    # ----------------------------------------------------------------------
    # EXACT HIT
    # ----------------------------------------------------------------------

    def _find_exact_hit(
        self,
        planet: str,
        target: NatalTarget,
        aspect: str,
        left: datetime,
        right: datetime,
    ) -> Optional[Tuple[datetime, float]]:

        exact_time, minimum_orb = (
            self._golden_section_minimum(
                planet,
                target,
                aspect,
                left,
                right,
            )
        )

        if minimum_orb <= self.config.exact_tolerance_deg:
            return exact_time, minimum_orb

        return None

    # ----------------------------------------------------------------------
    # ASPECT WINDOW
    # ----------------------------------------------------------------------

    def _build_single_window(
        self,
        planet: str,
        target: NatalTarget,
        aspect: str,
        active_start: datetime,
        active_end: datetime,
        period: ForecastPeriod,
    ) -> TransitWindow:

        max_orb = self.config.aspect_orbs[aspect]

        start_orb, _ = self._aspect_state(
            planet,
            target,
            aspect,
            active_start,
        )

        end_orb, _ = self._aspect_state(
            planet,
            target,
            aspect,
            active_end,
        )

        ingress = None
        egress = None

        if (
            start_orb > max_orb
            and active_start > period.start_utc
        ):
            ingress = self._bisect_threshold(
                planet,
                target,
                aspect,
                active_start - timedelta(hours=24),
                active_start,
                max_orb,
            )

        if (
            end_orb > max_orb
            and active_end < period.end_utc
        ):
            egress = self._bisect_threshold(
                planet,
                target,
                aspect,
                active_end,
                active_end + timedelta(hours=24),
                max_orb,
            )

        # Search exact points within window.
        local_step = self._planet_step(
            period.period_type,
            planet,
        )

        exact_hits: List[datetime] = []

        cursor = active_start

        while cursor < active_end:
            nxt = min(
                cursor + local_step,
                active_end,
            )

            exact = self._find_exact_hit(
                planet,
                target,
                aspect,
                cursor,
                nxt,
            )

            if exact is not None:
                exact_time, _ = exact

                if not exact_hits:
                    exact_hits.append(exact_time)

                elif abs(
                    (
                        exact_time - exact_hits[-1]
                    ).total_seconds()
                ) > self.config.exact_tolerance_seconds * 2:
                    exact_hits.append(exact_time)

            cursor = nxt

        # Global minimum.
        minimum_time, minimum_orb = (
            self._golden_section_minimum(
                planet,
                target,
                aspect,
                active_start,
                active_end,
            )
        )

        return TransitWindow(
            transit_body=planet,
            natal_target=target.name,
            aspect=aspect,
            aspect_angle=MAJOR_ASPECTS[aspect],
            max_orb=max_orb,
            start_utc=active_start,
            end_utc=active_end,
            ingress_utc=ingress,
            egress_utc=egress,
            exact_hits_utc=sorted(
                set(exact_hits)
            ),
            minimum_orb=minimum_orb,
            minimum_orb_utc=minimum_time,
            natal_house=target.house,
            themes=classify_themes(
                planet,
                target.name,
            ),
        )

    # ----------------------------------------------------------------------
    # WINDOW DETECTION
    # ----------------------------------------------------------------------

    def _find_windows_for_pair(
        self,
        planet: str,
        target: NatalTarget,
        aspect: str,
        period: ForecastPeriod,
    ) -> List[TransitWindow]:

        max_orb = self.config.aspect_orbs[aspect]

        step = self._planet_step(
            period.period_type,
            planet,
        )

        # Extend the scan so we can determine boundary state.
        boundary_days = (
            self.config.boundary_search_days_slow
            if planet in SLOW_PLANETS
            else self.config.boundary_search_days_fast
        )

        scan_start = period.start_utc - timedelta(
            days=boundary_days
        )

        scan_end = period.end_utc + timedelta(
            days=boundary_days
        )

        # Never scan absurdly large periods.
        if (
            scan_end - scan_start
        ).days > self.config.max_scan_days:
            raise RuntimeError(
                f"Transit scan for {planet} exceeded safety limit."
            )

        grid = self._build_grid(
            scan_start,
            scan_end,
            step,
        )

        states: List[Tuple[datetime, float]] = []

        for timestamp in grid:
            orb, _ = self._aspect_state(
                planet,
                target,
                aspect,
                timestamp,
            )

            states.append(
                (
                    timestamp,
                    orb,
                )
            )

        windows: List[
            Tuple[datetime, datetime]
        ] = []

        active_start: Optional[datetime] = None

        for idx, (
            timestamp,
            orb,
        ) in enumerate(states):

            active = self._is_active(
                orb,
                max_orb,
            )

            if active and active_start is None:
                active_start = timestamp

            if (
                not active
                and active_start is not None
            ):
                previous_timestamp = states[
                    max(0, idx - 1)
                ][0]

                if previous_timestamp < timestamp:
                    boundary = self._bisect_threshold(
                        planet,
                        target,
                        aspect,
                        previous_timestamp,
                        timestamp,
                        max_orb,
                    )
                else:
                    boundary = timestamp

                windows.append(
                    (
                        active_start,
                        boundary,
                    )
                )

                active_start = None

        if active_start is not None:
            windows.append(
                (
                    active_start,
                    scan_end,
                )
            )

        result: List[TransitWindow] = []

        for start, end in windows:
            # Clip to forecast period only after exact boundaries
            # are known.
            clipped_start = max(
                start,
                period.start_utc,
            )

            clipped_end = min(
                end,
                period.end_utc,
            )

            if clipped_end <= clipped_start:
                continue

            window = self._build_single_window(
                planet=planet,
                target=target,
                aspect=aspect,
                active_start=clipped_start,
                active_end=clipped_end,
                period=period,
            )

            # Exact dates must belong to requested period.
            window.exact_hits_utc = [
                value
                for value in window.exact_hits_utc
                if period.start_utc
                <= value
                <= period.end_utc
            ]

            if (
                window.minimum_orb
                <= max_orb + 1e-9
            ):
                result.append(window)

        return result

    # ----------------------------------------------------------------------
    # RETROGRADE PASS 1
    # ----------------------------------------------------------------------

    def _retrograde_pass_1(
        self,
        planet: str,
        start: datetime,
        end: datetime,
    ) -> List[Tuple[datetime, Motion]]:

        step = timedelta(
            hours=self.config.retrograde_coarse_hours
        )

        grid = self._build_grid(
            start,
            end,
            step,
        )

        result: List[Tuple[datetime, Motion]] = []

        for timestamp in grid:
            snapshot = self.get_point_snapshot(
                planet,
                timestamp,
            )

            result.append(
                (
                    timestamp,
                    snapshot.motion,
                )
            )

        return result

    # ----------------------------------------------------------------------
    # RETROGRADE PASS 2
    # ----------------------------------------------------------------------

    def _retrograde_pass_2(
        self,
        planet: str,
        brackets: List[Tuple[datetime, datetime]],
    ) -> List[Tuple[datetime, datetime]]:

        result: List[Tuple[datetime, datetime]] = []

        step = timedelta(
            hours=self.config.retrograde_mid_hours
        )

        for coarse_left, coarse_right in brackets:

            grid = self._build_grid(
                coarse_left,
                coarse_right,
                step,
            )

            previous = grid[0]
            previous_snapshot = self.get_point_snapshot(
                planet,
                previous,
            )

            previous_motion = previous_snapshot.motion

            for current in grid[1:]:
                current_snapshot = (
                    self.get_point_snapshot(
                        planet,
                        current,
                    )
                )

                current_motion = current_snapshot.motion

                if (
                    previous_motion
                    != current_motion
                    and {
                        previous_motion,
                        current_motion,
                    }
                    & {
                        Motion.DIRECT,
                        Motion.RETROGRADE,
                    }
                ):
                    result.append(
                        (
                            previous,
                            current,
                        )
                    )

                previous = current
                previous_motion = current_motion

        return result

    # ----------------------------------------------------------------------
    # RETROGRADE PASS 3
    # ----------------------------------------------------------------------

    def _refine_station(
        self,
        planet: str,
        left: datetime,
        right: datetime,
    ) -> Optional[StationEvent]:

        left_snapshot = self.get_point_snapshot(
            planet,
            left,
        )

        right_snapshot = self.get_point_snapshot(
            planet,
            right,
        )

        left_speed = left_snapshot.speed
        right_speed = right_snapshot.speed

        if (
            left_speed is None
            or right_speed is None
        ):
            return None

        if (
            left_speed == 0
            or right_speed == 0
        ):
            timestamp = (
                left
                if left_speed == 0
                else right
            )

        elif left_speed * right_speed > 0:
            return None

        else:
            tolerance = timedelta(
                seconds=self.config.retrograde_final_seconds
            )

            lo = left
            hi = right

            while hi - lo > tolerance:
                middle = lo + (
                    hi - lo
                ) / 2

                middle_snapshot = (
                    self.get_point_snapshot(
                        planet,
                        middle,
                    )
                )

                middle_speed = middle_snapshot.speed

                if middle_speed is None:
                    break

                if abs(middle_speed) <= (
                    self.config.retrograde_speed_epsilon
                ):
                    lo = middle
                    hi = middle
                    break

                if left_speed * middle_speed <= 0:
                    hi = middle
                    right_speed = middle_speed
                else:
                    lo = middle
                    left_speed = middle_speed

            timestamp = lo + (
                hi - lo
            ) / 2

        before = self.get_point_snapshot(
            planet,
            timestamp - timedelta(minutes=5),
        )

        after = self.get_point_snapshot(
            planet,
            timestamp + timedelta(minutes=5),
        )

        before_motion = before.motion
        after_motion = after.motion

        if (
            before_motion
            not in {
                Motion.DIRECT,
                Motion.RETROGRADE,
            }
            or after_motion
            not in {
                Motion.DIRECT,
                Motion.RETROGRADE,
            }
        ):
            return None

        if before_motion == after_motion:
            return None

        return StationEvent(
            planet=planet,
            timestamp_utc=timestamp,
            from_motion=before_motion,
            to_motion=after_motion,
            speed=self.get_point_snapshot(
                planet,
                timestamp,
            ).speed,
        )

    # ----------------------------------------------------------------------
    # RETROGRADE ENGINE
    # ----------------------------------------------------------------------

    def detect_retrograde(
        self,
        planet: str,
        start: datetime,
        end: datetime,
    ) -> Tuple[RetrogradeWindow, ...]:

        planet = normalize_name(planet)
        start = ensure_utc(start)
        end = ensure_utc(end)

        cache_key = (
            planet,
            start,
            end,
        )

        cached = self._retrograde_cache.get(
            cache_key
        )

        if cached is not None:
            return cached

        # PASS 1
        coarse = self._retrograde_pass_1(
            planet,
            start,
            end,
        )

        brackets: List[
            Tuple[datetime, datetime]
        ] = []

        for idx in range(1, len(coarse)):
            left_time, left_motion = coarse[idx - 1]
            right_time, right_motion = coarse[idx]

            if (
                left_motion
                != right_motion
                and {
                    left_motion,
                    right_motion,
                }
                & {
                    Motion.DIRECT,
                    Motion.RETROGRADE,
                }
            ):
                brackets.append(
                    (
                        left_time,
                        right_time,
                    )
                )

        # PASS 2
        refined_brackets = self._retrograde_pass_2(
            planet,
            brackets,
        )

        # PASS 3
        stations: List[StationEvent] = []

        for left, right in refined_brackets:
            station = self._refine_station(
                planet,
                left,
                right,
            )

            if station is not None:
                stations.append(station)

        stations.sort(
            key=lambda item: item.timestamp_utc
        )

        windows: List[RetrogradeWindow] = []

        retrograde_start: Optional[
            StationEvent
        ] = None

        for station in stations:

            if (
                station.to_motion
                == Motion.RETROGRADE
            ):
                retrograde_start = station

            elif (
                station.to_motion
                == Motion.DIRECT
                and retrograde_start is not None
            ):
                windows.append(
                    RetrogradeWindow(
                        planet=planet,
                        start_utc=retrograde_start.timestamp_utc,
                        end_utc=station.timestamp_utc,
                        start_station=retrograde_start,
                        end_station=station,
                    )
                )

                retrograde_start = None

        if retrograde_start is not None:
            # Period continues beyond the requested interval.
            windows.append(
                RetrogradeWindow(
                    planet=planet,
                    start_utc=retrograde_start.timestamp_utc,
                    end_utc=end,
                    start_station=retrograde_start,
                    end_station=None,
                )
            )

        result = tuple(windows)

        self._retrograde_cache[
            cache_key
        ] = result

        return result

    # ----------------------------------------------------------------------
    # EVENT RETROGRADE DECORATION
    # ----------------------------------------------------------------------

    def attach_retrograde(
        self,
        event: TransitWindow,
        period: ForecastPeriod,
    ) -> None:

        retrograde = self.detect_retrograde(
            event.transit_body,
            period.start_utc,
            period.end_utc,
        )

        event.retrograde_windows = list(
            retrograde
        )

        event.retrograde_present = any(
            window.start_utc <= event.end_utc
            and window.end_utc >= event.start_utc
            for window in retrograde
        )

    # ----------------------------------------------------------------------
    # PHASE
    # ----------------------------------------------------------------------

    def calculate_phase(
        self,
        event: TransitWindow,
        timestamp: datetime,
    ) -> EventPhase:

        timestamp = ensure_utc(timestamp)

        before = max(
            event.start_utc,
            timestamp - timedelta(hours=6),
        )

        after = min(
            event.end_utc,
            timestamp + timedelta(hours=6),
        )

        if before == after:
            return EventPhase.STATIC

        before_orb, _ = self._aspect_state(
            event.transit_body,
            self.natal_snapshot.get(
                event.natal_target
            ),
            event.aspect,
            before,
        )

        current_orb, _ = self._aspect_state(
            event.transit_body,
            self.natal_snapshot.get(
                event.natal_target
            ),
            event.aspect,
            timestamp,
        )

        after_orb, _ = self._aspect_state(
            event.transit_body,
            self.natal_snapshot.get(
                event.natal_target
            ),
            event.aspect,
            after,
        )

        if (
            current_orb
            <= self.config.exact_tolerance_deg
        ):
            return EventPhase.EXACT

        if (
            after_orb < current_orb
            and current_orb <= before_orb
        ):
            return EventPhase.APPLYING

        if (
            after_orb > current_orb
            and current_orb >= before_orb
        ):
            return EventPhase.SEPARATING

        return EventPhase.STATIC

    # ----------------------------------------------------------------------
    # PUBLIC SCAN
    # ----------------------------------------------------------------------

    def scan(
        self,
        period: ForecastPeriod,
    ) -> List[TransitWindow]:

        events: List[TransitWindow] = []

        for planet in TRANSIT_PLANETS:

            for target in self.natal_snapshot.targets:

                for aspect in MAJOR_ASPECTS:

                    windows = self._find_windows_for_pair(
                        planet=planet,
                        target=target,
                        aspect=aspect,
                        period=period,
                    )

                    for event in windows:

                        self.attach_retrograde(
                            event,
                            period,
                        )

                        exact = event.primary_exact_utc

                        if exact is not None:
                            phase = self.calculate_phase(
                                event,
                                exact,
                            )
                        else:
                            phase = self.calculate_phase(
                                event,
                                event.start_utc,
                            )

                        if (
                            event.exact_hits_utc
                        ):
                            event.phase_at_period_start = (
                                EventPhase.APPLYING
                            )

                        event.phase_at_period_end = phase

                        events.append(event)

        if len(events) > self.config.max_events_per_period:
            raise RuntimeError(
                "Transit engine produced an unexpectedly large "
                f"number of events: {len(events)}"
            )

        return events


# ============================================================================
# SCORING
# ============================================================================

class TransitScorer:

    def __init__(
        self,
        config: EngineConfig = DEFAULT_CONFIG,
    ):
        self.config = config

    @staticmethod
    def _orb_strength(
        orb: float,
        max_orb: float,
    ) -> float:

        if max_orb <= 0:
            return 0.0

        ratio = clamp(
            orb / max_orb,
            0.0,
            1.0,
        )

        # Non-linear:
        # 0° is much stronger than edge of orb.
        return (1.0 - ratio) ** 1.7

    def score(
        self,
        event: TransitWindow,
        period: ForecastPeriod,
    ) -> float:

        score = 0.0

        planet = event.transit_body
        target = event.natal_target

        score += PLANET_WEIGHT.get(
            planet,
            0.0,
        )

        score += TARGET_WEIGHT.get(
            target,
            0.0,
        ) * 0.35

        score += ASPECT_WEIGHT.get(
            event.aspect,
            0.0,
        ) * 3.0

        score += (
            self._orb_strength(
                event.minimum_orb,
                event.max_orb,
            )
            * 6.0
        )

        if target in ANGLES:
            score += self.config.angle_bonus

        if target in PERSONAL_PLANETS:
            score += self.config.personal_target_bonus

        if event.retrograde_present:
            score += self.config.retrograde_bonus

        if event.exact_count > 1:
            score += (
                min(
                    event.exact_count - 1,
                    3,
                )
                * self.config.repeated_hit_bonus
            )

        if event.phase_at_period_end == EventPhase.APPLYING:
            score += self.config.applying_bonus

        elif event.phase_at_period_end == EventPhase.SEPARATING:
            score += self.config.separating_bonus

        # Longer outer-planet windows should not automatically dominate.
        if planet in OUTER_PLANETS:
            score *= 1.0

        # Very short Moon events are useful for daily forecast,
        # but should not dominate monthly/yearly forecasts.
        if (
            planet == "moon"
            and period.period_type != PeriodType.DAY
        ):
            score *= 0.65

        return round(
            score,
            4,
        )


# ============================================================================
# CLASSIFICATION
# ============================================================================

class TransitClassifier:

    def __init__(
        self,
        config: EngineConfig = DEFAULT_CONFIG,
    ):
        self.config = config

    def classify(
        self,
        event: TransitWindow,
    ) -> TransitWindow:

        orb = event.minimum_orb
        planet = event.transit_body
        target = event.natal_target

        if orb > event.max_orb:
            event.activity = Activity.BACKGROUND
            event.reason = "outside_aspect_orb"
            return event

        if (
            target in ANGLES
            and orb <= self.config.foreground_max_orb
        ):
            event.activity = Activity.FOREGROUND
            event.reason = "angle_activation"
            return event

        if (
            planet in SLOW_PLANETS
            and orb <= self.config.slow_planet_tight_orb
        ):
            event.activity = Activity.FOREGROUND
            event.reason = "slow_planet_tight"
            return event

        if orb <= self.config.very_tight_orb:
            event.activity = Activity.FOREGROUND
            event.reason = "very_tight"
            return event

        if (
            planet in FAST_PLANETS
            and orb <= self.config.fast_planet_tight_orb
        ):
            event.activity = Activity.FOREGROUND
            event.reason = "fast_planet_tight"
            return event

        if (
            event.exact_count > 0
            and event.retrograde_present
        ):
            event.activity = Activity.FOREGROUND
            event.reason = "exact_retrograde_repeat"
            return event

        event.activity = Activity.BACKGROUND
        event.reason = "ordinary_background"

        return event


# ============================================================================
# SEMANTIC DEDUPLICATION
# ============================================================================

class TransitDeduplicator:

    @staticmethod
    def _event_sort_key(
        event: TransitWindow,
    ) -> Tuple:

        return (
            -event.score,
            event.minimum_orb,
            event.start_utc,
        )

    def deduplicate(
        self,
        events: Sequence[TransitWindow],
    ) -> List[TransitWindow]:

        """
        Do NOT collapse repeated retrograde hits.

        Saturn square natal Sun in May, August and November
        are three real temporal activations.

        We only deduplicate exact duplicates produced by overlapping
        sampling windows.
        """

        seen: Dict[str, TransitWindow] = {}

        for event in events:

            key = sha1_key(
                event.transit_body,
                event.natal_target,
                event.aspect,
                event.start_utc.isoformat(),
                event.end_utc.isoformat(),
            )

            current = seen.get(key)

            if current is None:
                seen[key] = event
                continue

            if event.score > current.score:
                seen[key] = event

        result = list(seen.values())

        result.sort(
            key=self._event_sort_key
        )

        # Repeated hit numbering.
        groups: Dict[
            Tuple[str, str, str],
            List[TransitWindow],
        ] = defaultdict(list)

        for event in result:
            groups[
                event.semantic_key
            ].append(event)

        for group in groups.values():
            group.sort(
                key=lambda item: item.start_utc
            )

            total = len(group)

            for index, event in enumerate(
                group,
                start=1,
            ):
                event.repeated_hit_index = index
                event.repeated_hit_count = total

        return result


# ============================================================================
# RANKING
# ============================================================================

class TransitRanker:

    @staticmethod
    def sort(
        events: Iterable[TransitWindow],
    ) -> List[TransitWindow]:

        return sorted(
            events,
            key=lambda event: (
                -event.score,
                -event.exact_count,
                0
                if event.retrograde_present
                else 1,
                event.minimum_orb,
                event.start_utc,
            ),
        )


# ============================================================================
# THEMATIC AGGREGATOR
# ============================================================================

class ThemeAggregator:

    def aggregate(
        self,
        events: Sequence[TransitWindow],
        config: EngineConfig = DEFAULT_CONFIG,
    ) -> Dict[str, ThemeAggregate]:

        result: Dict[
            str,
            ThemeAggregate,
        ] = {}

        for event in events:

            for theme in event.themes:

                aggregate = result.get(theme)

                if aggregate is None:
                    aggregate = ThemeAggregate(
                        theme=theme
                    )

                    result[theme] = aggregate

                aggregate.event_count += 1
                aggregate.total_score += event.score
                aggregate.peak_score = max(
                    aggregate.peak_score,
                    event.score,
                )

                aggregate.event_keys.append(
                    event.event_key
                )

                aggregate.exact_dates.extend(
                    event.exact_hits_utc
                )

        # Normalize event ordering.
        for aggregate in result.values():

            aggregate.exact_dates = sorted(
                set(
                    aggregate.exact_dates
                )
            )

            aggregate.event_keys = list(
                dict.fromkeys(
                    aggregate.event_keys
                )
            )

        return dict(
            sorted(
                result.items(),
                key=lambda item: (
                    -item[1].peak_score,
                    -item[1].total_score,
                ),
            )
        )


# ============================================================================
# FORECAST RESULT
# ============================================================================

@dataclass
class ForecastResult:
    period: ForecastPeriod

    raw_events: List[TransitWindow]

    foreground_events: List[TransitWindow]
    background_events: List[TransitWindow]

    final_events: List[TransitWindow]

    themes: Dict[str, ThemeAggregate]

    retrogrades: Dict[
        str,
        Tuple[RetrogradeWindow, ...],
    ]

    generated_at_utc: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )

    engine_version: str = "3.0.0"

    def stats(self) -> Dict[str, Any]:
        return {
            "period_type": self.period.period_type.value,
            "period_start_utc": self.period.start_utc.isoformat(),
            "period_end_utc": self.period.end_utc.isoformat(),
            "raw_events": len(self.raw_events),
            "foreground_events": len(
                self.foreground_events
            ),
            "background_events": len(
                self.background_events
            ),
            "final_events": len(
                self.final_events
            ),
            "themes": len(self.themes),
            "retrograde_planets": len(
                self.retrogrades
            ),
        }


# ============================================================================
# PRODUCTION HOROSCOPE CALCULATOR
# ============================================================================

class HoroscopeCalculator:
    """
    Production horoscope facade.

    Existing application can continue using:

        calculator.build_context(
            period_type="month",
            period_start_utc=...,
            period_end_utc=...,
        )

    The calculator owns:
        - natal chart
        - temporal transit engine
        - scoring
        - classification
        - aggregation
        - LLM serialization
    """

    VERSION = "3.0.0"

    def __init__(
        self,
        user_data: Dict[str, Any],
        lang: str = "ru",
        telegram_id: Optional[int] = None,
        coords: Optional[
            Tuple[float, float, str]
        ] = None,
        emulation_mode: bool = False,
        config: EngineConfig = DEFAULT_CONFIG,
    ):
        self.user_data = user_data
        self.lang = lang
        self.telegram_id = telegram_id
        self.coords = coords
        self.emulation_mode = emulation_mode
        self.config = config

        self.astro_calc = AstrologyCalculator(
            user_data,
            lang=lang,
            telegram_id=telegram_id,
            coords=coords,
            emulation_mode=False,
        )

        self.natal_data = (
            self.astro_calc._build_natal_chart()
        )

        self.natal_subject = (
            self.astro_calc._subject
        )

        self.natal_snapshot = (
            NatalSnapshot.from_subject(
                self.natal_subject
            )
        )

        location = self.natal_data.get(
            "location",
            {},
        )

        lat = to_float(
            location.get("lat")
        )

        lng = to_float(
            location.get("lng")
        )

        if lat is None or lng is None:

            if coords is not None:
                lat = float(coords[0])
                lng = float(coords[1])
            else:
                raise ValueError(
                    "Natal coordinates are required "
                    "for transit calculations."
                )
        logger.info("[INIT] Creating transit engine...")
        self.transit_engine = TransitWindowEngine(
            natal_subject=self.natal_subject,
            natal_snapshot=self.natal_snapshot,
            coords=(
                float(lat),
                float(lng),
            ),
            config=config,
        )
        logger.info("[INIT] Transit engine created.")

        self.scorer = TransitScorer(
            config=config
        )

        self.classifier = TransitClassifier(
            config=config
        )

        self.deduplicator = (
            TransitDeduplicator()
        )

        self.ranker = TransitRanker()
        self.theme_aggregator = (
            ThemeAggregator()
        )

        self.last_result: Optional[
            ForecastResult
        ] = None

        self._result_cache: Dict[
            Tuple[Any, ...],
            ForecastResult,
        ] = {}

    # ----------------------------------------------------------------------
    # MAX EVENTS
    # ----------------------------------------------------------------------

    def _max_final_events(
        self,
        period_type: PeriodType,
        requested: Optional[int],
    ) -> int:

        if requested is not None:
            return max(
                1,
                min(
                    requested,
                    self.config.max_events_per_period,
                ),
            )

        if period_type == PeriodType.DAY:
            return self.config.max_final_events_day

        if period_type == PeriodType.MONTH:
            return self.config.max_final_events_month

        return self.config.max_final_events_year

    # ----------------------------------------------------------------------
    # RETROGRADES
    # ----------------------------------------------------------------------

    def _collect_retrogrades(
        self,
        period: ForecastPeriod,
    ) -> Dict[
        str,
        Tuple[RetrogradeWindow, ...],
    ]:

        result: Dict[
            str,
            Tuple[RetrogradeWindow, ...],
        ] = {}

        # Sun and Moon are never retrograde.
        for planet in (
            "mercury",
            "venus",
            "mars",
            "jupiter",
            "saturn",
            "uranus",
            "neptune",
            "pluto",
        ):

            windows = (
                self.transit_engine.detect_retrograde(
                    planet,
                    period.start_utc,
                    period.end_utc,
                )
            )

            if windows:
                result[planet] = windows

        return result

    # ----------------------------------------------------------------------
    # PIPELINE
    # ----------------------------------------------------------------------

    def calculate(
            self,
            period_type: str,
            period_start_utc: datetime,
            period_end_utc: datetime,
            max_display: Optional[int] = None,
    ) -> ForecastResult:

        period = ForecastPeriod.from_values(
            period_type=period_type,
            period_start_utc=period_start_utc,
            period_end_utc=period_end_utc,
        )

        cache_key = (
            period.period_type.value,
            period.start_utc,
            period.end_utc,
            max_display,
        )

        cached = self._result_cache.get(cache_key)
        if cached is not None:
            self.last_result = cached
            return cached

        logger.info("=== HOROSCOPE PIPELINE START ===")
        logger.info(
            "period=%s start=%s end=%s",
            period.period_type.value,
            period.start_utc.isoformat(),
            period.end_utc.isoformat(),
        )

        # --------------------------------------------------------------
        # 1. Transit windows
        # --------------------------------------------------------------

        logger.info("[STEP 1] Scanning transit windows...")
        try:
            raw_events = self.transit_engine.scan(period)
        except Exception as e:
            logger.error(f"[STEP 1] ERROR in transit_engine.scan: {e}", exc_info=True)
            raise

        logger.info("[TRANSITS] raw=%d", len(raw_events))

        # --------------------------------------------------------------
        # 2. Score
        # --------------------------------------------------------------

        logger.info("[STEP 2] Scoring events...")
        for event in raw_events:
            event.score = self.scorer.score(event, period)
        logger.info("[STEP 2] Scoring complete.")

        # --------------------------------------------------------------
        # 3. Classification
        # --------------------------------------------------------------

        logger.info("[STEP 3] Classifying events...")
        for event in raw_events:
            self.classifier.classify(event)
        logger.info("[STEP 3] Classification complete.")

        # --------------------------------------------------------------
        # 4. Dedup
        # --------------------------------------------------------------

        logger.info("[STEP 4] Deduplicating events...")
        deduped = self.deduplicator.deduplicate(raw_events)
        logger.info("[DEDUP] raw=%d deduped=%d", len(raw_events), len(deduped))

        # --------------------------------------------------------------
        # 5. Foreground / background
        # --------------------------------------------------------------

        logger.info("[STEP 5] Splitting foreground/background...")
        foreground = [
            event for event in deduped
            if event.activity == Activity.FOREGROUND
        ]
        background = [
            event for event in deduped
            if event.activity == Activity.BACKGROUND
        ]
        logger.info("[STEP 5] foreground=%d background=%d", len(foreground), len(background))

        # --------------------------------------------------------------
        # 6. Ranking
        # --------------------------------------------------------------

        logger.info("[STEP 6] Ranking foreground...")
        foreground = self.ranker.sort(foreground)
        background = self.ranker.sort(background)
        logger.info("[STEP 6] Ranking complete.")

        # --------------------------------------------------------------
        # 7. Final selection
        # --------------------------------------------------------------

        limit = self._max_final_events(period.period_type, max_display)
        final_events = foreground[:limit]
        logger.info("[STEP 7] final_events=%d (limit=%d)", len(final_events), limit)

        # --------------------------------------------------------------
        # 8. Themes
        # --------------------------------------------------------------

        logger.info("[STEP 8] Aggregating themes...")
        themes = self.theme_aggregator.aggregate(deduped, self.config)
        logger.info("[STEP 8] themes=%d", len(themes))

        # --------------------------------------------------------------
        # 9. Retrogrades
        # --------------------------------------------------------------

        logger.info("[STEP 9] Collecting retrogrades...")
        retrogrades = self._collect_retrogrades(period)
        logger.info("[STEP 9] retrogrades collected for %d planets", len(retrogrades))

        result = ForecastResult(
            period=period,
            raw_events=deduped,
            foreground_events=foreground,
            background_events=background,
            final_events=final_events,
            themes=themes,
            retrogrades=retrogrades,
        )

        self._result_cache[cache_key] = result
        self.last_result = result

        logger.info(
            "=== HOROSCOPE PIPELINE END === "
            "raw=%d foreground=%d background=%d final=%d",
            len(deduped),
            len(foreground),
            len(background),
            len(final_events),
        )

        return result

    # ----------------------------------------------------------------------
    # DATE FORMATTING
    # ----------------------------------------------------------------------

    @staticmethod
    def _format_date(
        value: Optional[datetime],
    ) -> str:

        if value is None:
            return "не определена"

        return value.astimezone(
            UTC
        ).strftime(
            "%d.%m.%Y %H:%M UTC"
        )

    @staticmethod
    def _format_date_short(
        value: Optional[datetime],
    ) -> str:

        if value is None:
            return "—"

        return value.astimezone(
            UTC
        ).strftime(
            "%d.%m.%Y"
        )

    # ----------------------------------------------------------------------
    # EVENT SERIALIZATION
    # ----------------------------------------------------------------------

    def _event_to_context(
        self,
        index: int,
        event: TransitWindow,
    ) -> List[str]:

        lines: List[str] = []

        exact_dates = ", ".join(
            self._format_date_short(
                value
            )
            for value in event.exact_hits_utc
        )

        if not exact_dates:
            exact_dates = "нет"

        lines.append(
            f"{index}. "
            f"{event.display_name}"
        )

        lines.append(
            f"   Период: "
            f"{self._format_date(event.start_utc)} "
            f"→ "
            f"{self._format_date(event.end_utc)}"
        )

        lines.append(
            f"   Точный контакт: {exact_dates}"
        )

        lines.append(
            f"   Минимальный орб: "
            f"{event.minimum_orb:.3f}°"
        )

        phase_key = event.phase_at_period_end.value
        phase_text = PHASE_RU.get(phase_key, phase_key)
        lines.append(f"   Фаза: {phase_text}")

        lines.append(
            f"   Score: {event.score:.2f}"
        )

        lines.append(
            f"   Activity: "
            f"{event.activity.value}"
        )

        lines.append(
            f"   Причина: {event.reason}"
        )

        lines.append(
            f"   Темы: "
            f"{', '.join(event.themes)}"
        )

        lines.append(
            f"   Повторный проход: "
            f"{event.repeated_hit_index}/"
            f"{event.repeated_hit_count}"
        )

        lines.append(
            f"   Ретроградность: "
            f"{'да' if event.retrograde_present else 'нет'}"
        )

        if event.transit_house_at_exact:
            lines.append(
                f"   Дом транзитной планеты: "
                f"{event.transit_house_at_exact}"
            )

        if event.natal_house:
            lines.append(
                f"   Натальная точка: "
                f"{event.natal_house}"
            )

        return lines

    # ----------------------------------------------------------------------
    # NATAL CONTEXT
    # ----------------------------------------------------------------------

    def _build_natal_context(
        self,
    ) -> List[str]:

        lines: List[str] = []

        lines.append(
            "=== НАТАЛЬНЫЕ ДАННЫЕ ==="
        )

        for target in self.natal_snapshot.targets:

            longitude = target.longitude

            lines.append(
                f"{TARGET_RU.get(target.name, target.name)}: "
                f"{longitude:.4f}°"
                + (
                    f", дом {target.house}"
                    if target.house is not None
                    else ""
                )
            )

        lines.append("")

        return lines

    # ----------------------------------------------------------------------
    # THEME CONTEXT
    # ----------------------------------------------------------------------

    def _build_theme_context(
        self,
        result: ForecastResult,
    ) -> List[str]:

        lines: List[str] = []

        lines.append(
            "=== ТЕМАТИЧЕСКАЯ КАРТА ПЕРИОДА ==="
        )

        for theme, aggregate in result.themes.items():

            if aggregate.event_count <= 0:
                continue

            lines.append(
                f"- {theme}: "
                f"events={aggregate.event_count}; "
                f"total_score={aggregate.total_score:.2f}; "
                f"peak_score={aggregate.peak_score:.2f}"
            )

            if aggregate.exact_dates:
                dates = ", ".join(
                    self._format_date_short(
                        value
                    )
                    for value in aggregate.exact_dates[:10]
                )

                lines.append(
                    f"  exact_dates={dates}"
                )

        lines.append("")

        return lines

    # ----------------------------------------------------------------------
    # RETROGRADE CONTEXT
    # ----------------------------------------------------------------------

    def _build_retrograde_context(
        self,
        result: ForecastResult,
    ) -> List[str]:

        lines: List[str] = []

        lines.append(
            "=== РЕТРОГРАДНОСТЬ ==="
        )

        if not result.retrogrades:
            lines.append(
                "Нет ретроградных периодов "
                "для рассматриваемых планет."
            )
            lines.append("")
            return lines

        for planet, windows in (
            result.retrogrades.items()
        ):

            lines.append(
                f"- {PLANET_RU.get(planet, planet)}:"
            )

            for window in windows:

                lines.append(
                    f"  {self._format_date(window.start_utc)} "
                    f"→ "
                    f"{self._format_date(window.end_utc)}"
                )

                if window.start_station:
                    lines.append(
                        "  "
                        f"станция: "
                        f"{self._format_date(window.start_station.timestamp_utc)} "
                        f""
                        f"{window.start_station.station_type}"
                    )

                if window.end_station:
                    lines.append(
                        "  "
                        f"станция: "
                        f"{self._format_date(window.end_station.timestamp_utc)} "
                        f""
                        f"{window.end_station.station_type}"
                    )

        lines.append("")

        return lines

    # ----------------------------------------------------------------------
    # LLM CONTEXT
    # ----------------------------------------------------------------------

    def build_context(
        self,
        period_type: str,
        period_start_utc: datetime,
        period_end_utc: datetime,
        max_display: Optional[int] = None,
    ) -> str:

        result = self.calculate(
            period_type=period_type,
            period_start_utc=period_start_utc,
            period_end_utc=period_end_utc,
            max_display=max_display,
        )

        lines: List[str] = []

        lines.append(
            "=== АСТРОЛОГИЧЕСКИЙ КОНТЕКСТ ==="
        )

        lines.append(
            f"Тип периода: "
            f"{result.period.period_type.value}"
        )

        lines.append(
            f"Начало: "
            f"{self._format_date(result.period.start_utc)}"
        )

        lines.append(
            f"Конец: "
            f"{self._format_date(result.period.end_utc)}"
        )

        lines.append(
            f"Движок: "
            f"{self.VERSION}"
        )

        lines.append("")

        lines.extend(
            self._build_natal_context()
        )

        # --------------------------------------------------------------
        # Main transits
        # --------------------------------------------------------------

        lines.append(
            "=== ГЛАВНЫЕ ТРАНЗИТЫ ==="
        )

        if not result.final_events:
            lines.append(
                "Нет транзитов, прошедших "
                "порог значимости."
            )

        else:

            for index, event in enumerate(
                result.final_events,
                start=1,
            ):
                lines.extend(
                    self._event_to_context(
                        index,
                        event,
                    )
                )

        lines.append("")

        # --------------------------------------------------------------
        # Themes
        # --------------------------------------------------------------

        lines.extend(
            self._build_theme_context(
                result
            )
        )

        # --------------------------------------------------------------
        # Retrograde
        # --------------------------------------------------------------

        lines.extend(
            self._build_retrograde_context(
                result
            )
        )

        # --------------------------------------------------------------
        # Background
        # --------------------------------------------------------------

        lines.append(
            "=== ФОНОВЫЕ ТРАНЗИТЫ ==="
        )

        if not result.background_events:
            lines.append("Нет.")

        else:

            background_limit = {
                PeriodType.DAY: 10,
                PeriodType.MONTH: 20,
                PeriodType.YEAR: 30,
            }[
                result.period.period_type
            ]

            for index, event in enumerate(
                result.background_events[
                    :background_limit
                ],
                start=1,
            ):
                lines.append(
                    f"{index}. "
                    f"{event.display_name}; "
                    f"период "
                    f"{self._format_date_short(event.start_utc)}"
                    f"–"
                    f"{self._format_date_short(event.end_utc)}; "
                    f"точность "
                    f"{event.minimum_orb:.2f}°; "
                    f"score={event.score:.2f}"
                )

        lines.append("")

        # --------------------------------------------------------------
        # LLM rules
        # --------------------------------------------------------------

        lines.append(
            "=== ИНСТРУКЦИЯ ДЛЯ ИНТЕРПРЕТАТОРА ==="
        )

        lines.append(
            "1. Используй только транзиты, "
            "присутствующие в данных."
        )

        lines.append(
            "2. Точные даты являются расчетными "
            "астрономическими моментами аспекта; "
            "не придумывай другие даты."
        )

        lines.append(
            "3. Если у транзита несколько exact dates, "
            "это отдельные проходы одного аспекта, "
            "обычно связанные с ретроградным движением."
        )

        lines.append(
            "4. Главные транзиты используй как "
            "основной материал прогноза."
        )

        lines.append(
            "5. Тематическую карту используй для "
            "структурирования прогноза по сферам жизни."
        )

        lines.append(
            "6. Score — техническая величина ранжирования, "
            "не астрологическое значение."
        )

        lines.append(
            "7. Не превращай каждый фоновой транзит "
            "в отдельное предсказание."
        )

        lines.append(
            "8. Для month/year отдавай приоритет "
            "долгим и повторным транзитам."
        )

        lines.append(
            "9. Для day учитывай быстрые транзиты "
            "и точные моменты."
        )

        lines.append(
            "10. Не утверждай причинно-следственные "
            "факты о здоровье, финансах или других "
            "реальных последствиях только на основании "
            "астрологического транзита."
        )

        return "\n".join(lines)

    # ----------------------------------------------------------------------
    # EMULATION / QA
    # ----------------------------------------------------------------------

    def get_qa_report(self) -> str:

        result = self.last_result

        if result is None:
            return "No forecast has been calculated."

        lines: List[str] = []

        lines.append(
            "=== HOROSCOPE QA REPORT ==="
        )

        stats = result.stats()

        for key, value in stats.items():
            lines.append(
                f"{key}: {value}"
            )

        lines.append("")

        lines.append(
            "=== FINAL EVENTS ==="
        )

        for index, event in enumerate(
            result.final_events,
            start=1,
        ):
            exact_dates = ','.join(
                self._format_date_short(value)
                for value in event.exact_hits_utc
            ) or 'none'

            lines.append(
                f"{index:02d}. "
                f"{event.display_name} | "
                f"{self._format_date(event.start_utc)} "
                f"-> "
                f"{self._format_date(event.end_utc)} | "
                f"exact={exact_dates} | "
                f"orb={event.minimum_orb:.3f} | "
                f"score={event.score:.3f} | "
                f"activity={event.activity.value} | "
                f"reason={event.reason} | "
                f"retrograde={event.retrograde_present}"
            )

        lines.append("")

        lines.append(
            "=== THEMES ==="
        )

        for theme, aggregate in (
            result.themes.items()
        ):

            lines.append(
                f"{theme}: "
                f"count={aggregate.event_count} "
                f"total={aggregate.total_score:.2f} "
                f"peak={aggregate.peak_score:.2f}"
            )

        lines.append("")

        lines.append(
            "=== RETROGRADES ==="
        )

        for planet, windows in (
            result.retrogrades.items()
        ):

            for window in windows:
                lines.append(
                    f"{planet}: "
                    f"{self._format_date(window.start_utc)} "
                    f"-> "
                    f"{self._format_date(window.end_utc)}"
                )

        return "\n".join(lines)


# ============================================================================
# OPTIONAL: SIMPLE FACTORY
# ============================================================================

def build_horoscope_context(
    user_data: Dict[str, Any],
    period_type: str,
    period_start_utc: datetime,
    period_end_utc: datetime,
    lang: str = "ru",
    telegram_id: Optional[int] = None,
    coords: Optional[
        Tuple[float, float, str]
    ] = None,
    max_display: Optional[int] = None,
) -> str:

    calculator = HoroscopeCalculator(
        user_data=user_data,
        lang=lang,
        telegram_id=telegram_id,
        coords=coords,
        emulation_mode=False,
    )

    return calculator.build_context(
        period_type=period_type,
        period_start_utc=period_start_utc,
        period_end_utc=period_end_utc,
        max_display=max_display,
    )