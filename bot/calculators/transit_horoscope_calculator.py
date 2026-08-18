import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
import pytz

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
    get_passes_for_slow_planet,
    get_life_areas,
)

logger = logging.getLogger(__name__)


class TransitHoroscopeCalculator(BaseCalculator):
    """
    Класс для расчёта гороскопа на сегодня с учётом транзитов.
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

    def __init__(self, user_data: Dict[str, Any], lang: str = 'ru', natal_calc: Optional[AstrologyCalculator] = None):
        self.user_data = user_data
        self.lang = lang
        self.birth_date = user_data.get('birth_date')
        self.birth_time = user_data.get('birth_time')
        self.birth_place = user_data.get('birth_place')
        self.name = user_data.get('name', 'Человек')
        self.gender = user_data.get('gender', 'M')
        self.timezone_offset = user_data.get('timezone_offset', 3)

        tz_info = TIMEZONE_COORDS.get(self.timezone_offset, TIMEZONE_COORDS[3])
        self.transit_lat = tz_info["lat"]
        self.transit_lng = tz_info["lng"]
        self.transit_tz_str = tz_info["tz"]

        if natal_calc is not None:
            self.natal_calc = natal_calc
        else:
            self.natal_calc = AstrologyCalculator(user_data)
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
    # НОВЫЕ МЕТОДЫ ДЛЯ РАСЧЁТА ТРАНЗИТОВ (согласно ТЗ)
    # ========================================================================

    def get_transit_planet_positions(self) -> List[Dict[str, Any]]:
        """Возвращает список позиций транзитных планет (полные данные)."""
        if self._transit_positions is not None:
            return self._transit_positions

        transit_chart = self._get_transit_chart()
        planets = []
        # Важные планеты для гороскопа
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

        natal_planets = self._extract_planets_from_chart(self._get_natal_chart())
        transit_planets = self.get_transit_planet_positions()

        # Для расчёта весов используем карту
        natal_names = {p['name'] for p in natal_planets}
        # Добавляем углы для возможных аспектов к ним (но здесь только планеты)
        aspects = []
        current_date = datetime.now()

        for tp in transit_planets:
            for np in natal_planets:
                # Пропускаем аспекты транзита к самому себе (если планета совпадает)
                if tp['name'] == np['name']:
                    continue
                aspect_type, orb = get_aspect_type(tp['longitude'], np['degree'], self.ASPECT_ORBS)
                if aspect_type is None:
                    continue
                # Веса планет
                p1_weight = self.PLANET_WEIGHTS.get(tp['name'], 5)
                p2_weight = self.PLANET_WEIGHTS.get(np['name'], 5)
                aspect_weight = {'conjunction': 10, 'opposition': 9, 'trine': 8,
                                 'square': 7, 'sextile': 6, 'quincunx': 5,
                                 'semisextile': 4, 'sesquiquadrate': 4,
                                 'quintile': 3, 'biquintile': 3}.get(aspect_type, 5)
                score = calculate_score(p1_weight, p2_weight, aspect_weight, orb)
                confidence = calculate_confidence(score, orb)
                speed = tp.get('speed', 0.0)
                phase = get_transit_phase(speed)
                exact_date = estimate_exact_date(orb, speed, current_date)
                passes = get_passes_for_slow_planet(tp['name'], orb, speed, current_date)
                themes = self._get_aspect_themes(tp['name'], np['name'], aspect_type)

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
                    "passes": passes,
                })
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
            # Если углы не сохранены, получаем их через калькулятор
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
                # Веса: планета + угол (углы имеют вес 10)
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

    def get_transit_passes(self) -> List[Dict[str, Any]]:
        """Возвращает проходы медленных планет (агрегированные)."""
        if self._transit_passes is not None:
            return self._transit_passes

        aspects = self.get_transit_aspects_to_natal()
        passes = []
        for asp in aspects:
            if asp.get('passes'):
                passes.append({
                    "transit_planet": asp['transit_planet'],
                    "natal_planet": asp['natal_planet'],
                    "aspect": asp['aspect'],
                    "passes": asp['passes'],
                })
        self._transit_passes = passes
        return passes

    def get_transit_ingresses(self) -> List[Dict[str, Any]]:
        """
        Определяет ингрессии планет в знаки и дома в ближайшие 30 дней.
        Для упрощения используем текущие позиции и скорости для оценки.
        """
        if self._transit_ingresses is not None:
            return self._transit_ingresses

        transit_planets = self.get_transit_planet_positions()
        ingresses = []
        current_date = datetime.now()
        future_date = current_date + timedelta(days=30)

        # Получаем позиции на будущую дату (приближённо)
        # Для простоты используем текущий субъект и добавим 30 дней
        subject = self._get_transit_subject()
        # Создаём новый субъект на будущую дату (если можем)
        try:
            tz = pytz.timezone(self.transit_tz_str)
            future_dt = current_date + timedelta(days=30)
            if TransitSubject is not None:
                natal_subject = self.natal_calc._get_natal_subject()
                future_subject = TransitSubject(
                    natal_subject,
                    year=future_dt.year,
                    month=future_dt.month,
                    day=future_dt.day,
                    hour=future_dt.hour,
                    minute=future_dt.minute,
                    lat=self.transit_lat,
                    lng=self.transit_lng,
                    tz_str=self.transit_tz_str,
                )
            else:
                future_subject = AstrologicalSubject(
                    name="Transit_future",
                    year=future_dt.year,
                    month=future_dt.month,
                    day=future_dt.day,
                    hour=future_dt.hour,
                    minute=future_dt.minute,
                    lat=self.transit_lat,
                    lng=self.transit_lng,
                    tz_str=self.transit_tz_str,
                )
            future_chart = future_subject.model() if callable(future_subject.model) else future_subject.model
            if hasattr(future_chart, 'dict'):
                future_data = future_chart.dict()
            else:
                future_data = future_chart.__dict__

            # Сравниваем знаки и дома для каждой планеты
            for key in ['sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter', 'saturn',
                        'uranus', 'neptune', 'pluto', 'chiron']:
                if key in self.transit_chart and key in future_data:
                    current_obj = self.transit_chart[key]
                    future_obj = future_data[key]
                    if isinstance(current_obj, dict) and isinstance(future_obj, dict):
                        current_sign = current_obj.get('sign', '')
                        future_sign = future_obj.get('sign', '')
                        if current_sign != future_sign and future_sign:
                            ingresses.append({
                                "planet": key.capitalize(),
                                "type": "sign",
                                "from": current_sign,
                                "to": future_sign,
                                "date_approx": future_dt.strftime('%Y-%m-%d')
                            })
                        # Дома вычисляем отдельно
                        current_deg = current_obj.get('position', 0.0)
                        future_deg = future_obj.get('position', 0.0)
                        current_house = self._get_transit_house_for_planet(current_deg)
                        future_house = self._get_transit_house_for_planet(future_deg)
                        if current_house != future_house and future_house != 0:
                            ingresses.append({
                                "planet": key.capitalize(),
                                "type": "house",
                                "from": current_house,
                                "to": future_house,
                                "date_approx": future_dt.strftime('%Y-%m-%d')
                            })
        except Exception as e:
            logger.warning(f"Ошибка при расчёте ингрессий: {e}")

        self._transit_ingresses = ingresses
        return ingresses

    def get_transit_stations(self) -> List[Dict[str, Any]]:
        """Возвращает планеты, которые сейчас стационарны или близки к смене направления."""
        if self._transit_stations is not None:
            return self._transit_stations

        transit_planets = self.get_transit_planet_positions()
        stations = []
        for p in transit_planets:
            speed = p.get('speed', 0.0)
            if abs(speed) < 0.01:
                stations.append({
                    "planet": p['name'],
                    "status": "stationary",
                    "speed": round(speed, 3),
                    "sign": p['sign'],
                    "house": p['house']
                })
        self._transit_stations = stations
        return stations

    def get_active_periods(self) -> List[Dict[str, Any]]:
        """Группирует транзитные аспекты по темам и формирует активные периоды."""
        if self._active_periods is not None:
            return self._active_periods

        aspects = self.get_transit_aspects_to_natal()
        # Группируем по темам
        theme_groups = {}
        for asp in aspects:
            for theme in asp.get('themes', []):
                if theme not in theme_groups:
                    theme_groups[theme] = []
                theme_groups[theme].append(asp)

        periods = []
        for theme, asp_list in theme_groups.items():
            if not asp_list:
                continue
            # Определяем даты
            dates = [a.get('exact_date') for a in asp_list if a.get('exact_date')]
            if dates:
                start = min(dates)
                end = max(dates)
            else:
                start = datetime.now().strftime('%Y-%m-%d')
                end = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
            avg_score = sum(a['score'] for a in asp_list) / len(asp_list)
            avg_conf = sum(a['confidence'] for a in asp_list) / len(asp_list)
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
                for a in asp_list[:5]  # ограничим доказательства
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
        self._active_periods = periods
        return periods

    def get_transit_themes(self) -> Dict[str, Any]:
        """Агрегирует темы из всех аспектов (аналогично _build_themes)."""
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
        # Усредняем
        for theme in themes:
            themes[theme]["score"] = round(themes[theme]["score"] / themes[theme]["count"], 2)
            themes[theme]["confidence"] = round(
                sum(e['confidence'] for e in themes[theme]["evidence"]) / themes[theme]["count"], 2
            )
            themes[theme]["evidence"] = themes[theme]["evidence"][:5]
        return themes

    def _get_aspect_themes(self, p1: str, p2: str, aspect: str) -> List[str]:
        """Возвращает темы для аспекта между двумя планетами."""
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
    # СТАРЫЙ МЕТОД calculate (сохраняется для совместимости)
    # ========================================================================

    def calculate(self) -> Dict[str, Any]:
        """Основной метод, возвращающий данные для старого промпта (обратная совместимость)."""
        natal_chart = self._get_natal_chart()

        natal_planets = natal_chart.get('planets', [])
        natal_houses = natal_chart.get('houses', [])
        natal_aspects = natal_chart.get('aspects', [])

        transit_planets = self.get_transit_planet_positions()
        # Для обратной совместимости используем старый формат аспектов (простой список строк)
        transit_aspects_simple = []
        for a in self.get_transit_aspects_to_natal():
            transit_aspects_simple.append(
                f"Transit {a['transit_planet']} → Natal {a['natal_planet']} → {a['aspect']} → {a['orb']:.2f}°"
            )

        sun = next((p for p in natal_planets if p['name'].lower() == 'sun'), None)
        moon = next((p for p in natal_planets if p['name'].lower() == 'moon'), None)
        ascendant = natal_houses[0]['sign'] if natal_houses else 'не известно'

        planets_str = "\n".join(
            f"- {p['name']} в {p['sign']} ({p['degree']:.2f}°) в {p['house']} доме"
            for p in natal_planets
        ) if natal_planets else "не известно"

        aspects_str = "\n".join(
            f"- {a['p1']} {a['aspect']} {a['p2']} (орбис: {a['orb']:.2f}°)" for a in natal_aspects
        ) if natal_aspects else "не известно"

        cusps = []
        for i, h in enumerate(natal_houses, 1):
            cusps.append(f"{i}-й дом: {h['sign']} ({h['degree']:.2f}°)")
        cusps_str = "\n".join(cusps) if cusps else "не известно"

        transit_moon = next((p for p in transit_planets if p['name'].lower() == 'moon'), None)
        transit_moon_sign = transit_moon['sign'] if transit_moon else 'не известно'
        transit_moon_house = transit_moon['house'] if transit_moon else 'не известно'

        moon_aspects = []
        for a in self.get_transit_aspects_to_natal():
            if 'Moon' in a['transit_planet'] or 'Moon' in a['natal_planet']:
                moon_aspects.append(
                    f"Transit {a['transit_planet']} → Natal {a['natal_planet']} → {a['aspect']} → {a['orb']:.2f}°"
                )
        transit_moon_aspects = "\n".join(moon_aspects) if moon_aspects else "Нет значимых аспектов"

        retrograde_list = [p['name'] for p in transit_planets if p.get('retrograde', False)]
        retrograde_planets = ", ".join(
            [f"{p} ℞" for p in retrograde_list]) if retrograde_list else "Нет ретроградных планет"

        target_date = datetime.now(pytz.timezone(self.transit_tz_str)).strftime("%d.%m.%Y")
        birth_date = self.birth_date or "01.01.2000"

        age = self.calculate_age(birth_date, target_date)
        life_path = self.calculate_life_path_number(birth_date)
        personal_day = self.calculate_personal_day_number(birth_date, target_date)
        personal_year = self.calculate_personal_year(birth_date, target_date)
        matrix = self.calculate_matrix_arcans(birth_date)
        transit_arcan = self.calculate_transit_arcan(birth_date, target_date)
        moon_illumination = self.moon_phase_percent(target_date)
        lunar_day = self.get_lunar_day(target_date)
        week_day = self.week_day_name(target_date)
        birth_weekday = self.week_day_name(birth_date)
        days_to_birthday = self.days_until_birthday(birth_date, target_date)

        zodiac = self.get_zodiac_sign(int(birth_date.split('.')[0]), int(birth_date.split('.')[1]))
        element = self.get_zodiac_element(zodiac)
        quality = self.get_zodiac_quality(zodiac)

        if self.lang == 'en':
            gender_text = "Male" if self.gender == 'M' else "Female"
        else:
            gender_text = "Мужчина" if self.gender == 'M' else "Женщина"

        data = {
            "name": self.name,
            "gender_text": gender_text,
            "gender_display": gender_text,
            "birth_date": birth_date,
            "birth_weekday": birth_weekday,
            "birth_time": self.birth_time or "не указано",
            "birth_place": self.birth_place or "не указано",
            "target_date": target_date,
            "target_weekday": week_day,
            "age": age,
            "zodiac_sign": zodiac,
            "zodiac_element": element,
            "zodiac_quality": quality,
            "life_path_number": life_path,
            "personal_day_number": personal_day,
            "personal_year": personal_year,
            "matrix_center": matrix['sz'],
            "transit_arcan": transit_arcan,
            "moon_illumination": moon_illumination,
            "lunar_day": lunar_day,
            "days_to_birthday": days_to_birthday,
            "is_birthday_today": days_to_birthday == 0,
            "birthday_note": "СЕГОДНЯ ДЕНЬ РОЖДЕНИЯ! 🎂" if days_to_birthday == 0 else f"До дня рождения: {days_to_birthday} дней",
            "birthday_congrats": "ОБЯЗАТЕЛЬНО поздравь с Днем Рождения и дай мощный энергетический заряд!" if days_to_birthday == 0 else "",
            "sun_sign": sun['sign'] if sun else "не известно",
            "moon_sign": moon['sign'] if moon else "не известно",
            "ascendant": ascendant,
            "planets_list": planets_str,
            "aspects_list": aspects_str,
            "cusps_list": cusps_str,
            "transit_moon_sign": transit_moon_sign,
            "transit_moon_house": transit_moon_house,
            "transit_moon_aspects": transit_moon_aspects,
            "retrograde_planets": retrograde_planets,
            "transit_aspects": "\n".join(transit_aspects_simple) if transit_aspects_simple else "Нет значимых транзитных аспектов",
            "pronoun": "он" if self.gender == 'M' else "она",
            "possessive": "его" if self.gender == 'M' else "её",
        }
        return data

    # ========================================================================
    # НОВЫЙ МЕТОД ДЛЯ ПОЛУЧЕНИЯ ВСЕХ ДАННЫХ (для нового промпта)
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
        }