import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from kerykeion import AstrologicalSubject, AspectsFactory

from bot.calculators.astrology_calculator import AstrologyCalculator


logger = logging.getLogger(__name__)


# ============================================================================
# CONFIG
# ============================================================================

TRANSIT_PLANETS = {
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
}

NATAL_TARGETS = {
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
    "ascendant",
    "medium_coeli",
    "descendant",
    "imum_coeli",
}

ACTIVE_ASPECTS = [
    {"name": "conjunction", "orb": 5.0},
    {"name": "opposition", "orb": 5.0},
    {"name": "square", "orb": 4.0},
    {"name": "trine", "orb": 4.0},
    {"name": "sextile", "orb": 3.0},
]


# Планеты, которые считаем долгосрочными
SLOW_PLANETS = {
    "jupiter",
    "saturn",
    "uranus",
    "neptune",
    "pluto",
}

ANGLES = {
    "ascendant",
    "medium_coeli",
    "descendant",
    "imum_coeli",
}

PERSONAL_PLANETS = {
    "sun",
    "moon",
    "mercury",
    "venus",
    "mars",
}

MAJOR_ASPECTS = {
    "conjunction",
    "opposition",
    "square",
    "trine",
    "sextile",
}


# Максимальный орб, который допускаем в prompt.
#
# Важно:
# Kerykeion может вернуть аспекты с orb=4-5 градусов.
# Но далеко не каждый из них должен попадать в AI-промпт.
PROMPT_MAX_ORB = 3.0


# ============================================================================
# HELPERS
# ============================================================================

def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
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


def safe_attr(obj: Any, *names: str, default=None):
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)

    return default


def get_subject_model(subject: AstrologicalSubject):
    model = getattr(subject, "model", None)

    if callable(model):
        return model()

    return model


def model_to_dict(model: Any) -> Dict[str, Any]:
    if model is None:
        return {}

    if hasattr(model, "model_dump"):
        return model.model_dump()

    if hasattr(model, "dict"):
        return model.dict()

    if hasattr(model, "__dict__"):
        return model.__dict__

    return {}


def get_subject_data(subject: AstrologicalSubject) -> Dict[str, Any]:
    return model_to_dict(get_subject_model(subject))


def get_point_data(
    subject: AstrologicalSubject,
    point_name: str,
) -> Optional[Dict[str, Any]]:

    data = get_subject_data(subject)

    point = data.get(point_name)

    if point is None:
        return None

    if isinstance(point, dict):
        return point

    return {
        "sign": safe_attr(point, "sign"),
        "position": safe_float(
            safe_attr(point, "position"),
        ),
        "abs_pos": safe_float(
            safe_attr(point, "abs_pos"),
        ),
        "house": safe_attr(point, "house"),
        "retrograde": bool(
            safe_attr(point, "retrograde", default=False)
        ),
        "speed": safe_float(
            safe_attr(point, "speed"),
        ),
    }


# ============================================================================
# TRANSIT EVENT
# ============================================================================

@dataclass
class TransitEvent:

    transit_body: str
    natal_target: str

    transit_longitude: float
    natal_longitude: float

    aspect: str
    aspect_angle: float
    orb: float

    phase: str

    transit_house: Optional[Any]
    natal_house: Optional[Any]

    retrograde: bool
    transit_speed: float

    score: float = 0.0

    # Это только объяснение для диагностики.
    filter_reason: str = ""

    # Не используем как источник истины.
    activity: str = "BACKGROUND"

    @property
    def key(self) -> Tuple[str, str, str]:
        return (
            self.transit_body,
            self.natal_target,
            self.aspect,
        )


# ============================================================================
# HOROSCOPE CALCULATOR
# ============================================================================

class HoroscopeCalculator:

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

        self.astro_calc = AstrologyCalculator(
            user_data,
            lang=lang,
            telegram_id=telegram_id,
            coords=coords,
            emulation_mode=False,
        )

        self.natal_data = self.astro_calc._build_natal_chart()
        self.natal_subject = self.astro_calc._subject

        logger.info(
            "Natal subject: %s",
            getattr(self.natal_subject, "name", "?"),
        )

        self.natal_points = self._extract_natal_points()

        self._transit_cache: Dict[str, AstrologicalSubject] = {}

        self.raw_events: List[TransitEvent] = []
        self.dedup_events: List[TransitEvent] = []
        self.filtered_events: List[TransitEvent] = []
        self.background_events: List[TransitEvent] = []
        self.final_events: List[TransitEvent] = []

    # ========================================================================
    # NATAL DATA
    # ========================================================================

    def _extract_natal_points(self) -> Dict[str, Dict[str, Any]]:

        result = {}

        data = get_subject_data(self.natal_subject)

        for name in NATAL_TARGETS:

            point = data.get(name)

            if point is None:
                continue

            if isinstance(point, dict):
                result[name] = point
            else:
                result[name] = {
                    "sign": safe_attr(point, "sign"),
                    "position": safe_float(
                        safe_attr(point, "position")
                    ),
                    "abs_pos": safe_float(
                        safe_attr(point, "abs_pos")
                    ),
                    "house": safe_attr(point, "house"),
                    "retrograde": bool(
                        safe_attr(
                            point,
                            "retrograde",
                            default=False,
                        )
                    ),
                    "speed": safe_float(
                        safe_attr(point, "speed")
                    ),
                }

        logger.info(
            "Natal points extracted: %d",
            len(result),
        )

        return result

    # ========================================================================
    # TRANSIT SUBJECT
    # ========================================================================

    def _get_transit_subject(
        self,
        date: datetime,
    ) -> AstrologicalSubject:

        # Кеш должен учитывать время.
        key = date.strftime("%Y-%m-%d-%H-%M")

        if key in self._transit_cache:
            return self._transit_cache[key]

        location = self.natal_data.get("location", {})

        lat = safe_float(location.get("lat"))
        lng = safe_float(location.get("lng"))

        subject = AstrologicalSubject(
            name="Transit",
            year=date.year,
            month=date.month,
            day=date.day,
            hour=date.hour,
            minute=date.minute,
            lat=lat,
            lng=lng,
            tz_str="UTC",
        )

        self._transit_cache[key] = subject

        return subject

    # ========================================================================
    # KERYKEION
    # ========================================================================

    def _get_transit_aspects(
        self,
        transit_subject: AstrologicalSubject,
    ):

        natal_model = get_subject_model(self.natal_subject)
        transit_model = get_subject_model(transit_subject)

        result = AspectsFactory.dual_chart_aspects(
            natal_model,
            transit_model,
            first_subject_is_fixed=True,
            second_subject_is_fixed=False,
            active_aspects=ACTIVE_ASPECTS,
        )

        aspects = list(
            getattr(result, "aspects", [])
        )

        logger.info(
            "Kerykeion transit aspects: %d",
            len(aspects),
        )

        return aspects

    # ========================================================================
    # PHASE
    # ========================================================================

    @staticmethod
    def _normalize_phase(value: Any) -> str:

        value = str(value or "").strip().lower()

        if value == "applying":
            return "applying"

        if value == "separating":
            return "separating"

        if value in {"static", "stationary"}:
            return "static"

        return "unknown"

    # ========================================================================
    # ACTIVITY
    # ========================================================================

    @staticmethod
    def _is_foreground(
        transit_body: str,
        natal_target: str,
        aspect: str,
        orb: float,
        phase: str,
    ) -> Tuple[bool, str]:

        # ------------------------------------------------------------
        # 1. Только major aspects
        # ------------------------------------------------------------

        if aspect not in MAJOR_ASPECTS:
            return False, "non_major_aspect"

        # ------------------------------------------------------------
        # 2. Слишком большой орб
        # ------------------------------------------------------------

        if orb > PROMPT_MAX_ORB:
            return False, f"orb_too_wide:{orb:.2f}"

        # ------------------------------------------------------------
        # 3. Медленные планеты
        #
        # Они особенно важны для прогноза.
        # ------------------------------------------------------------

        if transit_body in SLOW_PLANETS:

            if natal_target in ANGLES:
                return True, "slow_planet_to_angle"

            if orb <= 2.0:
                return True, "slow_planet_tight_orb"

            if phase == "applying":
                return True, "slow_planet_applying"

        # ------------------------------------------------------------
        # 4. Транзиты к углам
        # ------------------------------------------------------------

        if natal_target in ANGLES:

            if orb <= 2.0:
                return True, "angle_tight_orb"

            if phase == "applying" and orb <= 3.0:
                return True, "angle_applying"

        # ------------------------------------------------------------
        # 5. Очень точные транзиты
        # ------------------------------------------------------------

        if orb <= 1.0:
            return True, "very_tight_orb"

        # ------------------------------------------------------------
        # 6. Applying до 2°
        # ------------------------------------------------------------

        if phase == "applying" and orb <= 2.0:
            return True, "applying_tight"

        return False, "ordinary_background"

    # ========================================================================
    # SCORE
    # ========================================================================

    @staticmethod
    def _score(
        transit_body: str,
        natal_target: str,
        aspect: str,
        orb: float,
        phase: str,
    ) -> float:

        score = 0.0

        # aspect
        score += {
            "conjunction": 4.0,
            "opposition": 4.0,
            "square": 3.5,
            "trine": 3.0,
            "sextile": 2.0,
        }.get(aspect, 0.0)

        # orb
        if orb <= 0.1:
            score += 5.0
        elif orb <= 0.5:
            score += 4.0
        elif orb <= 1.0:
            score += 3.0
        elif orb <= 2.0:
            score += 2.0
        elif orb <= 3.0:
            score += 1.0

        # slow planets
        score += {
            "pluto": 4.0,
            "neptune": 3.5,
            "uranus": 3.5,
            "saturn": 3.0,
            "jupiter": 2.5,
        }.get(transit_body, 0.0)

        # angles
        if natal_target in ANGLES:
            score += 4.0

        # personal planets
        if natal_target in PERSONAL_PLANETS:
            score += 2.0

        # phase
        if phase == "applying":
            score += 1.5

        elif phase == "separating":
            score += 0.5

        return round(score, 3)

    # ========================================================================
    # RAW EVENTS
    # ========================================================================

    def _calculate_raw_events(
        self,
        forecast_date: datetime,
    ) -> List[TransitEvent]:

        transit_subject = self._get_transit_subject(
            forecast_date
        )

        aspects = self._get_transit_aspects(
            transit_subject
        )

        events = []

        natal_name = normalize_name(
            getattr(
                self.natal_subject,
                "name",
                "",
            )
        )

        transit_name = normalize_name(
            getattr(
                transit_subject,
                "name",
                "",
            )
        )

        for asp in aspects:

            p1 = normalize_name(
                safe_attr(asp, "p1_name")
            )

            p2 = normalize_name(
                safe_attr(asp, "p2_name")
            )

            p1_owner = normalize_name(
                safe_attr(asp, "p1_owner")
            )

            p2_owner = normalize_name(
                safe_attr(asp, "p2_owner")
            )

            # ------------------------------------------------------------
            # Определяем natal/transit
            # ------------------------------------------------------------

            if (
                p1_owner == natal_name
                and p2_owner == transit_name
            ):
                natal_target = p1
                transit_body = p2

            elif (
                p2_owner == natal_name
                and p1_owner == transit_name
            ):
                natal_target = p2
                transit_body = p1

            else:

                if (
                    p1 in NATAL_TARGETS
                    and p2 in TRANSIT_PLANETS
                ):
                    natal_target = p1
                    transit_body = p2

                elif (
                    p2 in NATAL_TARGETS
                    and p1 in TRANSIT_PLANETS
                ):
                    natal_target = p2
                    transit_body = p1

                else:
                    continue

            # ------------------------------------------------------------
            # Проверки
            # ------------------------------------------------------------

            if natal_target not in NATAL_TARGETS:
                continue

            if transit_body not in TRANSIT_PLANETS:
                continue

            aspect = normalize_name(
                safe_attr(asp, "aspect")
            )

            if aspect not in MAJOR_ASPECTS:
                continue

            orb = safe_float(
                safe_attr(asp, "orbit"),
                default=999.0,
            )

            if orb > 5.0:
                continue

            phase = self._normalize_phase(
                safe_attr(
                    asp,
                    "aspect_movement",
                )
            )

            # ------------------------------------------------------------
            # Natal data
            # ------------------------------------------------------------

            natal_data = self.natal_points.get(
                natal_target
            )

            if not natal_data:
                continue

            transit_data = get_point_data(
                transit_subject,
                transit_body,
            )

            if not transit_data:
                continue

            transit_lon = (
                safe_float(
                    transit_data.get("abs_pos")
                )
                % 360.0
            )

            natal_lon = (
                safe_float(
                    natal_data.get("abs_pos")
                )
                % 360.0
            )

            aspect_angle = safe_float(
                safe_attr(
                    asp,
                    "aspect_degrees",
                )
            )

            is_foreground, reason = self._is_foreground(
                transit_body=transit_body,
                natal_target=natal_target,
                aspect=aspect,
                orb=orb,
                phase=phase,
            )

            score = self._score(
                transit_body=transit_body,
                natal_target=natal_target,
                aspect=aspect,
                orb=orb,
                phase=phase,
            )

            event = TransitEvent(
                transit_body=transit_body,
                natal_target=natal_target,

                transit_longitude=transit_lon,
                natal_longitude=natal_lon,

                aspect=aspect,
                aspect_angle=aspect_angle,
                orb=orb,

                phase=phase,

                transit_house=transit_data.get(
                    "house"
                ),

                natal_house=natal_data.get(
                    "house"
                ),

                retrograde=bool(
                    transit_data.get(
                        "retrograde",
                        False,
                    )
                ),

                transit_speed=safe_float(
                    transit_data.get("speed")
                ),

                score=score,

                filter_reason=reason,

                activity=(
                    "FOREGROUND"
                    if is_foreground
                    else "BACKGROUND"
                ),
            )

            events.append(event)

        logger.info(
            "[RAW] %d events",
            len(events),
        )

        self.raw_events = events

        return events

    # ========================================================================
    # DEDUP
    # ========================================================================

    def _deduplicate(
        self,
        events: List[TransitEvent],
    ) -> List[TransitEvent]:

        result = []
        seen = set()

        for event in events:

            key = event.key

            if key in seen:
                continue

            seen.add(key)
            result.append(event)

        logger.info(
            "[DEDUP] %d from %d",
            len(result),
            len(events),
        )

        self.dedup_events = result

        return result

    # ========================================================================
    # FILTER
    # ========================================================================

    def _filter(
        self,
        events: List[TransitEvent],
    ) -> Tuple[
        List[TransitEvent],
        List[TransitEvent],
    ]:

        """
            Единственная точка классификации событий.

            Каждый event должен попасть ровно в одну категорию:
            FOREGROUND или BACKGROUND.
            """

        foreground: List[TransitEvent] = []
        background: List[TransitEvent] = []

        for i, event in enumerate(events):

            activity = str(
                getattr(event, "activity", "")
            ).strip().upper()

            transit = str(
                getattr(event, "transit_planet", "")
            ).strip().lower()

            natal = str(
                getattr(event, "natal_planet", "")
            ).strip().lower()

            aspect = str(
                getattr(event, "aspect", "")
            ).strip().lower()

            orb = float(
                getattr(event, "orb", 999.0) or 999.0
            )

            score = float(
                getattr(event, "priority", 0.0) or 0.0
            )

            logger.info(
                "[FILTER INPUT %02d] "
                "%s -> %s %s | "
                "orb=%.3f | activity=%r | priority=%.3f",
                i,
                transit,
                natal,
                aspect,
                orb,
                activity,
                score,
            )

            if activity == "FOREGROUND":
                foreground.append(event)

                logger.info(
                    "[FILTER DECISION %02d] FOREGROUND",
                    i,
                )

            else:
                background.append(event)

                logger.info(
                    "[FILTER DECISION %02d] BACKGROUND",
                    i,
                )

        # ЖЁСТКАЯ проверка:
        # каждый event должен находиться только в одном списке.
        assert len(foreground) + len(background) == len(events), (
            f"FILTER BUG: "
            f"foreground={len(foreground)}, "
            f"background={len(background)}, "
            f"events={len(events)}"
        )

        logger.info(
            "[FILTER RESULT] "
            "input=%d foreground=%d background=%d",
            len(events),
            len(foreground),
            len(background),
        )

        self.filtered_events = foreground
        self.background_events = background

        return foreground, background

    # ========================================================================
    # RANK
    # ========================================================================

    def _rank(
        self,
        events: List[TransitEvent],
    ) -> List[TransitEvent]:

        ranked = sorted(
            events,
            key=lambda event: event.score,
            reverse=True,
        )

        return ranked

    # ========================================================================
    # FINAL
    # ========================================================================

    def _build_final(
        self,
        events: List[TransitEvent],
        max_display: int = 12,
    ) -> List[TransitEvent]:

        ranked = self._rank(events)

        final = ranked[:max_display]

        self.final_events = final

        logger.info(
            "[FINAL] %d events",
            len(final),
        )

        for i, event in enumerate(final):

            logger.info(
                "[FINAL EVENT %d] "
                "%s -> %s | %s | orb=%.3f | "
                "phase=%s | score=%.3f | reason=%s",
                i,
                event.transit_body,
                event.natal_target,
                event.aspect,
                event.orb,
                event.phase,
                event.score,
                event.filter_reason,
            )

        return final

    # ========================================================================
    # PROMPT CONTEXT
    # ========================================================================

    def _format_prompt_context(
        self,
        target_date: datetime,
    ) -> str:

        lines = []

        lines.append(
            "## АСТРОЛОГИЧЕСКИЙ КОНТЕКСТ"
        )

        lines.append(
            f"Дата прогноза: "
            f"{target_date.strftime('%d.%m.%Y')}"
        )

        lines.append("")

        # ------------------------------------------------------------
        # Натальные точки
        # ------------------------------------------------------------

        lines.append(
            "### Натальные положения"
        )

        natal_order = [
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
            "ascendant",
            "medium_coeli",
            "descendant",
            "imum_coeli",
        ]

        for name in natal_order:

            data = self.natal_points.get(name)

            if not data:
                continue

            sign = data.get(
                "sign",
                "",
            )

            position = safe_float(
                data.get("position")
            )

            house = data.get(
                "house"
            )

            lines.append(
                f"- {name}: "
                f"{sign} {position:.2f}°"
                + (
                    f", дом {house}"
                    if house
                    else ""
                )
            )

        lines.append("")

        # ------------------------------------------------------------
        # Основные транзиты
        # ------------------------------------------------------------

        lines.append(
            "### Значимые транзиты"
        )

        if not self.final_events:

            lines.append(
                "Значимых транзитов не обнаружено."
            )

        else:

            for event in self.final_events:

                lines.append(
                    f"- "
                    f"{event.transit_body} "
                    f"{event.aspect} "
                    f"{event.natal_target}; "
                    f"orb={event.orb:.2f}°; "
                    f"phase={event.phase}; "
                    f"score={event.score:.1f}"
                )

                if event.transit_house:
                    lines.append(
                        f"  транзитный дом: "
                        f"{event.transit_house}"
                    )

                if event.natal_house:
                    lines.append(
                        f"  натальный дом цели: "
                        f"{event.natal_house}"
                    )

                if event.retrograde:
                    lines.append(
                        "  транзитная планета ретроградна"
                    )

        lines.append("")

        # ------------------------------------------------------------
        # Статистика
        # ------------------------------------------------------------

        lines.append(
            "### Статистика обработки"
        )

        lines.append(
            f"- Kerykeion aspects: "
            f"{len(self.raw_events)}"
        )

        lines.append(
            f"- после dedup: "
            f"{len(self.dedup_events)}"
        )

        lines.append(
            f"- значимых: "
            f"{len(self.filtered_events)}"
        )

        lines.append(
            f"- передано в prompt: "
            f"{len(self.final_events)}"
        )

        return "\n".join(lines)

    # ========================================================================
    # PUBLIC
    # ========================================================================

    def build_context(
        self,
        period: str = "today",
        target_date: Optional[datetime] = None,
        days_range: int = 5,
        max_display: int = 12,
    ) -> str:

        if target_date is None:

            target_date = (
                datetime.now(timezone.utc)
                .replace(
                    hour=0,
                    minute=0,
                    second=0,
                    microsecond=0,
                )
            )

        logger.info(
            "Building horoscope context for %s",
            target_date.isoformat(),
        )

        # 1. Kerykeion
        raw = self._calculate_raw_events(
            target_date
        )

        # 2. Dedup
        dedup = self._deduplicate(raw)

        # 3. Deterministic filter
        foreground, background = self._filter(
            dedup
        )

        # 4. Ranking
        ranked = self._rank(
            foreground
        )

        # 5. Final
        self._build_final(
            ranked,
            max_display=max_display,
        )

        # Остальные foreground, которые не вошли
        # в prompt, тоже считаем background для UI.
        self.background_events = (
            background
            + ranked[max_display:]
        )

        logger.info(
            "[PIPELINE] raw=%d dedup=%d "
            "foreground=%d background=%d final=%d",
            len(self.raw_events),
            len(self.dedup_events),
            len(self.filtered_events),
            len(self.background_events),
            len(self.final_events),
        )

        return self._format_prompt_context(
            target_date
        )

    # ========================================================================
    # QA
    # ========================================================================

    def get_qa_report(self) -> str:

        lines = []

        lines.append(
            "=== HOROSCOPE QA ==="
        )

        lines.append("")

        lines.append(
            f"RAW: {len(self.raw_events)}"
        )

        lines.append(
            f"DEDUP: {len(self.dedup_events)}"
        )

        lines.append(
            f"FOREGROUND: {len(self.filtered_events)}"
        )

        lines.append(
            f"BACKGROUND: {len(self.background_events)}"
        )

        lines.append(
            f"FINAL: {len(self.final_events)}"
        )

        lines.append("")

        lines.append(
            "=== FINAL EVENTS ==="
        )

        for event in self.final_events:

            lines.append(
                f"{event.transit_body} -> "
                f"{event.natal_target} "
                f"{event.aspect} "
                f"orb={event.orb:.3f} "
                f"phase={event.phase} "
                f"score={event.score:.3f} "
                f"reason={event.filter_reason}"
            )

        lines.append("")

        lines.append(
            "=== FILTERED OUT ==="
        )

        for event in self.background_events:

            lines.append(
                f"{event.transit_body} -> "
                f"{event.natal_target} "
                f"{event.aspect} "
                f"orb={event.orb:.3f} "
                f"phase={event.phase} "
                f"reason={event.filter_reason}"
            )

        return "\n".join(lines)