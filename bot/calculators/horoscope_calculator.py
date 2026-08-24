import logging
import zoneinfo
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Tuple
import math

from kerykeion import AstrologicalSubject

from bot.calculators.astrology_calculator import AstrologyCalculator
from bot.calculators.natal_context_builder import NatalContextBuilder

logger = logging.getLogger(__name__)


class HoroscopeCalculator:
    """
    Калькулятор гороскопа на день с корректным расчётом аспектов и exact_datetime.
    """

    # Маппинг знаков → начальная долгота (0-360)
    SIGN_OFFSET = {
        'Aries': 0, 'Taurus': 30, 'Gemini': 60, 'Cancer': 90,
        'Leo': 120, 'Virgo': 150, 'Libra': 180, 'Scorpio': 210,
        'Sagittarius': 240, 'Capricorn': 270, 'Aquarius': 300, 'Pisces': 330
    }

    # Максимальные орбы для поиска
    MAX_ORBS = {
        'conjunction': 6.0,
        'opposition': 6.0,
        'trine': 6.0,
        'square': 6.0,
        'sextile': 5.0,
    }

    # Группы планет для скоринга
    GROUP_A = {'Saturn', 'Uranus', 'Neptune', 'Pluto', 'Jupiter'}
    GROUP_B = {'Mars', 'Venus', 'Mercury', 'Sun'}
    GROUP_C = {'Moon'}

    # Веса для скоринга
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

    # Точные углы аспектов
    ASPECT_ANGLES = {
        'conjunction': 0,
        'sextile': 60,
        'square': 90,
        'trine': 120,
        'opposition': 180,
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

        # Получаем натальную карту
        self.astro_calc = AstrologyCalculator(
            user_data, lang=lang, telegram_id=telegram_id, coords=coords,
            emulation_mode=False
        )
        self.natal_data = self.astro_calc._build_natal_chart()
        self.subject = self.astro_calc._subject

        self.natal_planets = self.natal_data['planets']
        self.natal_angles = self.natal_data['angles']
        self.natal_houses = self.natal_data['houses']

        # Строим список натальных целей
        self.natal_targets = self._build_natal_targets()

        # Кеш транзитных позиций
        self._transit_cache = {}

        # Результаты расчёта
        self.all_transits = []
        self.filtered_transits = []

    def _build_natal_targets(self) -> List[Dict]:
        """Строит список натальных целей с абсолютными долготами."""
        targets = []

        # Основные планеты
        main_names = {'Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                      'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto'}
        for p in self.natal_planets:
            if p['name'] in main_names:
                targets.append({
                    'name': p['name'],
                    'longitude': self._sign_to_abs(p['sign'], p['degree']),
                    'house': p['house'],
                    'is_angle': False,
                    'extra_type': None,
                    'weight': self.TARGET_WEIGHT.get(p['name'], 5)
                })

        # Углы
        angle_names = ['ASC', 'MC', 'DSC', 'IC']
        for angle in angle_names:
            if angle in self.natal_angles and self.natal_angles[angle] is not None:
                a = self.natal_angles[angle]
                targets.append({
                    'name': angle,
                    'longitude': self._sign_to_abs(a['sign'], a['position']),
                    'house': None,
                    'is_angle': True,
                    'extra_type': 'angle',
                    'weight': self.TARGET_WEIGHT.get(angle, 9)
                })

        # Дополнительные точки
        extra_names = ['True_North_Lunar_Node', 'True_South_Lunar_Node', 'Chiron', 'True_Lilith']
        for p in self.natal_planets:
            if p['name'] in extra_names:
                extra_type = 'node' if 'Node' in p['name'] else 'chiron' if p['name'] == 'Chiron' else 'lilith'
                targets.append({
                    'name': p['name'],
                    'longitude': self._sign_to_abs(p['sign'], p['degree']),
                    'house': p.get('house'),
                    'is_angle': False,
                    'extra_type': extra_type,
                    'weight': 3
                })

        return targets

    # ========== ГЕОМЕТРИЯ ==========

    def _sign_to_abs(self, sign: str, degree: float) -> float:
        """Преобразует знак + градус в абсолютную долготу (0-360)."""
        start = self.SIGN_OFFSET.get(sign, 0)
        if degree >= 30:
            return degree % 360
        return start + degree

    def _angular_distance(self, lon1: float, lon2: float) -> float:
        """Возвращает минимальное угловое расстояние (0-180)."""
        diff = abs(lon1 - lon2) % 360
        if diff > 180:
            diff = 360 - diff
        return diff

    def _aspect_info(self, angle: float) -> Tuple[Optional[str], float]:
        """
        Определяет ближайший аспект и орб.
        Возвращает (aspect_type, orb) или (None, inf) если аспект не определён.
        """
        best_aspect = None
        best_orb = 360.0
        for aspect, target_angle in self.ASPECT_ANGLES.items():
            orb = abs(angle - target_angle)
            if orb < best_orb:
                best_orb = orb
                best_aspect = aspect
        # Если минимальный орб слишком большой (> 10°), считаем, что аспекта нет
        if best_orb > 10.0:
            return None, best_orb
        return best_aspect, best_orb

    def _aspect_error(self, lon1: float, lon2: float, aspect_angle: float) -> float:
        """Возвращает ошибку аспекта (отклонение от точного угла)."""
        angle = self._angular_distance(lon1, lon2)
        return angle - aspect_angle

    def _find_exact_datetime(self, planet: str, target_lon: float, aspect_angle: float,
                             start_date: datetime, end_date: datetime) -> Optional[datetime]:
        """
        Находит точное время аспекта с помощью бинарного поиска.
        Возвращает datetime или None, если аспект не найден.
        """
        # Проверяем, что на концах интервала ошибка имеет разные знаки
        start_pos = self._get_transit_position(start_date, planet)
        end_pos = self._get_transit_position(end_date, planet)

        if start_pos is None or end_pos is None:
            return None

        start_error = self._aspect_error(start_pos, target_lon, aspect_angle)
        end_error = self._aspect_error(end_pos, target_lon, aspect_angle)

        # Если ошибка имеет одинаковый знак на обоих концах, значит аспекта нет в этом интервале
        if start_error * end_error > 0 and abs(start_error) > 0.1 and abs(end_error) > 0.1:
            # Проверяем, не было ли пересечения через 0/360
            # В этом случае ищем отдельно
            pass

        eps = 0.0001  # точность 0.0001 градуса (~0.36 секунды)
        max_iter = 100

        left = start_date
        right = end_date
        left_error = start_error
        right_error = end_error

        # Если на концах ошибка не разных знаков, но одна из них близка к 0, ищем экстремум
        if left_error * right_error > 0:
            # Ищем минимум абсолютной ошибки
            for _ in range(max_iter):
                mid = left + (right - left) / 2
                mid_pos = self._get_transit_position(mid, planet)
                if mid_pos is None:
                    break
                mid_error = self._aspect_error(mid_pos, target_lon, aspect_angle)

                if abs(mid_error) < eps:
                    return mid

                # Двигаемся в сторону уменьшения ошибки
                if abs(mid_error) < abs(left_error):
                    left = mid
                    left_error = mid_error
                else:
                    right = mid
                    right_error = mid_error

                if abs(left_error) < eps:
                    return left
                if abs(right_error) < eps:
                    return right

                if (right - left).total_seconds() < 60:  # меньше минуты
                    break

            # Возвращаем точку с минимальной ошибкой
            if abs(left_error) < abs(right_error):
                return left
            else:
                return right

        # Классический бинарный поиск (разные знаки)
        for _ in range(max_iter):
            mid = left + (right - left) / 2
            mid_pos = self._get_transit_position(mid, planet)
            if mid_pos is None:
                break
            mid_error = self._aspect_error(mid_pos, target_lon, aspect_angle)

            if abs(mid_error) < eps:
                return mid

            if left_error * mid_error < 0:
                right = mid
                right_error = mid_error
            else:
                left = mid
                left_error = mid_error

            if (right - left).total_seconds() < 60:
                break

        # Возвращаем точку с минимальной ошибкой
        if abs(left_error) < abs(right_error):
            return left
        else:
            return right

    def _get_transit_position(self, date: datetime, planet: str) -> Optional[float]:
        """Возвращает абсолютную долготу транзитной планеты на указанную дату."""
        positions = self._get_transit_positions(date)
        return positions.get(planet)

    # ========== ТРАНЗИТНЫЕ ПОЗИЦИИ ==========

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
                        positions[planet] = self._sign_to_abs(sign, degree)
                else:
                    if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                        sign = getattr(obj, 'sign', '')
                        degree = getattr(obj, 'position', 0.0)
                        if sign:
                            positions[planet] = self._sign_to_abs(sign, degree)

        self._transit_cache[key] = positions
        return positions

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

    # ========== РАСЧЁТ ТРАНЗИТОВ ==========

    def _calculate_all_transits(self, forecast_date: datetime, days_range: int = 5) -> List[Dict]:
        """
        Рассчитывает все транзиты для заданной даты с учётом ±days_range.
        Возвращает список с exact_datetime и всеми метаданными.
        """
        start = forecast_date - timedelta(days=days_range)
        end = forecast_date + timedelta(days=days_range)

        # Собираем позиции для всех дней в диапазоне
        days = []
        current = start
        while current <= end:
            positions = self._get_transit_positions(current)
            days.append({'date': current, 'positions': positions})
            current += timedelta(days=1)

        if len(days) < 2:
            return []

        transits = []

        for target in self.natal_targets:
            t_lon = target['longitude']
            for planet in ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                           'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']:
                # Проверяем, есть ли позиции планеты
                has_position = any(planet in day['positions'] for day in days)
                if not has_position:
                    continue

                # Для каждого аспекта ищем точную дату
                for aspect, aspect_angle in self.ASPECT_ANGLES.items():
                    # Ищем точную дату в диапазоне
                    exact_dt = self._find_exact_datetime(
                        planet, t_lon, aspect_angle,
                        start, end
                    )

                    if exact_dt is None:
                        continue

                    # Вычисляем орб на дату прогноза
                    forecast_pos = self._get_transit_position(forecast_date, planet)
                    if forecast_pos is None:
                        continue

                    # Вычисляем угловое расстояние между транзитной и натальной точкой
                    angle = self._angular_distance(forecast_pos, t_lon)
                    aspect_type, orb = self._aspect_info(angle)

                    # Проверяем, что аспект совпадает с тем, который мы искали
                    if aspect_type != aspect:
                        # Это может быть из-за того, что мы искали точный аспект другого типа.
                        # Для найденного точного момента мы должны использовать фактический тип аспекта.
                        # Поэтому переопределяем aspect и орб.
                        aspect = aspect_type
                        orb = abs(angle - self.ASPECT_ANGLES[aspect_type])

                    # Проверяем максимальный орб
                    max_orb = self.MAX_ORBS.get(aspect, 6.0)
                    if orb > max_orb:
                        continue

                    # Определяем фазу (applying/separating)
                    # Проверяем орб за день до и после
                    date_before = exact_dt - timedelta(days=1)
                    date_after = exact_dt + timedelta(days=1)

                    pos_before = self._get_transit_position(date_before, planet)
                    pos_after = self._get_transit_position(date_after, planet)

                    phase = 'exact'
                    if pos_before is not None and pos_after is not None:
                        error_before = self._aspect_error(pos_before, t_lon, aspect_angle)
                        error_after = self._aspect_error(pos_after, t_lon, aspect_angle)

                        if abs(error_before) < abs(error_after):
                            phase = 'separating'
                        elif abs(error_before) > abs(error_after):
                            phase = 'applying'

                    # Определяем статус относительно даты прогноза
                    delta = exact_dt - forecast_date
                    delta_hours = delta.total_seconds() / 3600

                    if abs(delta_hours) < 12:
                        status = 'today'
                    elif delta_hours > 0 and delta_hours < 36:
                        status = 'tomorrow'
                    elif delta_hours > 0:
                        status = 'future'
                    elif delta_hours < 0 and delta_hours > -36:
                        status = 'yesterday'
                    else:
                        status = 'past'

                    # Проверяем активность на дату прогноза
                    is_active = orb < self.MAX_ORBS.get(aspect, 6.0)

                    # Вычисляем score
                    score = self._calculate_score(
                        planet, target, aspect, orb, phase, status, is_active
                    )

                    transits.append({
                        'transit_planet': planet,
                        'natal_target': target['name'],
                        'aspect': aspect,
                        'orb': orb,
                        'phase': phase,
                        'exact_datetime': exact_dt,
                        'forecast_datetime': forecast_date,
                        'delta_hours': delta_hours,
                        'status': status,
                        'is_active': is_active,
                        'transit_house': self._get_transit_house(forecast_date, planet),
                        'natal_house': target['house'],
                        'is_angle': target['is_angle'],
                        'extra_type': target['extra_type'],
                        'score': score,
                        'target_weight': target['weight'],
                        'planet_weight': self.PLANET_WEIGHT.get(planet, 5),
                        'aspect_weight': self.ASPECT_WEIGHT.get(aspect, 0.7),
                    })

        return transits

    def _calculate_score(self, planet: str, target: Dict, aspect: str,
                         orb: float, phase: str, status: str, is_active: bool) -> float:
        """Вычисляет значимость транзита."""
        base_score = (
            self.PLANET_WEIGHT.get(planet, 5) *
            self.ASPECT_WEIGHT.get(aspect, 0.7) *
            target.get('weight', 5)
        ) / 100

        # Орб: чем меньше, тем лучше
        orb_factor = max(0.2, 1 - orb / 6.0)

        # Фаза: applying важнее
        phase_factor = 1.2 if phase == 'applying' else 0.9 if phase == 'separating' else 1.0

        # Статус: сегодня важнее всего
        status_factor = {
            'today': 1.5,
            'tomorrow': 1.3,
            'yesterday': 1.1,
            'future': 0.8,
            'past': 0.6
        }.get(status, 0.8)

        # Активность: бонус
        active_factor = 1.2 if is_active else 0.8

        # Углы: бонус
        angle_factor = 1.3 if target.get('is_angle') else 1.0

        score = base_score * orb_factor * phase_factor * status_factor * active_factor * angle_factor
        return round(score, 2)

    # ========== ФИЛЬТРАЦИЯ ==========

    def _filter_transits(self, transits: List[Dict], top_n: int = 15) -> List[Dict]:
        """
        Фильтрует и сортирует транзиты по значимости.
        """
        # Удаляем дубликаты: для одной пары планета-цель-аспект оставляем только один транзит
        seen = set()
        unique = []
        for t in transits:
            key = (t['transit_planet'], t['natal_target'], t['aspect'])
            if key not in seen:
                seen.add(key)
                unique.append(t)

        # Сортируем по score
        unique.sort(key=lambda x: x['score'], reverse=True)

        # Возвращаем top_n
        return unique[:top_n]

    # ========== ПОСТРОЕНИЕ КОНТЕКСТА ==========

    def build_context(self, period: str = 'today',
                      target_date: Optional[datetime] = None,
                      days_range: int = 5) -> str:
        if target_date is None:
            target_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        # 1. Рассчитываем все транзиты
        all_transits = self._calculate_all_transits(target_date, days_range)
        self.all_transits = all_transits

        # 2. Фильтруем
        filtered = self._filter_transits(all_transits, top_n=15)
        self.filtered_transits = filtered

        # 3. Формируем текст
        lines = []
        lines.append(f"### Прогноз на день")
        lines.append(f"Дата: {target_date.strftime('%d.%m.%Y')}")
        lines.append("")

        # Натальные данные
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

        # Транзиты
        if not filtered:
            lines.append("### Основные транзиты")
            lines.append("")
            lines.append("Нет значимых транзитов в указанный период.")
        else:
            lines.append("### Основные транзиты")
            lines.append("")
            for ev in filtered:
                planet = ev['transit_planet']
                target = ev['natal_target']
                aspect = ev['aspect']
                orb = ev['orb']
                phase = ev['phase']
                status = ev['status']
                transit_house = ev['transit_house']
                natal_house = ev['natal_house']
                exact_dt = ev['exact_datetime']
                delta_hours = ev['delta_hours']

                aspect_name = NatalContextBuilder.ASPECT_MAP.get(aspect, aspect)
                phase_text = {
                    'applying': 'сходящийся',
                    'separating': 'расходящийся',
                    'exact': 'точный'
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

                # Статус относительно даты прогноза
                if status == 'today':
                    lines.append("Пик влияния: сегодня")
                elif status == 'tomorrow':
                    lines.append("Пик влияния: завтра")
                elif status == 'yesterday':
                    lines.append("Пик влияния: вчера")
                elif status == 'future':
                    days = int(abs(delta_hours) / 24)
                    lines.append(f"Пик влияния: через {days} дн.")
                elif status == 'past':
                    days = int(abs(delta_hours) / 24)
                    lines.append(f"Пик влияния: был {days} дн. назад")

                # Период активности
                if ev['is_active']:
                    lines.append(f"Активен сегодня")

                lines.append("")

        return "\n".join(lines)

    def get_stats(self) -> Dict:
        """Возвращает статистику расчёта для отладки."""
        return {
            'total_transits': len(self.all_transits),
            'filtered_transits': len(self.filtered_transits),
            'all_transits': self.all_transits,
            'filtered_transits_list': self.filtered_transits
        }