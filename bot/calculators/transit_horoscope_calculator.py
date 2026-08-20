#bot\calculators\transit_horoscope_calculator.py
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
import pytz
from collections import defaultdict
#import ephem

from kerykeion import AstrologicalSubject

try:
    from kerykeion.transit import TransitSubject
except ImportError:
    TransitSubject = None

from .astrology_calculator import AstrologyCalculator
from .timezone_coords import TIMEZONE_COORDS
from .base_calculator import BaseCalculator
from .astrology_utils import (
    calculate_aspects_manual,
    get_aspect_type,
    calculate_score,
    calculate_confidence,
    get_planet_speed_from_subject,
    get_transit_phase,
    estimate_exact_date,
    get_life_areas,
)

logger = logging.getLogger(__name__)


class TransitHoroscopeCalculator(BaseCalculator):
    """
    Класс для расчёта гороскопа на заданный период (день, месяц, год) с учётом транзитов.
    """

    AVERAGE_SPEEDS = {
        'Sun': 0.9856, 'Moon': 13.1764, 'Mercury': 1.383,
        'Venus': 1.2, 'Mars': 0.524, 'Jupiter': 0.083,
        'Saturn': 0.033, 'Uranus': 0.012, 'Neptune': 0.006,
        'Pluto': 0.004, 'Chiron': 0.02, 'Mean_Lilith': 0.1,
        'True_North_Lunar_Node': -0.05, 'True_South_Lunar_Node': 0.05,
    }

    PLANET_WEIGHTS = {
        'Sun': 10, 'Moon': 10, 'Mercury': 7, 'Venus': 7, 'Mars': 7,
        'Jupiter': 6, 'Saturn': 8, 'Uranus': 5, 'Neptune': 5, 'Pluto': 6,
        'Chiron': 3, 'True_North_Lunar_Node': 5, 'True_South_Lunar_Node': 5,
        'Mean_Lilith': 2,
    }

    ASPECT_ORBS = {
        'conjunction': 8, 'opposition': 8, 'trine': 6,
        'square': 6, 'sextile': 5, 'quincunx': 4,
        'semisextile': 3, 'sesquiquadrate': 4,
        'quintile': 3, 'biquintile': 3,
    }

    # Соответствие между именами планет в kerykeion и ephem
    EPHEM_NAMES = {
        'Sun': 'Sun', 'Moon': 'Moon', 'Mercury': 'Mercury',
        'Venus': 'Venus', 'Mars': 'Mars', 'Jupiter': 'Jupiter',
        'Saturn': 'Saturn', 'Uranus': 'Uranus', 'Neptune': 'Neptune',
        'Pluto': 'Pluto', 'Chiron': 'Chiron',
    }

    # Средние орбитальные периоды (дней) для приблизительного поиска станций
    ORBITAL_PERIODS = {
        'Sun': 365.25, 'Moon': 27.3, 'Mercury': 88, 'Venus': 225,
        'Mars': 687, 'Jupiter': 4333, 'Saturn': 10759, 'Uranus': 30687,
        'Neptune': 60190, 'Pluto': 90560, 'Chiron': 20200,
    }

    def __init__(self, user_data: Dict[str, Any], lang: str = 'ru',
                 natal_calc: Optional[AstrologyCalculator] = None,
                 period: str = 'today',
                 start_utc: Optional[datetime] = None,
                 end_utc: Optional[datetime] = None, telegram_id: Optional[int] = None):
        self.user_data = user_data
        self.lang = lang
        self.birth_date = user_data.get('birth_date')
        self.birth_time = user_data.get('birth_time')
        self.birth_place = user_data.get('birth_place')
        self.name = user_data.get('name', 'Человек')
        self.gender = user_data.get('gender', 'M')
        self.timezone_offset = user_data.get('timezone_offset', 3)
        self.telegram_id = telegram_id

        self.period = period
        self.start_utc = start_utc
        self.end_utc = end_utc

        tz_info = TIMEZONE_COORDS.get(self.timezone_offset, TIMEZONE_COORDS[3])
        self.transit_lat = tz_info["lat"]
        self.transit_lng = tz_info["lng"]
        self.transit_tz_str = tz_info["tz"]

        if natal_calc is not None:
            self.natal_calc = natal_calc
        else:
            self.natal_calc = AstrologyCalculator(user_data, telegram_id=telegram_id)
        self.natal_chart = None
        self.transit_subject = None
        self.transit_chart = None
        self.transit_houses = None

        # Кеши для расчётов
        self._transit_positions = None
        self._transit_aspects = None
        self._transit_angle_aspects = None
        self._transit_passes = None
        self._transit_ingresses = None
        self._transit_stations = None
        self._active_periods = None

        # Кеш позиций планет по датам (для ингрессий и станций)
        self._positions_cache = {}

    def _get_ephem_observer(self):
        """Создаёт наблюдателя ephem для текущего местоположения."""
        if self._ephem_observer is None:
            obs = ephem.Observer()
            obs.lat = str(self.transit_lat)
            obs.lon = str(self.transit_lng)
            self._ephem_observer = obs
        return self._ephem_observer

    def _get_natal_chart(self) -> Dict[str, Any]:
        if self.natal_chart is None:
            self.natal_chart = self.natal_calc._calculate_chart()
        return self.natal_chart

    def _get_transit_subject(self) -> AstrologicalSubject:
        if self.transit_subject is None:
            tz = pytz.timezone(self.transit_tz_str)
            now = datetime.now(tz)
            lat, lng, tz_str = self.natal_calc._get_coordinates_and_timezone()

            if TransitSubject is not None:
                natal_subject = self.natal_calc._get_natal_subject()
                self.transit_subject = TransitSubject(
                    natal_subject,
                    year=now.year,
                    month=now.month,
                    day=now.day,
                    hour=now.hour,
                    minute=now.minute,
                    lat=self.transit_lat,
                    lng=self.transit_lng,
                    tz_str=self.transit_tz_str,
                )
            else:
                self.transit_subject = AstrologicalSubject(
                    name="Transit",
                    year=now.year,
                    month=now.month,
                    day=now.day,
                    hour=now.hour,
                    minute=now.minute,
                    lat=self.transit_lat,
                    lng=self.transit_lng,
                    tz_str=self.transit_tz_str,
                )
        return self.transit_subject

    def _get_transit_chart(self) -> Dict[str, Any]:
        if self.transit_chart is None:
            subject = self._get_transit_subject()
            model = subject.model() if callable(subject.model) else subject.model
            if hasattr(model, 'dict'):
                data = model.dict()
            elif hasattr(model, 'model_dump'):
                data = model.model_dump()
            else:
                data = model.__dict__

            house_keys = [
                'first_house', 'second_house', 'third_house', 'fourth_house',
                'fifth_house', 'sixth_house', 'seventh_house', 'eighth_house',
                'ninth_house', 'tenth_house', 'eleventh_house', 'twelfth_house'
            ]
            transit_houses = []
            for i, key in enumerate(house_keys, 1):
                if key in data:
                    obj = data[key]
                    if isinstance(obj, dict):
                        if 'position' in obj:
                            degree = obj.get('position', 0.0)
                            transit_houses.append({"number": i, "degree": degree})
                    else:
                        if hasattr(obj, 'position'):
                            degree = getattr(obj, 'position', 0.0)
                            transit_houses.append({"number": i, "degree": degree})
            self.transit_houses = transit_houses
            self.transit_chart = data
        return self.transit_chart

    def _get_transit_house_for_planet(self, longitude: float) -> int:
        if not self.transit_houses:
            return 0
        sorted_houses = sorted(self.transit_houses, key=lambda h: h['degree'])
        for i, h in enumerate(sorted_houses):
            next_house = sorted_houses[(i + 1) % len(sorted_houses)]
            start = h['degree']
            end = next_house['degree']
            if end < start:
                if longitude >= start or longitude < end:
                    return h['number']
            else:
                if start <= longitude < end:
                    return h['number']
        return 0

    def _extract_planets_from_chart(self, chart_data: Dict[str, Any]) -> List[Dict]:
        """Извлекает планеты из словаря карты (транзитной или натальной)."""
        planet_keys = [
            'sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter', 'saturn',
            'uranus', 'neptune', 'pluto', 'chiron', 'mean_lilith', 'true_lilith',
            'ceres', 'pallas', 'juno', 'vesta', 'eris', 'sedna', 'haumea', 'makemake',
            'mean_north_lunar_node', 'true_north_lunar_node',
            'mean_south_lunar_node', 'true_south_lunar_node'
        ]
        planets = []
        for key in planet_keys:
            if key in chart_data:
                obj = chart_data[key]
                if isinstance(obj, dict):
                    if 'sign' in obj and 'position' in obj:
                        planets.append({
                            "name": key.capitalize(),
                            "sign": obj.get('sign', 'unknown'),
                            "degree": obj.get('position', 0.0),
                            "house": obj.get('house', 0),
                            "retrograde": obj.get('retrograde', False),
                            "speed": obj.get('speed', 0.0),
                        })
                else:
                    if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                        planets.append({
                            "name": key.capitalize(),
                            "sign": getattr(obj, 'sign', 'unknown'),
                            "degree": getattr(obj, 'position', 0.0),
                            "house": getattr(obj, 'house', 0),
                            "retrograde": getattr(obj, 'retrograde', False),
                            "speed": getattr(obj, 'speed', 0.0),
                        })
        return planets

    # ========================================================================
    # ОСНОВНЫЕ МЕТОДЫ
    # ========================================================================

    def get_transit_planet_positions(self) -> List[Dict[str, Any]]:
        """Возвращает список позиций транзитных планет (полные данные)."""
        if self._transit_positions is not None:
            return self._transit_positions

        transit_chart = self._get_transit_chart()
        planets = []
        planet_keys = [
            'sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter', 'saturn',
            'uranus', 'neptune', 'pluto', 'chiron',
            'mean_lilith', 'true_lilith',
            'mean_north_lunar_node', 'true_north_lunar_node',
            'mean_south_lunar_node', 'true_south_lunar_node'
        ]
        for key in planet_keys:
            if key in transit_chart:
                obj = transit_chart[key]
                if isinstance(obj, dict):
                    planet_name = key.capitalize()
                    longitude = obj.get('position', 0.0)
                    transit_house = self._get_transit_house_for_planet(longitude)
                    planets.append({
                        "name": planet_name,
                        "longitude": longitude,
                        "sign": obj.get('sign', 'unknown'),
                        "degree": longitude % 30,
                        "speed": obj.get('speed', 0.0),
                        "retrograde": obj.get('retrograde', False),
                        "house": transit_house,
                    })
        self._transit_positions = planets
        return planets

    def get_transit_aspects_to_natal(self) -> List[Dict[str, Any]]:
        """Возвращает расширенные аспекты транзитных планет к натальным."""
        if self._transit_aspects is not None:
            return self._transit_aspects

        if self.natal_chart is None:
            self._get_natal_chart()

        natal_planets = self.natal_chart.get('planets', []) if self.natal_chart else []
        transit_planets = self.get_transit_planet_positions()

        logger.info(f"🔍 НАТАЛЬНЫЕ ПЛАНЕТЫ ({len(natal_planets)}):")
        for np in natal_planets:
            logger.info(f"  {np['name']}: {np['degree']:.2f}° в знаке {np['sign']}, дом {np.get('house', 0)}")

        logger.info(f"🔍 ТРАНЗИТНЫЕ ПЛАНЕТЫ ({len(transit_planets)}):")
        for tp in transit_planets:
            logger.info(f"  {tp['name']}: {tp['longitude']:.2f}° в знаке {tp['sign']}, дом {tp.get('house', 0)}")

        aspects = []
        current_date = datetime.now()

        for tp in transit_planets:
            for np in natal_planets:
                if tp['name'] == np['name']:
                    continue

                aspect_type, orb = get_aspect_type(tp['longitude'], np['degree'], self.ASPECT_ORBS)
                if aspect_type is None:
                    continue

                logger.info(f"✅ НАЙДЕН АСПЕКТ: {tp['name']} {aspect_type} {np['name']} с орбом {orb:.2f}°")

                p1_weight = self.PLANET_WEIGHTS.get(tp['name'], 5)
                p2_weight = self.PLANET_WEIGHTS.get(np['name'], 5)
                aspect_weight = {
                    'conjunction': 10, 'opposition': 9, 'trine': 8,
                    'square': 7, 'sextile': 6, 'quincunx': 5,
                    'semisextile': 4, 'sesquiquadrate': 4,
                    'quintile': 3, 'biquintile': 3
                }.get(aspect_type, 5)
                score = calculate_score(p1_weight, p2_weight, aspect_weight, orb)
                confidence = calculate_confidence(score, orb)
                speed = tp.get('speed', 0.0)
                phase = get_transit_phase(speed)
                exact_date = estimate_exact_date(orb, speed, current_date)
                themes = self._get_aspect_themes(tp['name'], np['name'], aspect_type)

                # Проверяем, попадает ли аспект в период (по точной дате или по проходу)
                if exact_date and not self._is_date_in_period(exact_date):
                    # Если точная дата вне периода, но планета медленная и может иметь несколько проходов,
                    # мы всё равно включим аспект, но позже отфильтруем при формировании промпта
                    pass

                aspects.append({
                    "transit_planet": tp['name'],
                    "natal_planet": np['name'],
                    "aspect": aspect_type,
                    "orb": round(orb, 2),
                    "exact_angle": round(orb, 2),
                    "phase": phase,
                    "exact_date": exact_date,
                    "transit_house": tp['house'],
                    "natal_house": np.get('house', 0),
                    "transit_sign": tp['sign'],
                    "natal_sign": np['sign'],
                    "score": round(score, 2),
                    "confidence": round(confidence, 2),
                    "themes": themes,
                    "life_areas": get_life_areas(tp['name'], np['name']),
                })

        logger.info(f"📊 ИТОГО НАЙДЕНО ТРАНЗИТНЫХ АСПЕКТОВ К ПЛАНЕТАМ: {len(aspects)}")
        self._transit_aspects = aspects
        return aspects

    def get_transit_aspects_to_angles(self) -> List[Dict[str, Any]]:
        """Возвращает аспекты транзитных планет к углам (ASC, MC, DSC, IC)."""
        if self._transit_angle_aspects is not None:
            return self._transit_angle_aspects

        transit_planets = self.get_transit_planet_positions()
        natal_chart = self._get_natal_chart()
        angles = natal_chart.get('angles', {})
        if not angles:
            subject = self.natal_calc._get_natal_subject()
            from .astrology_utils import get_angles
            angles = get_angles(subject)

        angle_names = ['ASC', 'MC', 'DSC', 'IC']
        angle_degrees = {name: angles.get(name, 0.0) for name in angle_names}

        aspects = []
        current_date = datetime.now()
        for tp in transit_planets:
            for angle_name in angle_names:
                angle_deg = angle_degrees.get(angle_name, 0.0)
                if angle_deg == 0.0:
                    continue
                aspect_type, orb = get_aspect_type(tp['longitude'], angle_deg, self.ASPECT_ORBS)
                if aspect_type is None:
                    continue
                p_weight = self.PLANET_WEIGHTS.get(tp['name'], 5)
                angle_weight = 10
                aspect_weight = {'conjunction': 10, 'opposition': 9, 'trine': 8,
                                 'square': 7, 'sextile': 6, 'quincunx': 5,
                                 'semisextile': 4, 'sesquiquadrate': 4,
                                 'quintile': 3, 'biquintile': 3}.get(aspect_type, 5)
                score = calculate_score(p_weight, angle_weight, aspect_weight, orb)
                confidence = calculate_confidence(score, orb)
                speed = tp.get('speed', 0.0)
                phase = get_transit_phase(speed)
                exact_date = estimate_exact_date(orb, speed, current_date)
                themes = self._get_aspect_themes(tp['name'], angle_name, aspect_type)

                aspects.append({
                    "transit_planet": tp['name'],
                    "angle": angle_name,
                    "aspect": aspect_type,
                    "orb": round(orb, 2),
                    "exact_angle": round(orb, 2),
                    "phase": phase,
                    "exact_date": exact_date,
                    "transit_house": tp['house'],
                    "score": round(score, 2),
                    "confidence": round(confidence, 2),
                    "themes": themes,
                    "life_areas": get_life_areas(tp['name'], angle_name),
                })
        self._transit_angle_aspects = aspects
        return aspects

    # ========================================================================
    # НОВЫЕ МЕТОДЫ ДЛЯ ПРОХОДОВ, ИНГРЕССИЙ, СТАНЦИЙ
    # ========================================================================

    def get_transit_passes(self) -> List[Dict[str, Any]]:
        if self._transit_passes is not None:
            return self._transit_passes

        aspects = self.get_transit_aspects_to_natal()
        groups = defaultdict(list)
        for asp in aspects:
            key = (asp['transit_planet'], asp['natal_planet'], asp['aspect'])
            if asp.get('exact_date'):
                groups[key].append(asp['exact_date'])

        passes = []
        for (t_planet, n_planet, aspect), dates in groups.items():
            unique_dates = sorted(set(dates))
            if unique_dates:
                passes.append({
                    "transit_planet": t_planet,
                    "natal_planet": n_planet,
                    "aspect": aspect,
                    "passes": [{"date": d, "direction": "direct"} for d in unique_dates]
                })
        self._transit_passes = passes
        return passes

    def get_transit_ingresses(self) -> List[Dict[str, Any]]:
        """
        Определяет даты ингрессий (вход планет в знаки и дома) в течение периода.
        Использует кеширование позиций.
        """
        if self._transit_ingresses is not None:
            return self._transit_ingresses

        if self.start_utc is None or self.end_utc is None:
            self._transit_ingresses = []
            return []

        planet_names = ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars', 'Jupiter',
                        'Saturn', 'Uranus', 'Neptune', 'Pluto', 'Chiron']
        ingresses = []
        current_date = self.start_utc
        one_day = timedelta(days=1)

        # Словари для хранения предыдущих значений
        prev_signs = {}
        prev_houses = {}

        # Инициализация – получаем позиции на start_utc
        for planet in planet_names:
            lon = self._get_cached_position(planet, self.start_utc)
            if lon is not None:
                prev_signs[planet] = int(lon // 30)  # номер знака 0-11
                prev_houses[planet] = self._get_transit_house_for_planet(lon)

        # Итерируем по дням, начиная со следующего дня
        current_date = self.start_utc + one_day
        while current_date <= self.end_utc:
            for planet in planet_names:
                lon = self._get_cached_position(planet, current_date)
                if lon is None:
                    continue
                current_sign = int(lon // 30)
                current_house = self._get_transit_house_for_planet(lon)

                # Проверяем ингрессию в знак
                if planet in prev_signs:
                    if current_sign != prev_signs[planet]:
                        sign_names = ['Овен', 'Телец', 'Близнецы', 'Рак', 'Лев', 'Дева',
                                      'Весы', 'Скорпион', 'Стрелец', 'Козерог', 'Водолей', 'Рыбы']
                        from_sign = sign_names[prev_signs[planet]] if prev_signs[planet] < len(sign_names) else str(
                            prev_signs[planet])
                        to_sign = sign_names[current_sign] if current_sign < len(sign_names) else str(current_sign)
                        ingresses.append({
                            "planet": planet,
                            "type": "sign",
                            "from": from_sign,
                            "to": to_sign,
                            "date": current_date.strftime('%Y-%m-%d')
                        })
                # Проверяем ингрессию в дом
                if planet in prev_houses:
                    if current_house != prev_houses[planet] and current_house != 0 and prev_houses[planet] != 0:
                        ingresses.append({
                            "planet": planet,
                            "type": "house",
                            "from": prev_houses[planet],
                            "to": current_house,
                            "date": current_date.strftime('%Y-%m-%d')
                        })

                prev_signs[planet] = current_sign
                prev_houses[planet] = current_house

            current_date += one_day

        self._transit_ingresses = ingresses
        return ingresses

    def get_transit_stations(self) -> List[Dict[str, Any]]:
        """
        Определяет даты станций (смена направления движения) для планет в течение периода.
        Использует численное дифференцирование позиций, получаемых через кеш.
        """
        if self._transit_stations is not None:
            return self._transit_stations

        if self.start_utc is None or self.end_utc is None:
            self._transit_stations = []
            return []

        planet_names = ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars', 'Jupiter',
                        'Saturn', 'Uranus', 'Neptune', 'Pluto', 'Chiron']

        stations = []
        one_day = timedelta(days=1)

        # Для каждой планеты храним предыдущий знак скорости (-1, 0, 1)
        prev_speed_sign = {}

        # Начальная инициализация: вычисляем позиции на start_utc и start_utc+1 день
        start_positions = {}
        next_positions = {}
        for planet in planet_names:
            p = self._get_cached_position(planet, self.start_utc)
            if p is not None:
                start_positions[planet] = p
            p2 = self._get_cached_position(planet, self.start_utc + one_day)
            if p2 is not None:
                next_positions[planet] = p2

        # Вычисляем начальную скорость
        for planet in planet_names:
            if planet in start_positions and planet in next_positions:
                speed = (next_positions[planet] - start_positions[planet]) % 360
                if speed > 180:
                    speed = speed - 360
                if abs(speed) < 0.001:
                    prev_speed_sign[planet] = 0
                else:
                    prev_speed_sign[planet] = 1 if speed > 0 else -1

        # Итерируем по дням с окном из трёх точек
        current_date = self.start_utc + one_day
        while current_date <= self.end_utc:
            prev_date = current_date - one_day
            next_date = current_date + one_day
            if next_date > self.end_utc:
                break

            prev_positions = {}
            cur_positions = {}
            next_positions = {}
            for planet in planet_names:
                p = self._get_cached_position(planet, prev_date)
                if p is not None:
                    prev_positions[planet] = p
                c = self._get_cached_position(planet, current_date)
                if c is not None:
                    cur_positions[planet] = c
                n = self._get_cached_position(planet, next_date)
                if n is not None:
                    next_positions[planet] = n

            for planet in planet_names:
                if planet not in prev_positions or planet not in cur_positions or planet not in next_positions:
                    continue
                # Центральная разность: (next - prev) / 2
                speed = (next_positions[planet] - prev_positions[planet]) % 360
                if speed > 180:
                    speed = speed - 360
                if abs(speed) < 0.001:
                    current_sign = 0
                else:
                    current_sign = 1 if speed > 0 else -1

                if planet in prev_speed_sign:
                    prev_sign = prev_speed_sign[planet]
                    if current_sign != prev_sign and prev_sign != 0 and current_sign != 0:
                        # Найдена станция
                        stations.append({
                            "planet": planet,
                            "status": "stationary",
                            "sign": self._get_sign_name(cur_positions[planet]),
                            "house": self._get_transit_house_for_planet(cur_positions[planet]),
                            "date": current_date.strftime('%Y-%m-%d'),
                            "speed": round(speed, 3)
                        })
                prev_speed_sign[planet] = current_sign

            current_date += one_day

        self._transit_stations = stations
        return stations

    def _create_transit_subject_for_date(self, date: datetime) -> AstrologicalSubject:
        tz = pytz.timezone(self.transit_tz_str)
        local_date = date.astimezone(tz)
        if TransitSubject is not None:
            natal_subject = self.natal_calc._get_natal_subject()
            return TransitSubject(
                natal_subject,
                year=local_date.year,
                month=local_date.month,
                day=local_date.day,
                hour=local_date.hour,
                minute=local_date.minute,
                lat=self.transit_lat,
                lng=self.transit_lng,
                tz_str=self.transit_tz_str,
            )
        else:
            return AstrologicalSubject(
                name="Transit",
                year=local_date.year,
                month=local_date.month,
                day=local_date.day,
                hour=local_date.hour,
                minute=local_date.minute,
                lat=self.transit_lat,
                lng=self.transit_lng,
                tz_str=self.transit_tz_str,
            )

    def _extract_planet_data_from_subject(self, subject: AstrologicalSubject) -> Dict[str, Dict]:
        model = subject.model() if callable(subject.model) else subject.model
        if hasattr(model, 'dict'):
            data = model.dict()
        else:
            data = model.__dict__

        result = {}
        planet_keys = ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars', 'Jupiter',
                       'Saturn', 'Uranus', 'Neptune', 'Pluto', 'Chiron']
        key_map = {k.lower(): k for k in planet_keys}
        for key, name in key_map.items():
            if key in data:
                obj = data[key]
                if isinstance(obj, dict):
                    if 'position' in obj and 'sign' in obj:
                        result[name] = {
                            'longitude': obj['position'],
                            'sign': obj['sign'],
                            'sign_num': self._sign_to_number(obj['sign']),
                            'house': self._get_transit_house_for_planet(obj['position'])
                        }
                else:
                    if hasattr(obj, 'position') and hasattr(obj, 'sign'):
                        result[name] = {
                            'longitude': obj.position,
                            'sign': obj.sign,
                            'sign_num': self._sign_to_number(obj.sign),
                            'house': self._get_transit_house_for_planet(obj.position)
                        }
        return result

    def _sign_to_number(self, sign: str) -> int:
        signs = ['Aries', 'Taurus', 'Gemini', 'Cancer', 'Leo', 'Virgo',
                 'Libra', 'Scorpio', 'Sagittarius', 'Capricorn', 'Aquarius', 'Pisces']
        try:
            return signs.index(sign)
        except ValueError:
            return 0

    def _get_sign_name(self, longitude: float) -> str:
        signs = ['Овен', 'Телец', 'Близнецы', 'Рак', 'Лев', 'Дева',
                 'Весы', 'Скорпион', 'Стрелец', 'Козерог', 'Водолей', 'Рыбы']
        index = int(longitude // 30) % 12
        return signs[index]


    # ========================================================================
    # АКТИВНЫЕ ПЕРИОДЫ
    # ========================================================================

    def get_active_periods(self) -> List[Dict[str, Any]]:
        """
        Группирует транзитные аспекты по темам и формирует активные периоды.
        Использует даты точных аспектов и объединяет близкие по времени.
        """
        if self._active_periods is not None:
            return self._active_periods

        aspects = self.get_transit_aspects_to_natal()
        # Убедимся, что у всех аспектов есть exact_date (если нет – вычисляем)
        current_date = datetime.now()
        for asp in aspects:
            if not asp.get('exact_date'):
                speed = self._get_planet_speed(asp['transit_planet'], is_transit=True, transit_calc=self)
                if speed != 0:
                    asp['exact_date'] = estimate_exact_date(asp['orb'], speed, current_date)

        # Группируем по темам
        theme_groups = defaultdict(list)
        for asp in aspects:
            for theme in asp.get('themes', []):
                theme_groups[theme].append(asp)

        periods = []
        for theme, asp_list in theme_groups.items():
            if not asp_list:
                continue
            # Собираем даты
            dates = [a.get('exact_date') for a in asp_list if a.get('exact_date')]
            if dates:
                # Фильтруем даты в пределах периода
                filtered_dates = [d for d in dates if self._is_date_in_period(d)]
                if not filtered_dates:
                    continue
                # Группируем даты в кластеры (если разница <= 7 дней)
                sorted_dates = sorted(filtered_dates)
                clusters = []
                current_cluster = [sorted_dates[0]]
                for d in sorted_dates[1:]:
                    # Преобразуем строки в даты
                    prev = datetime.strptime(current_cluster[-1], '%Y-%m-%d')
                    curr = datetime.strptime(d, '%Y-%m-%d')
                    if (curr - prev).days <= 7:
                        current_cluster.append(d)
                    else:
                        clusters.append(current_cluster)
                        current_cluster = [d]
                clusters.append(current_cluster)

                # Для каждого кластера создаём период
                for cluster in clusters:
                    if len(cluster) == 1:
                        start = cluster[0]
                        end = cluster[0]
                    else:
                        start = cluster[0]
                        end = cluster[-1]
                    # Фильтруем аспекты, входящие в этот период
                    period_aspects = [a for a in asp_list if a.get('exact_date') in cluster]
                    avg_score = sum(a['score'] for a in period_aspects) / len(period_aspects) if period_aspects else 0
                    avg_conf = sum(a['confidence'] for a in period_aspects) / len(period_aspects) if period_aspects else 0
                    evidence = [
                        {
                            "transit": a['transit_planet'],
                            "natal": a['natal_planet'],
                            "aspect": a['aspect'],
                            "orb": a['orb'],
                            "phase": a['phase'],
                            "exact_date": a.get('exact_date'),
                            "transit_house": a['transit_house'],
                            "natal_house": a['natal_house'],
                            "score": a['score'],
                            "confidence": a['confidence']
                        }
                        for a in period_aspects[:5]
                    ]
                    periods.append({
                        "start": start,
                        "end": end,
                        "theme": theme,
                        "intensity": round(avg_score, 1),
                        "confidence": round(avg_conf, 2),
                        "score": round(avg_score, 2),
                        "evidence": evidence
                    })
            else:
                # Если дат нет, но аспекты есть (например, быстрые планеты без точной даты)
                # Создаём период на весь запрошенный диапазон
                if self.start_utc and self.end_utc:
                    start = self.start_utc.strftime('%Y-%m-%d')
                    end = self.end_utc.strftime('%Y-%m-%d')
                    avg_score = sum(a['score'] for a in asp_list) / len(asp_list) if asp_list else 0
                    avg_conf = sum(a['confidence'] for a in asp_list) / len(asp_list) if asp_list else 0
                    evidence = [
                        {
                            "transit": a['transit_planet'],
                            "natal": a['natal_planet'],
                            "aspect": a['aspect'],
                            "orb": a['orb'],
                            "phase": a['phase'],
                            "exact_date": a.get('exact_date'),
                            "transit_house": a['transit_house'],
                            "natal_house": a['natal_house'],
                            "score": a['score'],
                            "confidence": a['confidence']
                        }
                        for a in asp_list[:5]
                    ]
                    periods.append({
                        "start": start,
                        "end": end,
                        "theme": theme,
                        "intensity": round(avg_score, 1),
                        "confidence": round(avg_conf, 2),
                        "score": round(avg_score, 2),
                        "evidence": evidence
                    })

        # Фильтруем по периоду (уже отфильтровано выше, но на всякий случай)
        self._active_periods = periods
        return periods

    def get_transit_themes(self) -> Dict[str, Any]:
        """Агрегирует темы из всех аспектов."""
        aspects = self.get_transit_aspects_to_natal()
        themes = {}
        for asp in aspects:
            for theme in asp.get('themes', []):
                if theme not in themes:
                    themes[theme] = {"evidence": [], "score": 0, "count": 0}
                themes[theme]["evidence"].append({
                    "type": "transit",
                    "source": f"{asp['transit_planet']} {asp['aspect']} {asp['natal_planet']}",
                    "score": asp['score'],
                    "confidence": asp['confidence']
                })
                themes[theme]["count"] += 1
                themes[theme]["score"] += asp['score']
        for theme in themes:
            themes[theme]["score"] = round(themes[theme]["score"] / themes[theme]["count"], 2)
            themes[theme]["confidence"] = round(
                sum(e['confidence'] for e in themes[theme]["evidence"]) / themes[theme]["count"], 2
            )
            themes[theme]["evidence"] = themes[theme]["evidence"][:5]
        return themes

    def _get_aspect_themes(self, p1: str, p2: str, aspect: str) -> List[str]:
        themes_map = {
            'Sun': ['identity', 'self_expression', 'vitality'],
            'Moon': ['emotions', 'family', 'intuition'],
            'Mercury': ['communication', 'learning', 'intellect'],
            'Venus': ['love', 'beauty', 'values'],
            'Mars': ['action', 'drive', 'conflict'],
            'Jupiter': ['growth', 'expansion', 'wisdom'],
            'Saturn': ['structure', 'responsibility', 'discipline'],
            'Uranus': ['change', 'innovation', 'freedom'],
            'Neptune': ['intuition', 'spirituality', 'illusion'],
            'Pluto': ['transformation', 'power', 'depth'],
            'Chiron': ['healing', 'wound', 'teaching'],
            'ASC': ['self', 'appearance', 'personality'],
            'MC': ['career', 'status', 'ambition'],
            'DSC': ['relationships', 'partnership'],
            'IC': ['home', 'family', 'roots'],
        }
        themes1 = themes_map.get(p1, ['unknown'])
        themes2 = themes_map.get(p2, ['unknown'])
        combined = themes1 + themes2
        return list(dict.fromkeys(combined))

    # ========================================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ========================================================================

    def _is_date_in_period(self, date_str: Optional[str]) -> bool:
        if not date_str or self.start_utc is None or self.end_utc is None:
            return False
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d').date()
            start = self.start_utc.date()
            end = self.end_utc.date()
            return start <= dt <= end
        except ValueError:
            return False

    def _get_planet_speed(self, planet: str, is_transit: bool = False, transit_calc=None) -> float:
        # Используем средние скорости как fallback
        avg_speeds = {
            'Sun': 0.9856, 'Moon': 13.1764, 'Mercury': 1.383,
            'Venus': 1.2, 'Mars': 0.524, 'Jupiter': 0.083,
            'Saturn': 0.033, 'Uranus': 0.012, 'Neptune': 0.006,
            'Pluto': 0.004, 'Chiron': 0.02, 'Mean_Lilith': 0.1,
            'True_North_Lunar_Node': -0.05, 'True_South_Lunar_Node': 0.05,
        }
        try:
            if is_transit and transit_calc is not None:
                subject = transit_calc._get_transit_subject()
                if hasattr(subject, 'planets'):
                    for p in subject.planets:
                        if p.name.lower() == planet.lower():
                            return p.speed if hasattr(p, 'speed') else avg_speeds.get(planet, 0.0)
            else:
                subject = self.natal_calc._get_natal_subject()
                if hasattr(subject, 'planets'):
                    for p in subject.planets:
                        if p.name.lower() == planet.lower():
                            return p.speed if hasattr(p, 'speed') else avg_speeds.get(planet, 0.0)
        except:
            pass
        return avg_speeds.get(planet, 0.0)

    def _get_cached_position(self, planet: str, date: datetime) -> Optional[float]:
        """
        Возвращает долготу планеты на указанную дату, используя кеш.
        Если данных нет, создаёт субъект и извлекает позицию.
        """
        key = (planet, date.strftime('%Y-%m-%d'))
        if key in self._positions_cache:
            return self._positions_cache[key]

        subject = self._create_transit_subject_for_date(date)
        data = self._extract_planet_data_from_subject(subject)
        if planet in data:
            pos = data[planet]['longitude']
            self._positions_cache[key] = pos
            return pos
        return None

    def calculate(self) -> Dict[str, Any]:
        """
        Возвращает данные в старом формате для обратной совместимости (используется в astrology_data_builder).
        """
        aspects = self.get_transit_aspects_to_natal()
        if aspects:
            transit_aspects_str = "\n".join(
                f"Transit {a['transit_planet']} → Natal {a['natal_planet']} → {a['aspect']} → {a['orb']:.2f}°"
                for a in aspects
            )
        else:
            transit_aspects_str = "Нет значимых транзитных аспектов"
        return {"transit_aspects": transit_aspects_str}

    # ========================================================================
    # НОВЫЙ МЕТОД ДЛЯ ПОЛУЧЕНИЯ ВСЕХ ДАННЫХ
    # ========================================================================

    def get_full_transit_data(self) -> Dict[str, Any]:
        """Возвращает все данные для нового промпта гороскопа."""
        return {
            "transit_planets": self.get_transit_planet_positions(),
            "transit_aspects": self.get_transit_aspects_to_natal(),
            "transit_angle_aspects": self.get_transit_aspects_to_angles(),
            "transit_passes": self.get_transit_passes(),
            "transit_ingresses": self.get_transit_ingresses(),
            "transit_stations": self.get_transit_stations(),
            "active_periods": self.get_active_periods(),
            "transit_themes": self.get_transit_themes(),
            "period": self.period,
            "start_utc": self.start_utc,
            "end_utc": self.end_utc,
        }