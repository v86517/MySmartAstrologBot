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
    Калькулятор гороскопа на день с корректной математикой аспектов.
    Все долготы хранятся в абсолютных градусах 0–360°.
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

    GROUP_A = {'Saturn', 'Uranus', 'Neptune', 'Pluto', 'Jupiter'}
    GROUP_B = {'Mars', 'Venus', 'Mercury', 'Sun'}
    GROUP_C = {'Moon'}

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

        # Включаем отладку
        self.debug = True   # <-- атрибут определён

        self.natal_targets = self._build_natal_targets()
        self._transit_cache = {}
        self.all_transits = []
        self.filtered_transits = []

    def _build_natal_targets(self) -> List[Dict]:
        targets = []
        main_names = {'Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                      'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto'}
        for p in self.natal_planets:
            if p['name'] in main_names:
                lon = self._sign_to_abs(p['sign'], p['degree'])
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
                lon = self._sign_to_abs(a['sign'], a['position'])
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
                lon = self._sign_to_abs(p['sign'], p['degree'])
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

    def _sign_to_abs(self, sign: str, degree: float) -> float:
        start = self.SIGN_OFFSET.get(sign, 0)
        if degree >= 30:
            return degree % 360
        return start + degree

    def _angular_distance(self, lon1: float, lon2: float) -> float:
        diff = abs(lon1 - lon2) % 360
        if diff > 180:
            diff = 360 - diff
        return diff

    def _aspect_info(self, transit_lon: float, natal_lon: float) -> Tuple[Optional[str], float, float]:
        distance = self._angular_distance(transit_lon, natal_lon)
        best_aspect = None
        best_orb = 360.0
        for aspect, exact_angle in self.ASPECT_ANGLES.items():
            orb = abs(distance - exact_angle)
            if orb < best_orb:
                best_orb = orb
                best_aspect = aspect
        if best_orb > 10.0:
            return None, best_orb, distance
        return best_aspect, best_orb, distance

    def _aspect_error(self, transit_lon: float, natal_lon: float, aspect_angle: float) -> float:
        distance = self._angular_distance(transit_lon, natal_lon)
        return distance - aspect_angle

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

        start_error = self._aspect_error(start_pos, natal_lon, aspect_angle)
        end_error = self._aspect_error(end_pos, natal_lon, aspect_angle)

        eps = 0.0001
        max_iter = 100
        left = start_date
        right = end_date
        left_error = start_error
        right_error = end_error

        if left_error * right_error > 0:
            for _ in range(max_iter):
                mid = left + (right - left) / 2
                mid_pos = self._get_transit_position(mid, planet)
                if mid_pos is None:
                    break
                mid_error = self._aspect_error(mid_pos, natal_lon, aspect_angle)
                if abs(mid_error) < eps:
                    return mid
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
                if (right - left).total_seconds() < 60:
                    break
            return left if abs(left_error) < abs(right_error) else right

        for _ in range(max_iter):
            mid = left + (right - left) / 2
            mid_pos = self._get_transit_position(mid, planet)
            if mid_pos is None:
                break
            mid_error = self._aspect_error(mid_pos, natal_lon, aspect_angle)
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
        return left if abs(left_error) < abs(right_error) else right

    def _calculate_all_transits(self, forecast_date: datetime, days_range: int = 5) -> List[Dict]:
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

        transits = []

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

                    aspect_type, orb, distance = self._aspect_info(forecast_pos, t_lon)
                    if aspect_type is None:
                        continue

                    max_orb = self.MAX_ORBS.get(aspect_type, 6.0)
                    if orb > max_orb:
                        continue

                    if self.debug and target['is_angle']:
                        logger.info(
                            f"🔍 АСПЕКТ: {planet} → {target['name']} | "
                            f"transit_lon={forecast_pos:.4f}, target_lon={t_lon:.4f}, "
                            f"distance={distance:.4f}, aspect={aspect_type}, orb={orb:.4f}"
                        )

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

                    is_active = orb < self.MAX_ORBS.get(aspect_type, 6.0)

                    score = self._calculate_score(
                        planet, target, aspect_type, orb, phase, status, is_active
                    )

                    transit_house = self._get_transit_house(forecast_date, planet)

                    transits.append({
                        'transit_planet': planet,
                        'natal_target': target['name'],
                        'aspect': aspect_type,
                        'orb': orb,
                        'distance': distance,
                        'phase': phase,
                        'exact_datetime': exact_dt,
                        'forecast_datetime': forecast_date,
                        'delta_hours': delta_hours,
                        'status': status,
                        'is_active': is_active,
                        'transit_house': transit_house,
                        'natal_house': target['house'],
                        'is_angle': target['is_angle'],
                        'extra_type': target['extra_type'],
                        'score': score,
                        'target_weight': target['weight'],
                        'planet_weight': self.PLANET_WEIGHT.get(planet, 5),
                        'aspect_weight': self.ASPECT_WEIGHT.get(aspect_type, 0.7),
                    })

        return transits

    def _calculate_score(self, planet: str, target: Dict, aspect: str,
                         orb: float, phase: str, status: str, is_active: bool) -> float:
        base_score = (
            self.PLANET_WEIGHT.get(planet, 5) *
            self.ASPECT_WEIGHT.get(aspect, 0.7) *
            target.get('weight', 5)
        ) / 100

        orb_factor = max(0.2, 1 - orb / 6.0)
        phase_factor = 1.2 if phase == 'applying' else 0.9 if phase == 'separating' else 1.0
        status_factor = {
            'today': 1.5,
            'tomorrow': 1.3,
            'yesterday': 1.1,
            'future': 0.8,
            'past': 0.6
        }.get(status, 0.8)
        active_factor = 1.2 if is_active else 0.8
        angle_factor = 1.3 if target.get('is_angle') else 1.0

        score = base_score * orb_factor * phase_factor * status_factor * active_factor * angle_factor
        return round(score, 2)

    def _filter_transits(self, transits: List[Dict], top_n: int = 15) -> List[Dict]:
        seen = set()
        unique = []
        for t in transits:
            key = (t['transit_planet'], t['natal_target'], t['aspect'])
            if key not in seen:
                seen.add(key)
                unique.append(t)

        unique.sort(key=lambda x: x['score'], reverse=True)
        return unique[:top_n]

    def get_diagnostic_table(self, target_date: datetime) -> str:
        lines = []
        lines.append("=== ДИАГНОСТИЧЕСКАЯ ТАБЛИЦА ===")
        lines.append(f"Дата: {target_date.strftime('%Y-%m-%d %H:%M')} UTC")
        lines.append("")

        positions = self._get_transit_positions(target_date)
        lines.append("ТРАНЗИТНЫЕ ПЛАНЕТЫ:")
        for planet in ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                       'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']:
            if planet in positions:
                lon = positions[planet]
                sign_name = None
                degree_in_sign = lon
                for s, start in self.SIGN_OFFSET.items():
                    if start <= lon < start + 30:
                        sign_name = s
                        degree_in_sign = lon - start
                        break
                full_sign = {
                    'Ari': 'Овен', 'Tau': 'Телец', 'Gem': 'Близнецы',
                    'Can': 'Рак', 'Leo': 'Лев', 'Vir': 'Дева',
                    'Lib': 'Весы', 'Sco': 'Скорпион', 'Sag': 'Стрелец',
                    'Cap': 'Козерог', 'Aqu': 'Водолей', 'Pis': 'Рыбы'
                }.get(sign_name, sign_name)
                if sign_name:
                    lines.append(f"  {planet}: {full_sign} {degree_in_sign:.2f}° (abs {lon:.4f})")
                else:
                    lines.append(f"  {planet}: {lon:.4f}°")

        lines.append("")
        lines.append("НАТАЛЬНЫЕ ОБЪЕКТЫ (абсолютные долготы):")
        for target in self.natal_targets:
            name = target['name']
            lon = target['longitude']
            house = target['house'] if target['house'] is not None else '—'
            lines.append(f"  {name}: {lon:.4f}° (дом {house})")

        lines.append("")
        lines.append("КОНТРОЛЬНЫЕ ПРОВЕРКИ:")
        asc = next((t['longitude'] for t in self.natal_targets if t['name'] == 'ASC'), None)
        dsc = next((t['longitude'] for t in self.natal_targets if t['name'] == 'DSC'), None)
        mc = next((t['longitude'] for t in self.natal_targets if t['name'] == 'MC'), None)
        ic = next((t['longitude'] for t in self.natal_targets if t['name'] == 'IC'), None)

        if asc is not None and dsc is not None:
            dist = self._angular_distance(asc, dsc)
            lines.append(f"  ASC ↔ DSC: {dist:.4f}° (ожидается 180°)")
        if mc is not None and ic is not None:
            dist = self._angular_distance(mc, ic)
            lines.append(f"  MC ↔ IC: {dist:.4f}° (ожидается 180°)")

        return "\n".join(lines)

    def build_context(self, period: str = 'today',
                      target_date: Optional[datetime] = None,
                      days_range: int = 5) -> str:
        if target_date is None:
            target_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        all_transits = self._calculate_all_transits(target_date, days_range)
        self.all_transits = all_transits

        filtered = self._filter_transits(all_transits, top_n=15)
        self.filtered_transits = filtered

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

                if ev['is_active']:
                    lines.append("Активен сегодня")

                lines.append("")

        return "\n".join(lines)

    def get_stats(self) -> Dict:
        return {
            'total_transits': len(self.all_transits),
            'filtered_transits': len(self.filtered_transits),
            'all_transits': self.all_transits,
            'filtered_transits_list': self.filtered_transits
        }