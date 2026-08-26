import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from kerykeion import AstrologicalSubject, AspectsFactory

from bot.calculators.astrology_calculator import AstrologyCalculator

logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

TRANSIT_PLANETS = {
    "sun", "moon", "mercury", "venus", "mars",
    "jupiter", "saturn", "uranus", "neptune", "pluto",
}

NATAL_TARGETS = {
    "sun", "moon", "mercury", "venus", "mars",
    "jupiter", "saturn", "uranus", "neptune", "pluto",
    "chiron", "true_north_lunar_node",
    "ascendant", "medium_coeli", "descendant", "imum_coeli",
}

ACTIVE_ASPECTS = [
    {"name": "conjunction", "orb": 5.0},
    {"name": "opposition", "orb": 5.0},
    {"name": "square", "orb": 4.0},
    {"name": "trine", "orb": 4.0},
    {"name": "sextile", "orb": 3.0},
]

MAJOR_ASPECTS = {
    "conjunction", "opposition", "square", "trine", "sextile"
}

ANGLE_TARGETS = {
    "ascendant", "medium_coeli", "descendant", "imum_coeli"
}

SLOW_PLANETS = {
    "jupiter", "saturn", "uranus", "neptune", "pluto"
}

PERSONAL_TARGETS = {
    "sun", "moon", "mercury", "venus", "mars"
}

# Максимальный орб для попадания в foreground.
# Важно: score НЕ заменяется activity. Activity вычисляется здесь
# из астрологических признаков, а затем фильтр только разделяет списки.
FOREGROUND_MAX_ORB = 3.0

# Для быстрых планет требуется более тесный аспект, если цель не угол.
FAST_PLANET_TIGHT_ORB = 1.5

# Для медленных планет допускаем более широкий орб.
SLOW_PLANET_MAX_ORB = 3.0

# Максимальное количество событий, передаваемых как основные.
DEFAULT_MAX_DISPLAY = 12

# Вес транзитной планеты.
PLANET_WEIGHT = {
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

# Вес натальной точки.
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

ASPECT_WEIGHT = {
    "conjunction": 1.00,
    "opposition": 0.95,
    "square": 0.90,
    "trine": 0.85,
    "sextile": 0.75,
}

ASPECT_RU = {
    "conjunction": "соединение",
    "opposition": "оппозиция",
    "square": "квадрат",
    "trine": "трин",
    "sextile": "секстиль",
}

PHASE_RU = {
    "applying": "сходящийся",
    "separating": "расходящийся",
    "static": "стационарный",
    "unknown": "не определена",
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


# ============================================================================
# HELPERS
# ============================================================================

def get_attr_safe(obj: Any, *names: str, default=None):
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_name(value: Any) -> str:
    if value is None:
        return ""
    return (
        str(value)
        .strip()
        .lower()
        .replace(" ", "_")
        .replace("'", "")
    )


def normalize_phase(value: Any) -> str:
    if not value:
        return "unknown"

    value = str(value).strip().lower()

    if value == "applying":
        return "applying"
    if value == "separating":
        return "separating"
    if value in {"static", "stationary"}:
        return "static"

    return "unknown"


def get_model_dict(subject: AstrologicalSubject) -> Dict[str, Any]:
    model = getattr(subject, "model", None)

    if callable(model):
        model = model()

    if model is None:
        model = subject

    if hasattr(model, "model_dump"):
        return model.model_dump()

    if hasattr(model, "dict"):
        return model.dict()

    return getattr(model, "__dict__", {})


def extract_point_dict(
    subject: AstrologicalSubject,
    point_name: str,
) -> Optional[Dict[str, Any]]:
    data = get_model_dict(subject)
    point = data.get(point_name)

    if point is None:
        return None

    if isinstance(point, dict):
        return point

    return {
        "sign": get_attr_safe(point, "sign"),
        "position": to_float(get_attr_safe(point, "position")),
        "abs_pos": to_float(get_attr_safe(point, "abs_pos")),
        "house": get_attr_safe(point, "house"),
        "retrograde": bool(get_attr_safe(point, "retrograde", False)),
        "speed": to_float(get_attr_safe(point, "speed"), 0.0),
    }


def extract_planets_dict(subject: AstrologicalSubject) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    data = get_model_dict(subject)

    for name in TRANSIT_PLANETS | {"chiron", "true_north_lunar_node"}:
        point = data.get(name)
        if not point:
            continue

        if isinstance(point, dict):
            result[name] = point
        else:
            result[name] = {
                "sign": get_attr_safe(point, "sign"),
                "position": to_float(get_attr_safe(point, "position")),
                "abs_pos": to_float(get_attr_safe(point, "abs_pos")),
                "house": get_attr_safe(point, "house"),
                "retrograde": bool(get_attr_safe(point, "retrograde", False)),
                "speed": to_float(get_attr_safe(point, "speed"), 0.0),
            }

    return result


def extract_angles_dict(subject: AstrologicalSubject) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    data = get_model_dict(subject)

    for name in ANGLE_TARGETS:
        point = data.get(name)
        if not point:
            continue

        if isinstance(point, dict):
            result[name] = point
        else:
            result[name] = {
                "sign": get_attr_safe(point, "sign"),
                "position": to_float(get_attr_safe(point, "position")),
                "abs_pos": to_float(get_attr_safe(point, "abs_pos")),
            }

    return result


# ============================================================================
# TRANSIT EVENT
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

    phase: str = "unknown"

    transit_house: Any = 0
    natal_target_house: Any = 0

    is_retrograde: bool = False
    transit_speed: float = 0.0

    score: float = 0.0
    activity: str = "BACKGROUND"
    reason: str = ""

    # Служебные поля для диагностики / промпта.
    source_aspect: str = ""
    source_movement: str = ""

    @property
    def unique_key(self) -> str:
        return (
            f"{self.transit_body}:"
            f"{self.natal_target}:"
            f"{self.aspect}"
        )

    @property
    def display_name(self) -> str:
        return (
            f"{PLANET_RU.get(self.transit_body, self.transit_body)} "
            f"{ASPECT_RU.get(self.aspect, self.aspect)} "
            f"{TARGET_RU.get(self.natal_target, self.natal_target)}"
        )


# ============================================================================
# KERYKEION
# ============================================================================

def get_natal_aspects(subject: AstrologicalSubject) -> List[Any]:
    try:
        result = AspectsFactory.single_chart_aspects(
            subject,
            active_aspects=ACTIVE_ASPECTS,
        )
        return list(result.aspects) if hasattr(result, "aspects") else []
    except Exception as exc:
        logger.warning("Ошибка получения натальных аспектов: %s", exc)
        return []


def get_transit_aspects(
    natal_subject: AstrologicalSubject,
    transit_subject: AstrologicalSubject,
) -> List[Any]:
    natal_model = (
        natal_subject.model()
        if callable(natal_subject.model)
        else natal_subject.model
    )

    transit_model = (
        transit_subject.model()
        if callable(transit_subject.model)
        else transit_subject.model
    )

    result = AspectsFactory.dual_chart_aspects(
        natal_model,
        transit_model,
        first_subject_is_fixed=True,
        second_subject_is_fixed=False,
        active_aspects=ACTIVE_ASPECTS,
    )

    logger.info(
        "Kerykeion transit aspects: %d",
        len(result.aspects),
    )

    return list(result.aspects)


# ============================================================================
# HOROSCOPE CALCULATOR
# ============================================================================

class HoroscopeCalculator:
    """
    Production pipeline:

        Kerykeion
          ↓
        TransitEvent
          ↓
        score
          ↓
        FOREGROUND / BACKGROUND
          ↓
        semantic deduplication
          ↓
        ranking
          ↓
        TOP-N
          ↓
        plain-text context for LLM

    Важный принцип:
        _filter_events() НИКОГДА не вычисляет значимость.
        Он только разделяет уже классифицированные события.

    Поэтому невозможно получить ситуацию:
        activity=FOREGROUND при создании события
        → BACKGROUND внутри фильтра.

    Если activity неправильная, проблема находится в _classify_event().
    """

    def __init__(
        self,
        user_data: Dict[str, Any],
        lang: str = "ru",
        telegram_id: Optional[int] = None,
        coords: Optional[Tuple[float, float, str]] = None,
        emulation_mode: bool = False,
    ):
        self.user_data = user_data
        self.lang = lang
        self.telegram_id = telegram_id
        self.coords = coords
        self.emulation_mode = emulation_mode

        self.astro_calc = AstrologyCalculator(
            user_data,
            lang=lang,
            telegram_id=telegram_id,
            coords=coords,
            emulation_mode=False,
        )

        self.natal_data = self.astro_calc._build_natal_chart()
        self.natal_subject = self.astro_calc._subject

        self.natal_planets = extract_planets_dict(self.natal_subject)
        self.natal_angles = extract_angles_dict(self.natal_subject)

        self._transit_cache: Dict[str, AstrologicalSubject] = {}

        self.raw_events: List[TransitEvent] = []
        self.dedup_events: List[TransitEvent] = []
        self.foreground_events: List[TransitEvent] = []
        self.background_events: List[TransitEvent] = []
        self.final_events: List[TransitEvent] = []

        self.natal_targets = self._build_natal_targets()

    # ----------------------------------------------------------------------
    # NATAL TARGETS
    # ----------------------------------------------------------------------

    def _build_natal_targets(self) -> List[Dict[str, Any]]:
        targets: List[Dict[str, Any]] = []

        for name, data in self.natal_planets.items():
            if name not in NATAL_TARGETS:
                continue

            lon = to_float(data.get("abs_pos"), 0.0) or 0.0

            targets.append({
                "name": name,
                "longitude": lon % 360.0,
                "house": data.get("house"),
                "is_angle": False,
            })

        for name, data in self.natal_angles.items():
            lon = to_float(data.get("abs_pos"), 0.0) or 0.0

            targets.append({
                "name": name,
                "longitude": lon % 360.0,
                "house": None,
                "is_angle": True,
            })

        return targets

    # ----------------------------------------------------------------------
    # TRANSIT SUBJECT
    # ----------------------------------------------------------------------

    def _get_transit_subject(self, date: datetime) -> AstrologicalSubject:
        # Ключ включает время. Нельзя кешировать только YYYY-MM-DD,
        # иначе два расчёта в один день могут получить разные даты/времена,
        # но один и тот же transit subject.
        key = date.astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M"
        )

        if key in self._transit_cache:
            return self._transit_cache[key]

        location = self.natal_data.get("location", {})

        lat = location.get("lat")
        lng = location.get("lng")

        date_utc = date.astimezone(timezone.utc)

        subject = AstrologicalSubject(
            name="Transit",
            year=date_utc.year,
            month=date_utc.month,
            day=date_utc.day,
            hour=date_utc.hour,
            minute=date_utc.minute,
            lat=lat,
            lng=lng,
            tz_str="UTC",
        )

        self._transit_cache[key] = subject
        return subject

    # ----------------------------------------------------------------------
    # ANGLE NORMALIZATION
    # ----------------------------------------------------------------------

    @staticmethod
    def _normalize_angle_target(
        target: str,
        aspect: str,
    ) -> Tuple[str, str]:
        """
        Приводим противоположные углы к одной оси.

        DSC = ASC + 180°
        IC  = MC  + 180°

        Поэтому:
            Uranus opposition ASC
        и:
            Uranus conjunction DSC

        описывают одну конфигурацию и должны дедуплицироваться.

        Аналогично:
            trine ASC <-> sextile DSC
            trine MC  <-> sextile IC
        """
        target = normalize_name(target)
        aspect = normalize_name(aspect)

        opposite = {
            "conjunction": "opposition",
            "opposition": "conjunction",
            "trine": "sextile",
            "sextile": "trine",
            "square": "square",
        }

        if target == "descendant":
            return "ascendant", opposite.get(aspect, aspect)

        if target == "imum_coeli":
            return "medium_coeli", opposite.get(aspect, aspect)

        return target, aspect

    # ----------------------------------------------------------------------
    # RAW → TRANSIT EVENT
    # ----------------------------------------------------------------------

    def _identify_transit_and_natal(
        self,
        aspect: Any,
        transit_subject: AstrologicalSubject,
    ) -> Optional[Tuple[str, str]]:
        p1 = normalize_name(get_attr_safe(aspect, "p1_name"))
        p2 = normalize_name(get_attr_safe(aspect, "p2_name"))

        p1_owner = normalize_name(
            get_attr_safe(aspect, "p1_owner", default="")
        )
        p2_owner = normalize_name(
            get_attr_safe(aspect, "p2_owner", default="")
        )

        natal_name = normalize_name(
            getattr(self.natal_subject, "name", "")
        )

        transit_name = normalize_name(
            getattr(transit_subject, "name", "")
        )

        if p1_owner == natal_name and p2_owner == transit_name:
            natal_target, transit_body = p1, p2
        elif p2_owner == natal_name and p1_owner == transit_name:
            natal_target, transit_body = p2, p1
        else:
            # Fallback для версий Kerykeion, где owner может отсутствовать.
            if p1 in NATAL_TARGETS and p2 in TRANSIT_PLANETS:
                natal_target, transit_body = p1, p2
            elif p2 in NATAL_TARGETS and p1 in TRANSIT_PLANETS:
                natal_target, transit_body = p2, p1
            else:
                return None

        if natal_target not in NATAL_TARGETS:
            return None

        if transit_body not in TRANSIT_PLANETS:
            return None

        return transit_body, natal_target

    def _build_raw_events(self, forecast_date: datetime) -> List[TransitEvent]:
        transit_subject = self._get_transit_subject(forecast_date)
        aspects = get_transit_aspects(self.natal_subject, transit_subject)

        events: List[TransitEvent] = []
        logger.info("=== KERYKEION RAW ASPECTS ===")
        logger.info("Всего получено: %d", len(aspects))

        for idx, aspect in enumerate(aspects):
            # Логируем полную информацию о сыром аспекте до проверок
            p1 = get_attr_safe(aspect, "p1_name")
            p2 = get_attr_safe(aspect, "p2_name")
            asp_type = get_attr_safe(aspect, "aspect")
            orb = to_float(get_attr_safe(aspect, "orbit"))
            movement = get_attr_safe(aspect, "aspect_movement")
            p1_owner = get_attr_safe(aspect, "p1_owner")
            p2_owner = get_attr_safe(aspect, "p2_owner")

            # Начальный лог
            logger.info(
                "[RAW ASPECT %02d] %s -> %s | aspect=%s orb=%.3f movement=%s | owner1=%s owner2=%s",
                idx, p1, p2, asp_type, orb if orb is not None else 0.0, movement, p1_owner, p2_owner
            )

            # Проверка owner и принадлежности к планетам
            pair = self._identify_transit_and_natal(aspect, transit_subject)
            if not pair:
                logger.info("  -> ОТБРОШЕН: не удалось определить transit/natal пару")
                continue

            transit_body, natal_target_raw = pair
            source_aspect = normalize_name(asp_type)
            if source_aspect not in MAJOR_ASPECTS:
                logger.info("  -> ОТБРОШЕН: non-major aspect (%s)", source_aspect)
                continue

            if orb is None or orb > 10.0:  # если орб слишком большой – тоже отбрасываем
                logger.info("  -> ОТБРОШЕН: orb=None или >10.0")
                continue

            # Здесь создаём событие, как раньше...
            movement_str = str(movement or "")
            phase = normalize_phase(movement_str)

            natal_target, aspect_type = self._normalize_angle_target(natal_target_raw, source_aspect)

            natal_data = self.natal_planets.get(natal_target) or self.natal_angles.get(natal_target)
            transit_data = extract_point_dict(transit_subject, transit_body)

            if not natal_data or not transit_data:
                logger.info("  -> ОТБРОШЕН: нет данных для transit=%s или natal=%s", transit_body, natal_target)
                continue

            transit_lon = (to_float(transit_data.get("abs_pos"), 0.0) or 0.0) % 360.0
            natal_lon = (to_float(natal_data.get("abs_pos"), 0.0) or 0.0) % 360.0
            aspect_degrees = to_float(get_attr_safe(aspect, "aspect_degrees"), 0.0) or 0.0

            event = TransitEvent(
                transit_body=transit_body,
                natal_target=natal_target,
                transit_longitude=transit_lon,
                natal_target_longitude=natal_lon,
                angular_distance=aspect_degrees,
                aspect=aspect_type,
                aspect_angle=aspect_degrees,
                orb=float(orb),
                phase=phase,
                transit_house=transit_data.get("house", 0),
                natal_target_house=natal_data.get("house", 0),
                is_retrograde=bool(transit_data.get("retrograde", False)),
                transit_speed=to_float(transit_data.get("speed"), 0.0) or 0.0,
                source_aspect=source_aspect,
                source_movement=movement_str,
            )
            events.append(event)
            logger.info("  -> ПРИНЯТ: %s -> %s | aspect=%s orb=%.3f phase=%s",
                        transit_body, natal_target, aspect_type, orb, phase)

        logger.info("[RAW] Итого принято: %d из %d", len(events), len(aspects))
        self.raw_events = events
        return events

    # ----------------------------------------------------------------------
    # SCORE
    # ----------------------------------------------------------------------

    @staticmethod
    def _orb_strength(orb: float) -> float:
        """
        0..1.
        Чем меньше орб, тем выше сила.
        """
        if orb <= 0.1:
            return 1.0
        if orb <= 0.5:
            return 0.90
        if orb <= 1.0:
            return 0.75
        if orb <= 2.0:
            return 0.55
        if orb <= 3.0:
            return 0.35
        return 0.0

    def _calculate_score(self, event: TransitEvent) -> float:
        """
        Score = значимость транзита для ранжирования.

        Диапазон не фиксирован — важен относительный порядок.

        Основные факторы:
          - медленность транзитной планеты;
          - значимость натальной точки;
          - тип аспекта;
          - точность орба;
          - applying/separating;
          - угловая точка.
        """
        planet = event.transit_body
        target = event.natal_target
        aspect = event.aspect

        score = 0.0

        # 1. Базовая сила транзитной планеты.
        score += PLANET_WEIGHT.get(planet, 0.0)

        # 2. Значимость натальной точки.
        score += TARGET_WEIGHT.get(target, 0.0) * 0.35

        # 3. Тип аспекта.
        score += ASPECT_WEIGHT.get(aspect, 0.0) * 3.0

        # 4. Точность.
        orb_strength = self._orb_strength(event.orb)
        score += orb_strength * 5.0

        # 5. Углы — сильный модификатор.
        if target in ANGLE_TARGETS:
            score += 2.5

        # 6. Личные планеты как натальная цель.
        if target in PERSONAL_TARGETS:
            score += 1.0

        # 7. Applying немного сильнее separating.
        if event.phase == "applying":
            score += 1.5
        elif event.phase == "separating":
            score += 0.25

        return round(score, 3)

    # ----------------------------------------------------------------------
    # CLASSIFICATION
    # ----------------------------------------------------------------------

    def _classify_event(self, event: TransitEvent) -> TransitEvent:
        """
        Определяет FOREGROUND/BACKGROUND.

        Это единственное место, где принимается решение
        о значимости события.

        _filter_events() ниже ничего не "угадывает".
        """

        planet = event.transit_body
        target = event.natal_target
        orb = event.orb

        # Сначала score.
        event.score = self._calculate_score(event)

        # --- HARD EXCLUSIONS -----------------------------------------------

        if event.aspect not in MAJOR_ASPECTS:
            event.activity = "BACKGROUND"
            event.reason = "non_major_aspect"
            return event

        if orb > FOREGROUND_MAX_ORB:
            event.activity = "BACKGROUND"
            event.reason = f"orb_too_wide:{orb:.2f}"
            return event

        # --- STRONG FOREGROUND CASES ---------------------------------------

        if planet in SLOW_PLANETS and target in ANGLE_TARGETS:
            event.activity = "FOREGROUND"
            event.reason = "slow_planet_to_angle"
            return event

        if planet in SLOW_PLANETS and orb <= 1.5:
            event.activity = "FOREGROUND"
            event.reason = "slow_planet_tight_orb"
            return event

        if orb <= 0.5:
            event.activity = "FOREGROUND"
            event.reason = "very_tight_orb"
            return event

        if target in ANGLE_TARGETS and event.phase == "applying" and orb <= 2.5:
            event.activity = "FOREGROUND"
            event.reason = "angle_applying"
            return event

        if event.phase == "applying" and orb <= 1.5:
            event.activity = "FOREGROUND"
            event.reason = "applying_tight"
            return event

        # Быстрые планеты требуют высокой точности.
        if planet not in SLOW_PLANETS and orb <= FAST_PLANET_TIGHT_ORB:
            event.activity = "FOREGROUND"
            event.reason = "fast_planet_tight_orb"
            return event

        # Всё остальное — background.
        event.activity = "BACKGROUND"
        event.reason = "ordinary_background"

        return event

    def _score_and_classify(self, events: List[TransitEvent]) -> List[TransitEvent]:
        logger.info("=== КЛАССИФИКАЦИЯ СОБЫТИЙ ===")
        for idx, event in enumerate(events):
            self._classify_event(event)
            logger.info(
                "[CLASSIFY %02d] %s -> %s | aspect=%s orb=%.3f phase=%s score=%.3f activity=%s reason=%s",
                idx,
                event.transit_body,
                event.natal_target,
                event.aspect,
                event.orb,
                event.phase,
                event.score,
                event.activity,
                event.reason,
            )
        return events

    # ----------------------------------------------------------------------
    # DEDUPLICATION
    # ----------------------------------------------------------------------

    @staticmethod
    def _canonical_event_key(event: TransitEvent) -> Tuple[str, str, str]:
        """
        Семантический ключ.

        ASC/DSC и MC/IC уже нормализованы при создании события.

        Дополнительная защита:
        ключ строится по:
            transit_body + canonical target + aspect
        """
        return (
            event.transit_body.lower(),
            event.natal_target.lower(),
            event.aspect.lower(),
        )

    def _deduplicate_events(self, events: List[TransitEvent]) -> List[TransitEvent]:
        best: Dict[Tuple[str, str, str], TransitEvent] = {}

        for event in events:
            key = self._canonical_event_key(event)
            current = best.get(key)
            if current is None:
                best[key] = event
                continue
            if event.score > current.score or (event.score == current.score and event.orb < current.orb):
                best[key] = event

        result = list(best.values())
        logger.info("=== ДЕДУПЛИКАЦИЯ ===")
        logger.info("Было: %d, стало: %d", len(events), len(result))
        for idx, event in enumerate(result):
            logger.info("[DEDUP %02d] %s -> %s | aspect=%s orb=%.3f score=%.3f", idx, event.transit_body,
                        event.natal_target, event.aspect, event.orb, event.score)
        self.dedup_events = result
        return result

    # ----------------------------------------------------------------------
    # FILTER
    # ----------------------------------------------------------------------

    def _filter_events(self, events: List[TransitEvent]) -> Tuple[List[TransitEvent], List[TransitEvent]]:
        foreground: List[TransitEvent] = []
        background: List[TransitEvent] = []

        logger.info("=== ФИЛЬТРАЦИЯ ===")
        for idx, event in enumerate(events):
            activity = str(event.activity).strip().upper()
            if activity == "FOREGROUND":
                foreground.append(event)
                decision = "FOREGROUND"
            else:
                background.append(event)
                decision = "BACKGROUND"

            logger.info(
                "[FILTER %02d] %s -> %s | activity=%s reason=%s orb=%.3f score=%.3f",
                idx,
                event.transit_body,
                event.natal_target,
                decision,
                event.reason,
                event.orb,
                event.score,
            )

        logger.info("[FILTER] Итог: FOREGROUND=%d, BACKGROUND=%d", len(foreground), len(background))
        self.foreground_events = foreground
        self.background_events = background
        return foreground, background

    # ----------------------------------------------------------------------
    # RANKING / TOP N
    # ----------------------------------------------------------------------

    @staticmethod
    def _ranking_key(event: TransitEvent):
        return (
            event.score,
            1 if event.phase == "applying" else 0,
            -event.orb,
        )

    def _rank_events(self, events: List[TransitEvent]) -> List[TransitEvent]:
        ranked = sorted(events, key=self._ranking_key, reverse=True)
        logger.info("=== РАНЖИРОВАНИЕ ===")
        for idx, event in enumerate(ranked, start=1):
            logger.info(
                "[RANK %02d] %s -> %s | orb=%.3f score=%.3f phase=%s reason=%s",
                idx,
                event.transit_body,
                event.natal_target,
                event.orb,
                event.score,
                event.phase,
                event.reason,
            )
        return ranked

    def _build_final(self, foreground: List[TransitEvent], max_display: int = DEFAULT_MAX_DISPLAY) -> List[
        TransitEvent]:
        ranked = self._rank_events(foreground)
        final = ranked[:max_display]

        logger.info("=== ФИНАЛЬНЫЙ СПИСОК ===")
        for idx, event in enumerate(final, start=1):
            logger.info(
                "[FINAL %02d] %s -> %s | orb=%.3f score=%.3f phase=%s reason=%s",
                idx,
                event.transit_body,
                event.natal_target,
                event.orb,
                event.score,
                event.phase,
                event.reason,
            )

        self.final_events = final
        return final

    # ----------------------------------------------------------------------
    # PUBLIC PIPELINE
    # ----------------------------------------------------------------------

    def calculate(
        self,
        target_date: Optional[datetime] = None,
        max_display: int = DEFAULT_MAX_DISPLAY,
    ) -> List[TransitEvent]:
        """
        Полный pipeline без генерации текста.

        Удобно для тестов и QA.
        """
        if target_date is None:
            target_date = datetime.now(timezone.utc)

        raw = self._build_raw_events(target_date)

        # Здесь больше НЕТ промежуточных методов, которые могут
        # случайно переписать activity/score.
        classified = self._score_and_classify(raw)

        dedup = self._deduplicate_events(classified)

        foreground, background = self._filter_events(dedup)

        self.background_events = background

        final = self._build_final(
            foreground,
            max_display=max_display,
        )

        self._log_pipeline_summary()

        return final

    # ----------------------------------------------------------------------
    # TEXT FOR LLM
    # ----------------------------------------------------------------------

    def build_context(
            self,
            period: str = "today",
            target_date: Optional[datetime] = None,
            days_range: int = 5,
            max_display: int = DEFAULT_MAX_DISPLAY,
    ) -> str:
        """
        Возвращает контекст для LLM.

        Если включён emulation_mode, возвращается диагностический отчёт
        со всеми сырыми, дедуплицированными, классифицированными
        и финальными событиями.

        Иначе возвращается структурированный текст для интерпретатора.
        """
        if target_date is None:
            target_date = datetime.now(timezone.utc)

        # ======================================================================
        # ЛОГИРОВАНИЕ НАТАЛЬНЫХ ДАННЫХ (всегда в начале лога)
        # ======================================================================
        logger.info("=== НАТАЛЬНЫЕ ДАННЫЕ ===")
        for planet in ("sun", "moon", "mercury", "venus", "mars",
                       "jupiter", "saturn", "uranus", "neptune", "pluto"):
            data = self.natal_planets.get(planet)
            if data:
                sign = data.get("sign", "")
                position = to_float(data.get("position"), 0.0) or 0.0
                house = data.get("house", "")
                retro = " ретроградный" if data.get("retrograde") else ""
                logger.info("  %s: %s %.2f°, %s дом%s",
                            PLANET_RU.get(planet, planet), sign, position, house, retro)

        for angle in ("ascendant", "medium_coeli", "descendant", "imum_coeli"):
            data = self.natal_angles.get(angle)
            if data:
                sign = data.get("sign", "")
                position = to_float(data.get("position"), 0.0) or 0.0
                logger.info("  %s: %s %.2f°", TARGET_RU.get(angle, angle), sign, position)
        logger.info("=== КОНЕЦ НАТАЛЬНЫХ ДАННЫХ ===")

        # Выполняем полный pipeline
        self.calculate(
            target_date=target_date,
            max_display=max_display,
        )

        # Режим эмуляции – отдаём диагностику
        if self.emulation_mode:
            return self._format_emulation_context(
                target_date=target_date,
                period=period,
                days_range=days_range,
            )

        # Обычный режим – контекст для LLM
        return self._format_llm_context(
            target_date=target_date,
            period=period,
            days_range=days_range,
        )

    def _format_emulation_context(
            self,
            target_date: datetime,
            period: str,
            days_range: int,
    ) -> str:
        """
        Диагностический вывод для режима эмуляции.

        Показывает все этапы pipeline:
            RAW → DEDUP → CLASSIFY → FILTER → FINAL
        с полными деталями каждого события.
        """
        lines: List[str] = []

        lines.append("=== ЭМУЛЯЦИЯ РАСЧЁТА ГОРОСКОПА ===")
        lines.append(f"Дата прогноза: {target_date.strftime('%d.%m.%Y')}")
        lines.append(f"Период: {period}")
        lines.append(f"Параметры фильтра: max_display={DEFAULT_MAX_DISPLAY}, "
                     f"foreground_max_orb={FOREGROUND_MAX_ORB}")
        lines.append("")

        # ------------------------------------------------------------------
        # RAW EVENTS
        # ------------------------------------------------------------------

        lines.append(f"=== RAW (всего {len(self.raw_events)}) ===")
        for idx, event in enumerate(self.raw_events):
            lines.append(
                f"{idx + 1:02d}. {event.transit_body} -> {event.natal_target} | "
                f"aspect={event.aspect} | orb={event.orb:.3f} | "
                f"phase={event.phase} | source={event.source_aspect}"
            )

        lines.append("")

        # ------------------------------------------------------------------
        # DEDUP EVENTS
        # ------------------------------------------------------------------

        lines.append(f"=== DEDUP (всего {len(self.dedup_events)}) ===")
        for idx, event in enumerate(self.dedup_events):
            lines.append(
                f"{idx + 1:02d}. {event.transit_body} -> {event.natal_target} | "
                f"aspect={event.aspect} | orb={event.orb:.3f} | "
                f"phase={event.phase} | score={event.score:.3f} | "
                f"activity={event.activity} | reason={event.reason}"
            )

        lines.append("")

        # ------------------------------------------------------------------
        # FOREGROUND EVENTS
        # ------------------------------------------------------------------

        lines.append(f"=== FOREGROUND (всего {len(self.foreground_events)}) ===")
        if not self.foreground_events:
            lines.append("(нет)")
        else:
            for idx, event in enumerate(self.foreground_events):
                lines.append(
                    f"{idx + 1:02d}. {event.transit_body} -> {event.natal_target} | "
                    f"aspect={event.aspect} | orb={event.orb:.3f} | "
                    f"phase={event.phase} | score={event.score:.3f} | "
                    f"reason={event.reason}"
                )

        lines.append("")

        # ------------------------------------------------------------------
        # BACKGROUND EVENTS
        # ------------------------------------------------------------------

        lines.append(f"=== BACKGROUND (всего {len(self.background_events)}) ===")
        if not self.background_events:
            lines.append("(нет)")
        else:
            for idx, event in enumerate(self.background_events):
                lines.append(
                    f"{idx + 1:02d}. {event.transit_body} -> {event.natal_target} | "
                    f"aspect={event.aspect} | orb={event.orb:.3f} | "
                    f"phase={event.phase} | score={event.score:.3f} | "
                    f"reason={event.reason}"
                )

        lines.append("")

        # ------------------------------------------------------------------
        # FINAL EVENTS
        # ------------------------------------------------------------------

        lines.append(f"=== FINAL (всего {len(self.final_events)}) ===")
        if not self.final_events:
            lines.append("(нет)")
        else:
            for idx, event in enumerate(self.final_events):
                lines.append(
                    f"{idx + 1:02d}. {event.transit_body} -> {event.natal_target} | "
                    f"aspect={event.aspect} | orb={event.orb:.3f} | "
                    f"phase={event.phase} | score={event.score:.3f} | "
                    f"reason={event.reason}"
                )

        lines.append("")

        # ------------------------------------------------------------------
        # СТАТИСТИКА
        # ------------------------------------------------------------------

        lines.append("=== СТАТИСТИКА ===")
        lines.append(f"RAW: {len(self.raw_events)}")
        lines.append(f"DEDUP: {len(self.dedup_events)}")
        lines.append(f"FOREGROUND: {len(self.foreground_events)}")
        lines.append(f"BACKGROUND: {len(self.background_events)}")
        lines.append(f"FINAL: {len(self.final_events)}")

        return "\n".join(lines)

    def _format_llm_context(
            self,
            target_date: datetime,
            period: str,
            days_range: int,
    ) -> str:
        # ======================================================================
        # ВЫВОД ДАННЫХ, КОТОРЫЕ ИДУТ В ПРОМПТ (структурированный лог)
        # ======================================================================
        logger.info("=== ДАННЫЕ ИДУТ В ПРОМПТ ===")
        logger.info("Дата прогноза: %s", target_date.strftime('%d.%m.%Y'))
        logger.info("Период: %s", period)

        # --- Натальные планеты ---
        logger.info("--- НАТАЛЬНЫЕ ПЛАНЕТЫ ---")
        for planet in (
                "sun", "moon", "mercury", "venus", "mars",
                "jupiter", "saturn", "uranus", "neptune", "pluto",
        ):
            data = self.natal_planets.get(planet)
            if not data:
                continue
            sign = data.get("sign", "")
            position = to_float(data.get("position"), 0.0) or 0.0
            house = data.get("house", "")
            retrograde = bool(data.get("retrograde", False))
            retro = " ретроградный" if retrograde else ""
            logger.info(
                "  %s: %s %.2f°, %s дом%s",
                PLANET_RU.get(planet, planet),
                sign,
                position,
                house,
                retro,
            )

        # --- Натальные углы ---
        logger.info("--- НАТАЛЬНЫЕ УГЛЫ ---")
        for angle in ("ascendant", "medium_coeli", "descendant", "imum_coeli"):
            data = self.natal_angles.get(angle)
            if not data:
                continue
            sign = data.get("sign", "")
            position = to_float(data.get("position"), 0.0) or 0.0
            logger.info(
                "  %s: %s %.2f°",
                TARGET_RU.get(angle, angle),
                sign,
                position,
            )

        # --- Финальные транзиты ---
        logger.info("--- ФИНАЛЬНЫЕ ТРАНЗИТЫ (всего %d) ---", len(self.final_events))
        for idx, event in enumerate(self.final_events, start=1):
            transit_planet = PLANET_RU.get(event.transit_body, event.transit_body)
            aspect = ASPECT_RU.get(event.aspect, event.aspect)
            target = TARGET_RU.get(event.natal_target, event.natal_target)
            phase = PHASE_RU.get(event.phase, event.phase)
            retro = "да" if event.is_retrograde else "нет"
            logger.info(
                "[%02d] %s %s %s | орб=%.3f | фаза=%s | транзитный дом=%s | натальный дом=%s | ретроградность=%s | score=%.3f | reason=%s",
                idx,
                transit_planet,
                aspect,
                target,
                event.orb,
                phase,
                event.transit_house,
                event.natal_target_house,
                retro,
                event.score,
                event.reason,
            )

        # ======================================================================
        # ФОРМИРОВАНИЕ ТЕКСТА ДЛЯ LLM (без изменений)
        # ======================================================================
        lines: List[str] = []

        lines.append("=== АСТРОЛОГИЧЕСКИЙ КОНТЕКСТ ===")
        lines.append(f"Дата прогноза: {target_date.strftime('%d.%m.%Y')}")
        lines.append(f"Период: {period}")
        lines.append("")

        # ------------------------------------------------------------------
        # NATAL
        # ------------------------------------------------------------------

        lines.append("=== НАТАЛЬНЫЕ ДАННЫЕ ===")

        for angle in (
                "ascendant",
                "medium_coeli",
                "descendant",
                "imum_coeli",
        ):
            data = self.natal_angles.get(angle)
            if not data:
                continue
            sign = data.get("sign", "")
            position = to_float(data.get("position"), 0.0) or 0.0
            lines.append(
                f"{TARGET_RU.get(angle, angle)}: "
                f"{sign} {position:.2f}°"
            )

        for planet in (
                "sun", "moon", "mercury", "venus", "mars",
                "jupiter", "saturn", "uranus", "neptune", "pluto",
        ):
            data = self.natal_planets.get(planet)
            if not data:
                continue
            sign = data.get("sign", "")
            position = to_float(data.get("position"), 0.0) or 0.0
            house = data.get("house", "")
            retrograde = bool(data.get("retrograde", False))
            retro = " ретроградный" if retrograde else ""
            lines.append(
                f"{PLANET_RU.get(planet, planet)}: "
                f"{sign} {position:.2f}°, "
                f"{house} дом{retro}"
            )

        lines.append("")

        # ------------------------------------------------------------------
        # MAJOR TRANSITS
        # ------------------------------------------------------------------

        lines.append("=== ГЛАВНЫЕ ТРАНЗИТЫ ===")

        if not self.final_events:
            lines.append("Нет транзитов, прошедших порог значимости.")
        else:
            for index, event in enumerate(self.final_events, start=1):
                phase = PHASE_RU.get(event.phase, event.phase)
                aspect = ASPECT_RU.get(event.aspect, event.aspect)
                transit_planet = PLANET_RU.get(event.transit_body, event.transit_body)
                target = TARGET_RU.get(event.natal_target, event.natal_target)

                lines.append(
                    f"{index}. "
                    f"{transit_planet} — {aspect} — {target}; "
                    f"орб {event.orb:.2f}°; "
                    f"фаза {phase}; "
                    f"score {event.score:.2f}."
                )

                if event.transit_house:
                    lines.append(f"   Транзитная планета: {event.transit_house} дом.")
                if event.natal_target_house:
                    lines.append(f"   Натальная точка: {event.natal_target_house} дом.")
                if event.is_retrograde:
                    lines.append("   Транзитная планета ретроградна.")
                lines.append(f"   Причина отбора: {event.reason}.")

        lines.append("")

        # ------------------------------------------------------------------
        # BACKGROUND
        # ------------------------------------------------------------------

        lines.append("=== ФОНОВЫЕ ТРАНЗИТЫ ===")

        if not self.background_events:
            lines.append("Нет.")
        else:
            background_sorted = self._rank_events(self.background_events)
            for event in background_sorted[:10]:
                lines.append(
                    f"- "
                    f"{PLANET_RU.get(event.transit_body, event.transit_body)} "
                    f"{ASPECT_RU.get(event.aspect, event.aspect)} "
                    f"{TARGET_RU.get(event.natal_target, event.natal_target)}; "
                    f"орб {event.orb:.2f}°; "
                    f"фаза {PHASE_RU.get(event.phase, event.phase)}; "
                    f"причина: {event.reason}."
                )
            if len(background_sorted) > 10:
                lines.append(
                    f"... ещё {len(background_sorted) - 10} "
                    f"фоновых транзитов не включены."
                )

        lines.append("")

        # ------------------------------------------------------------------
        # INSTRUCTIONS TO LLM
        # ------------------------------------------------------------------

        lines.append("=== ИНСТРУКЦИЯ ДЛЯ ИНТЕРПРЕТАТОРА ===")
        lines.append("Используй главные транзиты как основной материал прогноза.")
        lines.append("Не придумывай транзиты, которых нет в данных.")
        lines.append(
            "Score используется для ранжирования, а не как астрологическое "
            "значение, которое нужно объяснять пользователю."
        )
        lines.append(
            "Не перечисляй все фоновые транзиты подряд. "
            "Используй их только для уточнения контекста."
        )
        lines.append(
            "Учитывай орб и фазу: сходящийся аспект обычно важнее "
            "расходящегося при прочих равных."
        )

        # ======================================================================
        # Возвращаем текст без логирования промпта
        # ======================================================================
        return "\n".join(lines)

    # ----------------------------------------------------------------------
    # QA / DEBUG
    # ----------------------------------------------------------------------

    def _log_pipeline_summary(self) -> None:
        logger.info(
            "[PIPELINE] RAW=%d DEDUP=%d FOREGROUND=%d "
            "BACKGROUND=%d FINAL=%d",
            len(self.raw_events),
            len(self.dedup_events),
            len(self.foreground_events),
            len(self.background_events),
            len(self.final_events),
        )

        for index, event in enumerate(
            self.final_events,
            start=1,
        ):
            logger.info(
                "[FINAL %02d] %s | "
                "orb=%.3f phase=%s score=%.3f "
                "reason=%s",
                index,
                event.display_name,
                event.orb,
                event.phase,
                event.score,
                event.reason,
            )

    def get_stats(self) -> Dict[str, Any]:
        return {
            "raw": len(self.raw_events),
            "dedup": len(self.dedup_events),
            "foreground": len(self.foreground_events),
            "background": len(self.background_events),
            "final": len(self.final_events),
        }

    def get_qa_report(self) -> str:
        lines: List[str] = []

        lines.append("=== HOROSCOPE QA ===")
        lines.append(
            f"RAW: {len(self.raw_events)}"
        )
        lines.append(
            f"DEDUP: {len(self.dedup_events)}"
        )
        lines.append(
            f"FOREGROUND: {len(self.foreground_events)}"
        )
        lines.append(
            f"BACKGROUND: {len(self.background_events)}"
        )
        lines.append(
            f"FINAL: {len(self.final_events)}"
        )
        lines.append("")

        lines.append("=== FINAL EVENTS ===")

        for event in self.final_events:
            lines.append(
                f"{event.transit_body} -> {event.natal_target} "
                f"{event.aspect} "
                f"orb={event.orb:.3f} "
                f"phase={event.phase} "
                f"score={event.score:.3f} "
                f"reason={event.reason}"
            )

        lines.append("")
        lines.append("=== FILTERED OUT ===")

        final_ids = {id(event) for event in self.final_events}

        filtered = [
            event
            for event in self.dedup_events
            if id(event) not in final_ids
        ]

        for event in self._rank_events(filtered):
            lines.append(
                f"{event.transit_body} -> {event.natal_target} "
                f"{event.aspect} "
                f"orb={event.orb:.3f} "
                f"phase={event.phase} "
                f"score={event.score:.3f} "
                f"activity={event.activity} "
                f"reason={event.reason}"
            )

        return "\n".join(lines)
