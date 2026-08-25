import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Tuple, Callable

from kerykeion import AstrologicalSubject, AspectsFactory

from bot.calculators.astrology_calculator import AstrologyCalculator

logger = logging.getLogger(__name__)

# ============================================================================
# 1. КОНФИГУРАЦИЯ
# ============================================================================

# Планеты, которые используем в прогнозе (транзитные)
TRANSIT_PLANETS = {
    'sun', 'moon', 'mercury', 'venus', 'mars',
    'jupiter', 'saturn', 'uranus', 'neptune', 'pluto'
}

# Натальные точки (планеты + углы), к которым анализируем транзиты
NATAL_TARGETS = {
    'sun', 'moon', 'mercury', 'venus', 'mars',
    'jupiter', 'saturn', 'uranus', 'neptune', 'pluto',
    'chiron', 'true_north_lunar_node',
    'ascendant', 'medium_coeli', 'descendant', 'imum_coeli'
}

# Настройки аспектов для Kerykeion (активные аспекты с орбами)
ACTIVE_ASPECTS = [
    {"name": "conjunction", "orb": 5.0},
    {"name": "opposition", "orb": 5.0},
    {"name": "square", "orb": 4.0},
    {"name": "trine", "orb": 4.0},
    {"name": "sextile", "orb": 3.0},
]

# Веса для приоритета
PLANET_WEIGHT = {
    'pluto': 10, 'neptune': 9, 'uranus': 9, 'saturn': 8,
    'jupiter': 7, 'mars': 6, 'venus': 5, 'mercury': 5,
    'sun': 5, 'moon': 4
}

TARGET_WEIGHT = {
    'sun': 10, 'moon': 10, 'ascendant': 10, 'medium_coeli': 9,
    'mercury': 8, 'venus': 8, 'mars': 8,
    'jupiter': 6, 'saturn': 6, 'uranus': 5,
    'neptune': 5, 'pluto': 5,
    'chiron': 3, 'true_north_lunar_node': 3, 'true_south_lunar_node': 3,
    'descendant': 8, 'imum_coeli': 7
}

ASPECT_WEIGHT = {
    'conjunction': 1.0,
    'opposition': 0.95,
    'square': 0.90,
    'trine': 0.85,
    'sextile': 0.75
}

# Окна для классификации активности (дни до/после exact)
# Для поиска exact используется отдельный модуль, здесь оставляем конфиг
TODAY_WINDOW = {'fast': 1.0, 'medium': 2.0, 'slow': 5.0}
APPROACHING_WINDOW = {'fast': 7.0, 'medium': 30.0, 'slow': 90.0}
RECENT_WINDOW = {'fast': 3.0, 'medium': 14.0, 'slow': 60.0}

EXACT_TOLERANCE = 0.01
EPSILON = 0.05

# ============================================================================
# 2. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ РАБОТЫ С KERYKEION
# ============================================================================

def get_attr_safe(obj: Any, *names: str, default=None):
    """Безопасное получение атрибута."""
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def to_float(value: Any, default=None) -> Optional[float]:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_name(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower().replace(" ", "_").replace("'", "")


def get_model_dict(subject: AstrologicalSubject) -> Dict:
    """Извлекает словарь модели из субъекта."""
    model = getattr(subject, "model", None)
    if callable(model):
        model = model()
    if model is None:
        model = subject

    # В Kerykeion 5 модели — Pydantic, поэтому сначала model_dump()
    if hasattr(model, "model_dump"):
        return model.model_dump()
    if hasattr(model, "dict"):
        return model.dict()
    return model.__dict__


def extract_point_dict(subject: AstrologicalSubject, point_name: str) -> Optional[Dict]:
    """Извлекает данные одной планеты/точки."""
    data = get_model_dict(subject)
    point = data.get(point_name)
    if point is None:
        return None
    if isinstance(point, dict):
        return point
    # Если точка — объект, извлекаем нужные поля
    return {
        'sign': get_attr_safe(point, 'sign'),
        'position': to_float(get_attr_safe(point, 'position')),
        'abs_pos': to_float(get_attr_safe(point, 'abs_pos')),
        'house': get_attr_safe(point, 'house'),
        'retrograde': bool(get_attr_safe(point, 'retrograde', False)),
        'speed': to_float(get_attr_safe(point, 'speed')),
    }


def extract_planets_dict(subject: AstrologicalSubject) -> Dict[str, Dict]:
    """Извлекает все планеты в виде словаря {имя: данные}."""
    result = {}
    data = get_model_dict(subject)
    for name in TRANSIT_PLANETS | {'chiron', 'true_north_lunar_node'}:
        point = data.get(name)
        if point:
            result[name] = point if isinstance(point, dict) else {
                'sign': get_attr_safe(point, 'sign'),
                'position': to_float(get_attr_safe(point, 'position')),
                'abs_pos': to_float(get_attr_safe(point, 'abs_pos')),
                'house': get_attr_safe(point, 'house'),
                'retrograde': bool(get_attr_safe(point, 'retrograde', False)),
                'speed': to_float(get_attr_safe(point, 'speed')),
            }
    return result


def extract_angles_dict(subject: AstrologicalSubject) -> Dict[str, Dict]:
    """Извлекает углы (ASC, MC, DSC, IC)."""
    result = {}
    data = get_model_dict(subject)
    for name in ['ascendant', 'medium_coeli', 'descendant', 'imum_coeli']:
        point = data.get(name)
        if point:
            result[name] = point if isinstance(point, dict) else {
                'sign': get_attr_safe(point, 'sign'),
                'position': to_float(get_attr_safe(point, 'position')),
                'abs_pos': to_float(get_attr_safe(point, 'abs_pos')),
            }
    return result


def get_natal_aspects(subject: AstrologicalSubject) -> List[Dict]:
    """Возвращает натальные аспекты через AspectsFactory.single_chart_aspects."""
    try:
        aspects_obj = AspectsFactory.single_chart_aspects(subject, active_aspects=ACTIVE_ASPECTS)
        return list(aspects_obj.aspects) if hasattr(aspects_obj, 'aspects') else []
    except Exception as e:
        logger.warning(f"Ошибка получения натальных аспектов: {e}")
        return []


def get_transit_aspects(
    natal_subject: AstrologicalSubject,
    transit_subject: AstrologicalSubject,
) -> List[Dict]:
    """
    Получение аспектов между натальной и транзитной картой через Kerykeion 5.12.9.
    """
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
        active_aspects=ACTIVE_ASPECTS,   # если используете
    )

    logger.info("Kerykeion transit aspects: %d", len(result.aspects))
    for aspect in result.aspects[:5]:
        logger.info(
            "TRANSIT ASPECT: %s %s %s | orb=%.3f | movement=%s",
            aspect.p1_name,
            aspect.aspect,
            aspect.p2_name,
            aspect.orbit,
            aspect.aspect_movement,
        )

    return list(result.aspects)


# ============================================================================
# 3. DATACLASS TRANSIT EVENT
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
    """
    Калькулятор гороскопа на основе Kerykeion v5.
    Использует AspectsFactory для получения аспектов, а не ручные вычисления.
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

        # Строим натальную карту через существующий AstrologyCalculator
        self.astro_calc = AstrologyCalculator(
            user_data, lang=lang, telegram_id=telegram_id, coords=coords,
            emulation_mode=False
        )
        self.natal_data = self.astro_calc._build_natal_chart()
        self.natal_subject = self.astro_calc._subject  # сохраняем субъект

        # Извлекаем натальные планеты и углы в удобном виде
        self.natal_planets = extract_planets_dict(self.natal_subject)
        self.natal_angles = extract_angles_dict(self.natal_subject)
        self.natal_houses = self.natal_data.get('houses', [])  # для домов

        # Кеш для транзитных субъектов (по дате)
        self._transit_cache = {}

        # Списки событий
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

        # Натальные цели для транзитов
        self.natal_targets = self._build_natal_targets()

    # ------------------- ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ -------------------

    def _build_natal_targets(self) -> List[Dict]:
        """Формирует список натальных целей (планеты + углы)."""
        targets = []
        # Планеты
        for name, data in self.natal_planets.items():
            if name in NATAL_TARGETS:
                targets.append({
                    'name': name,
                    'longitude': data.get('abs_pos', 0.0) % 360.0,
                    'house': data.get('house'),
                    'is_angle': False,
                    'weight': TARGET_WEIGHT.get(name, 5)
                })
        # Углы
        for name, data in self.natal_angles.items():
            targets.append({
                'name': name,
                'longitude': data.get('abs_pos', 0.0) % 360.0,
                'house': None,
                'is_angle': True,
                'weight': TARGET_WEIGHT.get(name, 9)
            })
        return targets

    def _get_transit_subject(self, date: datetime) -> AstrologicalSubject:
        """Создаёт транзитный субъект на заданную дату (UTC)."""
        key = date.strftime('%Y-%m-%d')
        if key in self._transit_cache:
            return self._transit_cache[key]

        lat = self.natal_data['location']['lat']
        lng = self.natal_data['location']['lng']
        subject = AstrologicalSubject(
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
        self._transit_cache[key] = subject
        return subject

    # ------------------- ОСНОВНЫЕ ЭТАПЫ PIPELINE -------------------

    def _calculate_raw_events(self, forecast_date: datetime) -> List[TransitEvent]:
        """
        Этап 1: получение транзитных аспектов через AspectsFactory.
        """
        transit_subject = self._get_transit_subject(forecast_date)
        raw_aspects = get_transit_aspects(self.natal_subject, transit_subject)

        events = []
        for asp in raw_aspects:
            # Определяем, кто транзитная планета, а кто натальная
            p1 = normalize_name(get_attr_safe(asp, 'p1_name'))
            p2 = normalize_name(get_attr_safe(asp, 'p2_name'))
            p1_owner = normalize_name(get_attr_safe(asp, 'p1_owner', ''))
            p2_owner = normalize_name(get_attr_safe(asp, 'p2_owner', ''))

            natal_name = normalize_name(getattr(self.natal_subject, 'name', ''))
            transit_name = normalize_name(getattr(transit_subject, 'name', ''))

            # Идентифицируем натальную и транзитную планеты
            if p1_owner == natal_name and p2_owner == transit_name:
                natal_point, transit_point = p1, p2
            elif p2_owner == natal_name and p1_owner == transit_name:
                natal_point, transit_point = p2, p1
            else:
                # Fallback: если owner не задан, определяем по словарю
                if p1 in NATAL_TARGETS and p2 in TRANSIT_PLANETS:
                    natal_point, transit_point = p1, p2
                elif p2 in NATAL_TARGETS and p1 in TRANSIT_PLANETS:
                    natal_point, transit_point = p2, p1
                else:
                    continue

            # Проверяем, что цель допустима
            if natal_point not in NATAL_TARGETS or transit_point not in TRANSIT_PLANETS:
                continue

            # Извлекаем аспект
            aspect_type = normalize_name(get_attr_safe(asp, 'aspect'))
            if aspect_type not in ASPECT_WEIGHT:
                continue

            orb = to_float(get_attr_safe(asp, 'orbit'))
            if orb is None:
                continue

            aspect_degrees = to_float(get_attr_safe(asp, 'aspect_degrees'))
            movement = str(get_attr_safe(asp, 'aspect_movement', ''))

            # Получаем данные планет
            natal_data = self.natal_planets.get(natal_point) or self.natal_angles.get(natal_point)
            transit_data = extract_point_dict(transit_subject, transit_point)

            if not natal_data or not transit_data:
                continue

            # ---- НОВАЯ ЛОГИКА: вычисляем phase, activity, priority ----
            phase = self._map_aspect_phase(asp)

            activity = self._calculate_activity(
                transit_body=transit_point,
                natal_target=natal_point,
                aspect_name=aspect_type,
                orb=orb,
                phase=phase,
            )

            priority_score = self._calculate_priority(
                transit_body=transit_point,
                natal_target=natal_point,
                aspect_name=aspect_type,
                orb=orb,
                phase=phase,
            )

            # Создаём событие
            event = TransitEvent(
                transit_body=transit_point,
                natal_target=natal_point,
                transit_longitude=transit_data.get('abs_pos', 0.0) % 360.0,
                natal_target_longitude=natal_data.get('abs_pos', 0.0) % 360.0,
                angular_distance=aspect_degrees if aspect_degrees is not None else 0.0,
                aspect=aspect_type,
                aspect_angle=0.0,
                orb=orb,
                transit_speed=transit_data.get('speed', 0.0),
                is_retrograde=transit_data.get('retrograde', False),
                transit_house=transit_data.get('house', 0),
                natal_target_house=natal_data.get('house', 0),
                phase=phase,                     # теперь не unknown
                activity=activity,               # FOREGROUND/BACKGROUND
                priority_score=priority_score,   # ненулевое значение
            )
            events.append(event)

        # Диагностика первых 10 событий
        for i, event in enumerate(events[:10]):
            logger.info(
                "[EVENT %d] transit=%s natal=%s aspect=%s orb=%.3f phase=%s activity=%s priority=%.3f transit_house=%s natal_house=%s",
                i,
                event.transit_body,
                event.natal_target,
                event.aspect,
                event.orb,
                event.phase,
                event.activity,
                event.priority_score,
                event.transit_house,
                event.natal_target_house,
            )

        logger.info(f"[RAW] {len(events)} events")
        self.raw_events = events
        return events

    def _apply_phase_and_peak(self, events: List[TransitEvent], forecast_date: datetime) -> List[TransitEvent]:
        """
        Этап 2: определение фазы и точных дат (упрощённо).
        Здесь можно оставить численный поиск, но теперь мы используем Kerykeion для получения позиций.
        Для краткости оставляем базовую логику.
        """
        for ev in events:
            # Для определения фазы используем Kerykeion на соседних датах
            # (здесь можно реализовать find_exact_pass, но мы оставляем заглушку)
            ev.phase = 'unknown'
            ev.previous_exact = None
            ev.next_exact = None
            ev.nearest_exact = None
            ev.days_to_nearest = 0.0

        self.phase_events = events
        return events

    def _calculate_houses(self, events: List[TransitEvent]) -> List[TransitEvent]:
        """Этап 3: дома уже заполнены из данных Kerykeion."""
        self.house_events = events
        return events

    def _deduplicate_events(self, events: List[TransitEvent]) -> List[TransitEvent]:
        """
        Этап 4: дедупликация по уникальному ключу.
        Оставляем событие с минимальным орбом.
        """
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
        """
        Этап 5: классификация активности и приоритет.
        Используем те же веса и логику, что и раньше.
        """
        for ev in events:
            # Активность (упрощённо)
            if ev.phase == 'unknown':
                ev.activity = 'BACKGROUND'
                ev.filter_reason = 'phase unknown'
                ev.orb_strength = 0.0
                ev.timing_strength = 0.0
                ev.priority_score = 0.0
                continue

            # Определяем активность по дням до exact (если есть)
            # Здесь можно использовать ev.days_to_nearest
            ev.activity = 'BACKGROUND'  # заглушка

            # Приоритет
            planet_w = PLANET_WEIGHT.get(ev.transit_body, 5)
            target_w = TARGET_WEIGHT.get(ev.natal_target, 5)
            aspect_w = ASPECT_WEIGHT.get(ev.aspect, 0.7)
            orb_factor = max(0.0, 1.0 - ev.orb / 5.0)  # упрощённо
            timing = 0.5  # заглушка

            ev.orb_strength = orb_factor
            ev.timing_strength = timing
            ev.priority_score = planet_w * target_w * aspect_w * orb_factor * timing

        self.activity_events = events
        return events

    def _filter_events(self, events: List[TransitEvent]) -> Tuple[List[TransitEvent], List[TransitEvent]]:
        """
        Этап 6: фильтрация — отделяем foreground (значимые) и background.
        activity должно быть 'FOREGROUND' (без учёта регистра).
        """
        foreground = []
        background = []
        for event in events:
            activity = str(getattr(event, "activity", "")).strip().upper()
            if activity == "FOREGROUND":
                foreground.append(event)
            else:
                background.append(event)

        logger.info("[FILTER] foreground=%d, background=%d", len(foreground), len(background))
        self.filtered_events = foreground
        self.background_events = background
        return foreground, background

    def _rank_events(self, events: List[TransitEvent]) -> List[TransitEvent]:
        """
        Этап 7: ранжирование по priority_score (убывание).
        """
        sorted_events = sorted(events, key=lambda x: x.priority_score, reverse=True)
        self.ranked_events = sorted_events
        return sorted_events

    def _build_final(self, events: List[TransitEvent], max_display: int = 12) -> List[TransitEvent]:
        """
        Этап 8: выбор топ-N событий для финального вывода.
        Сначала сортируем по priority_score, затем берём первые max_display.
        """
        sorted_events = sorted(events, key=lambda x: x.priority_score, reverse=True)
        final = sorted_events[:max_display]

        logger.info(f"[FINAL] {len(final)} events (max_display={max_display})")
        self.final_events = final
        self.all_relevant = events  # сохраняем все релевантные для отладки
        return final

    # ------------------- ПУБЛИЧНЫЙ МЕТОД -------------------

    def build_context(self, period: str = 'today',
                      target_date: Optional[datetime] = None,
                      days_range: int = 5) -> str:
        if target_date is None:
            target_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        raw = self._calculate_raw_events(target_date)  # теперь phase, activity, priority заполнены
        phase_events = self._apply_phase_and_peak(raw, target_date)  # (пока заглушка)
        house_events = self._calculate_houses(phase_events)
        dedup = self._deduplicate_events(house_events)  # дедупликация
        activity = self._classify_activity_and_priority(dedup, target_date)  # (может быть избыточно)
        foreground, background = self._filter_events(activity)  # теперь правильно фильтрует
        ranked = self._rank_events(foreground)  # сортировка
        final = self._build_final(ranked, max_display=12)  # выбор топ-12

        self.background_events = background + [e for e in ranked if e not in final]
        self._log_debug_events(final)
        return self._format_context(target_date)

    # ------------------- ЛОГИРОВАНИЕ И ФОРМАТИРОВАНИЕ -------------------

    def _log_debug_events(self, events: List[TransitEvent]):
        for ev in events:
            logger.info(
                f"[DEBUG] {ev.transit_body}->{ev.natal_target} | "
                f"lon={ev.transit_longitude:.2f} target={ev.natal_target_longitude:.2f} "
                f"dist={ev.angular_distance:.2f} aspect={ev.aspect} orb={ev.orb:.4f} "
                f"phase={ev.phase} days={ev.days_to_nearest:.2f} "
                f"activity={ev.activity} score={ev.priority_score:.3f}"
            )

    def _format_context(self, target_date: datetime) -> str:
        lines = []
        lines.append(f"### Прогноз на день")
        lines.append(f"Дата: {target_date.strftime('%d.%m.%Y')}")
        lines.append("")

        lines.append("### Натальные данные")
        lines.append("")
        for angle in ['ascendant', 'medium_coeli', 'descendant', 'imum_coeli']:
            if angle in self.natal_angles:
                data = self.natal_angles[angle]
                sign = data.get('sign', '')
                pos = data.get('position', 0.0)
                name_map = {
                    'ascendant': 'ASC', 'medium_coeli': 'MC',
                    'descendant': 'DSC', 'imum_coeli': 'IC'
                }
                lines.append(f"{name_map.get(angle, angle)}: {sign} {pos:.2f}°")
        lines.append("")
        for name, data in self.natal_planets.items():
            if name in TRANSIT_PLANETS:
                sign = data.get('sign', '')
                deg = data.get('position', 0.0)
                house = data.get('house', 0)
                retro = data.get('retrograde', False)
                line = f"{name.capitalize()}: {sign} {deg:.2f}°, {house} дом"
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
                aspect_names = {'conjunction': 'соединение', 'opposition': 'оппозиция',
                                'trine': 'трин', 'square': 'квадрат', 'sextile': 'секстиль'}
                phase_text = {'applying': 'сходящийся', 'exact': 'точный', 'separating': 'расходящийся'}.get(ev.phase, '')
                aspect_ru = aspect_names.get(ev.aspect, ev.aspect)
                line = f"{ev.transit_body.capitalize()} транзитный — {aspect_ru} — натальное {ev.natal_target.capitalize()}"
                if phase_text:
                    line += f", орб {ev.orb:.2f}°, {phase_text}"
                else:
                    line += f", орб {ev.orb:.2f}°"
                lines.append(line)
                if ev.transit_house:
                    lines.append(f"Транзитная планета активирует {ev.transit_house} дом")
                if ev.natal_target_house:
                    lines.append(f"Натальный {ev.natal_target.capitalize()} находится в {ev.natal_target_house} доме")
                lines.append("")
        return "\n".join(lines)

    # ------------------- QA ОТЧЁТ -------------------

    def get_qa_report(self) -> str:
        target_pairs = [
            ('sun', 'mars'), ('uranus', 'ascendant'), ('pluto', 'ascendant'),
            ('neptune', 'ascendant'), ('mars', 'medium_coeli'), ('neptune', 'medium_coeli')
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
        lines.append("| planet → target | transit_lon | target_lon | angular_dist | aspect | orb | phase | days_to | activity | priority | FINAL |")
        lines.append("|-----------------|-------------|------------|--------------|--------|-----|-------|---------|----------|----------|-------|")
        for key in target_pairs:
            ev = found.get(key)
            if ev:
                is_final = "FINAL" if id(ev) in final_ids else "BACKGROUND"
                lines.append(
                    f"| {ev.transit_body} → {ev.natal_target} | {ev.transit_longitude:.2f} | {ev.natal_target_longitude:.2f} | {ev.angular_distance:.2f} | {ev.aspect} | {ev.orb:.4f} | {ev.phase} | {ev.days_to_nearest:.2f} | {ev.activity} | {ev.priority_score:.3f} | {is_final} |"
                )
            else:
                lines.append(f"| {key[0]} → {key[1]} | - | - | - | - | - | - | - | - | - | НЕ НАЙДЕНО |")
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

    @staticmethod
    def _map_aspect_phase(aspect) -> str:
        """
        Преобразует Kerykeion aspect_movement
        в внутреннее значение phase.
        """
        movement = getattr(aspect, "aspect_movement", None)
        if not movement:
            return "unknown"
        movement = str(movement).strip().lower()
        if movement == "applying":
            return "applying"
        if movement == "separating":
            return "separating"
        if movement in {"static", "stationary"}:
            return "static"
        return "unknown"

    @staticmethod
    def _calculate_activity(
        transit_body: str,
        natal_target: str,
        aspect_name: str,
        orb: float,
        phase: str,
    ) -> str:
        """
        Определяет, является ли транзит значимым для дневного прогноза.
        """
        transit_body = str(transit_body).lower()
        natal_target = str(natal_target).lower()
        aspect_name = str(aspect_name).lower()

        MAJOR_ASPECTS = {"conjunction", "opposition", "square", "trine", "sextile"}
        SLOW_PLANETS = {"jupiter", "saturn", "uranus", "neptune", "pluto"}
        IMPORTANT_POINTS = {"ascendant", "medium_coeli", "descendant", "imum_coeli"}

        if aspect_name not in MAJOR_ASPECTS:
            return "BACKGROUND"
        if orb > 3.0:
            return "BACKGROUND"
        if transit_body in SLOW_PLANETS:
            return "FOREGROUND"
        if natal_target in IMPORTANT_POINTS:
            return "FOREGROUND"
        if orb <= 1.0:
            return "FOREGROUND"
        if phase == "applying" and orb <= 2.0:
            return "FOREGROUND"
        return "BACKGROUND"

    @staticmethod
    def _calculate_priority(
        transit_body: str,
        natal_target: str,
        aspect_name: str,
        orb: float,
        phase: str,
    ) -> float:
        """
        Вычисляет приоритет события.
        """
        transit_body = str(transit_body).lower()
        natal_target = str(natal_target).lower()
        aspect_name = str(aspect_name).lower()

        score = 0.0

        aspect_scores = {
            "conjunction": 4.0,
            "opposition": 4.0,
            "square": 3.5,
            "trine": 3.0,
            "sextile": 2.0,
        }
        score += aspect_scores.get(aspect_name, 0.0)

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

        slow_scores = {
            "pluto": 4.0,
            "neptune": 3.5,
            "uranus": 3.5,
            "saturn": 3.0,
            "jupiter": 2.5,
        }
        score += slow_scores.get(transit_body, 0.0)

        IMPORTANT_POINTS = {"ascendant", "medium_coeli", "descendant", "imum_coeli"}
        if natal_target in IMPORTANT_POINTS:
            score += 4.0

        if natal_target in {"sun", "moon", "mercury", "venus", "mars"}:
            score += 2.0

        if phase == "applying":
            score += 1.5
        elif phase == "separating":
            score += 0.5

        return round(score, 3)