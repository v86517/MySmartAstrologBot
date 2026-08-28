#bot\calculators\astrology_utils.py
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta


# def get_house_for_longitude(longitude: float, houses: List[Dict]) -> int:
#     """Определяет номер дома по долготе планеты на основе куспидов домов."""
#     if not houses:
#         return 0
#     sorted_houses = sorted(houses, key=lambda h: h['degree'])
#     for i, h in enumerate(sorted_houses):
#         next_house = sorted_houses[(i + 1) % len(sorted_houses)]
#         start = h['degree']
#         end = next_house['degree']
#         if end < start:  # переход через 0°
#             if longitude >= start or longitude < end:
#                 return h['number']
#         else:
#             if start <= longitude < end:
#                 return h['number']
#     return 0


def get_angles(subject) -> Dict[str, float]:
    """Извлекает углы ASC, MC, DSC, IC из субъекта."""
    try:
        asc = getattr(subject, 'ascendant', 0.0) or 0.0
        mc = getattr(subject, 'midheaven', 0.0) or 0.0
        dsc = (asc + 180) % 360
        ic = (mc + 180) % 360
        return {"ASC": asc, "MC": mc, "DSC": dsc, "IC": ic}
    except Exception:
        return {"ASC": 0.0, "MC": 0.0, "DSC": 0.0, "IC": 0.0}


def find_dispositor(planet_name: str, sign: str, planets_data: List[Dict]) -> Dict[str, Any]:
    """Находит диспозитора планеты по знаку, возвращает цепочку."""
    sign_rulers = {
        'Aries': 'Mars', 'Taurus': 'Venus', 'Gemini': 'Mercury',
        'Cancer': 'Moon', 'Leo': 'Sun', 'Virgo': 'Mercury',
        'Libra': 'Venus', 'Scorpio': 'Pluto', 'Sagittarius': 'Jupiter',
        'Capricorn': 'Saturn', 'Aquarius': 'Uranus', 'Pisces': 'Neptune',
    }
    if sign not in sign_rulers:
        return {"dispositor": None, "chain": [], "final_dispositor": None}

    dispositor = sign_rulers[sign]
    chain = [planet_name]
    current = dispositor
    planet_names = [p.get('name') for p in planets_data]

    while current in planet_names:
        chain.append(current)
        for p in planets_data:
            if p.get('name') == current:
                current_sign = p.get('sign', '')
                if current_sign in sign_rulers:
                    current = sign_rulers[current_sign]
                else:
                    current = None
                break
        else:
            current = None

    return {
        "dispositor": dispositor,
        "chain": chain,
        "final_dispositor": chain[-1] if chain else None,
    }


# def extract_planets_from_subject(subject) -> List[Dict]:
#     """Извлекает список планет с градусами из субъекта (для натала и транзитов)."""
#     planets = []
#     # Если есть атрибут .planets (kerykeion >= 5)
#     if hasattr(subject, 'planets') and subject.planets:
#         for p in subject.planets:
#             planets.append({
#                 "name": p.name,
#                 "sign": getattr(p, 'sign', 'unknown'),
#                 "degree": getattr(p, 'position', 0.0),
#                 "house": getattr(p, 'house', 0),
#                 "retrograde": getattr(p, 'retrograde', False),
#                 "speed": getattr(p, 'speed', 0.0),
#             })
#     else:
#         # Иначе через модель
#         model = subject.model() if callable(subject.model) else subject.model
#         data = model.dict() if hasattr(model, 'dict') else model.__dict__
#         planet_keys = [
#             'sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter', 'saturn',
#             'uranus', 'neptune', 'pluto', 'chiron', 'mean_lilith', 'true_lilith',
#             'ceres', 'pallas', 'juno', 'vesta', 'eris', 'sedna', 'haumea', 'makemake',
#             'mean_north_lunar_node', 'true_north_lunar_node',
#             'mean_south_lunar_node', 'true_south_lunar_node'
#         ]
#         for key in planet_keys:
#             if key in data:
#                 obj = data[key]
#                 if isinstance(obj, dict):
#                     if 'position' in obj:
#                         planets.append({
#                             "name": key.capitalize(),
#                             "sign": obj.get('sign', 'unknown'),
#                             "degree": obj.get('position', 0.0),
#                             "house": obj.get('house', 0),
#                             "retrograde": obj.get('retrograde', False),
#                             "speed": obj.get('speed', 0.0),
#                         })
#                 else:
#                     if hasattr(obj, 'position'):
#                         planets.append({
#                             "name": key.capitalize(),
#                             "sign": getattr(obj, 'sign', 'unknown'),
#                             "degree": getattr(obj, 'position', 0.0),
#                             "house": getattr(obj, 'house', 0),
#                             "retrograde": getattr(obj, 'retrograde', False),
#                             "speed": getattr(obj, 'speed', 0.0),
#                         })
#     return planets


# def extract_houses_from_subject(subject) -> List[Dict]:
#     """Извлекает куспиды домов из субъекта."""
#     houses = []
#     model = subject.model() if callable(subject.model) else subject.model
#     data = model.dict() if hasattr(model, 'dict') else model.__dict__
#     house_keys = [
#         'first_house', 'second_house', 'third_house', 'fourth_house',
#         'fifth_house', 'sixth_house', 'seventh_house', 'eighth_house',
#         'ninth_house', 'tenth_house', 'eleventh_house', 'twelfth_house'
#     ]
#     for i, key in enumerate(house_keys, 1):
#         if key in data:
#             obj = data[key]
#             if isinstance(obj, dict):
#                 if 'position' in obj:
#                     houses.append({
#                         "number": i,
#                         "sign": obj.get('sign', 'unknown'),
#                         "degree": obj.get('position', 0.0),
#                     })
#             else:
#                 if hasattr(obj, 'position'):
#                     houses.append({
#                         "number": i,
#                         "sign": getattr(obj, 'sign', 'unknown'),
#                         "degree": getattr(obj, 'position', 0.0),
#                     })
#     return houses


# def calculate_aspects_manual(planets1: List[Dict], planets2: List[Dict],
#                              aspect_types: Optional[Dict[str, float]] = None) -> List[Dict]:
#     """Ручной расчёт аспектов между двумя списками планет (по умолчанию мажорные)."""
#     if aspect_types is None:
#         aspect_types = {
#             'conjunction': 8, 'opposition': 8, 'trine': 6,
#             'square': 6, 'sextile': 5,
#         }
#     aspects = []
#     for p1 in planets1:
#         for p2 in planets2:
#             if p1['name'] == p2['name']:
#                 continue
#             diff = abs(p1['degree'] - p2['degree']) % 360
#             if diff > 180:
#                 diff = 360 - diff
#             for aspect_name, orb in aspect_types.items():
#                 target = {
#                     'conjunction': 0, 'opposition': 180, 'trine': 120,
#                     'square': 90, 'sextile': 60
#                 }.get(aspect_name, 0)
#                 if abs(diff - target) <= orb:
#                     aspects.append({
#                         'p1': p1['name'],
#                         'p2': p2['name'],
#                         'aspect': aspect_name,
#                         'orb': abs(diff - target),
#                     })
#                     break
#     return aspects


# ========== НОВЫЕ ФУНКЦИИ ДЛЯ ТРАНЗИТОВ И СИНАСТРИИ ==========

def get_aspect_type(deg1: float, deg2: float, orb_dict: Dict[str, float]) -> Tuple[Optional[str], float]:
    """
    Определяет тип аспекта и орбис между двумя долготами.
    orb_dict: {'conjunction': 8, 'opposition': 8, ...}
    Возвращает (название аспекта, орбис) или (None, 0).
    """
    diff = abs(deg1 - deg2) % 360
    if diff > 180:
        diff = 360 - diff
    for aspect_name, orb in orb_dict.items():
        target = {
            'conjunction': 0, 'opposition': 180, 'trine': 120,
            'square': 90, 'sextile': 60, 'quincunx': 150,
            'semisextile': 30, 'sesquiquadrate': 135,
            'quintile': 72, 'biquintile': 144
        }.get(aspect_name.lower(), 0)
        if abs(diff - target) <= orb:
            return aspect_name, abs(diff - target)
    return None, 0.0


def calculate_score(planet1_weight: float, planet2_weight: float, aspect_weight: float, orb: float) -> float:
    """Вычисляет score для аспекта по формуле: (base + avg_weight + aspect_weight)/3 - orb_penalty."""
    base = 5
    avg_weight = (planet1_weight + planet2_weight) / 2
    orb_penalty = orb / 10
    score = (base + avg_weight + aspect_weight) / 3 - orb_penalty
    return max(1, min(10, score))


def calculate_confidence(score: float, orb: float) -> float:
    """Вычисляет confidence как (score/10) * (1 - orb/10)."""
    confidence = (score / 10) * (1 - orb / 10)
    return max(0.1, min(1.0, confidence))


# def get_planet_speed_from_subject(planet_name: str, subject) -> float:
#     """Извлекает скорость планеты из субъекта (по имени)."""
#     if hasattr(subject, 'planets'):
#         for p in subject.planets:
#             if p.name.lower() == planet_name.lower():
#                 return getattr(p, 'speed', 0.0)
#     return 0.0


def get_transit_phase(speed: float) -> str:
    """Определяет фазу транзита: 'applying', 'separating' или 'stationary'."""
    if abs(speed) < 0.01:
        return 'stationary'
    return 'applying' if speed > 0 else 'separating'


def estimate_exact_date(orb: float, speed: float, current_date: datetime) -> Optional[str]:
    """Оценивает дату точного аспекта на основе текущего орбиса и скорости (в градусах в день)."""
    if abs(speed) < 0.001:
        return None
    days = orb / abs(speed)
    exact = current_date + timedelta(days=days)
    return exact.strftime('%Y-%m-%d')


# def get_passes_for_slow_planet(planet_name: str, orb: float, speed: float, current_date: datetime) -> List[Dict]:
#     """
#     Возвращает проходы для медленных планет (Saturn, Jupiter, Uranus, Neptune, Pluto).
#     Возвращает список из трёх приблизительных дат.
#     """
#     slow_planets = ['Saturn', 'Jupiter', 'Uranus', 'Neptune', 'Pluto']
#     if planet_name not in slow_planets or abs(speed) < 0.001:
#         return []
#     passes = []
#     # Проходы с интервалом примерно 120 дней (для упрощения)
#     for i in range(3):
#         date = current_date + timedelta(days=120 * i)
#         direction = "direct" if i % 2 == 0 else "retrograde"
#         passes.append({"number": i + 1, "date": date.strftime('%Y-%m-%d'), "direction": direction})
#     return passes


def get_life_areas(planet1: str, planet2: str) -> List[str]:
    """Определяет жизненные сферы для аспекта на основе планет."""
    areas = []
    if 'Saturn' in (planet1, planet2):
        areas.extend(['career', 'responsibility'])
    if 'Venus' in (planet1, planet2):
        areas.extend(['relationships', 'love'])
    if 'Mars' in (planet1, planet2):
        areas.extend(['action', 'conflict'])
    if 'Jupiter' in (planet1, planet2):
        areas.extend(['growth', 'expansion'])
    if 'Moon' in (planet1, planet2):
        areas.extend(['emotions', 'family'])
    if 'Sun' in (planet1, planet2):
        areas.extend(['identity', 'self_expression'])
    return list(set(areas))