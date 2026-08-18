# bot/calculators/astrology_utils.py
from typing import List, Dict, Any, Optional

def get_house_for_longitude(longitude: float, houses: List[Dict]) -> int:
    """Определяет номер дома по долготе планеты на основе куспидов домов."""
    if not houses:
        return 0
    sorted_houses = sorted(houses, key=lambda h: h['degree'])
    for i, h in enumerate(sorted_houses):
        next_house = sorted_houses[(i + 1) % len(sorted_houses)]
        start = h['degree']
        end = next_house['degree']
        if end < start:  # переход через 0°
            if longitude >= start or longitude < end:
                return h['number']
        else:
            if start <= longitude < end:
                return h['number']
    return 0

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

def extract_planets_from_subject(subject) -> List[Dict]:
    """Извлекает список планет с градусами из субъекта (для натала и транзитов)."""
    planets = []
    # Если есть атрибут .planets (kerykeion >= 5)
    if hasattr(subject, 'planets') and subject.planets:
        for p in subject.planets:
            planets.append({
                "name": p.name,
                "sign": getattr(p, 'sign', 'unknown'),
                "degree": getattr(p, 'position', 0.0),
                "house": getattr(p, 'house', 0),
                "retrograde": getattr(p, 'retrograde', False),
                "speed": getattr(p, 'speed', 0.0),
            })
    else:
        # Иначе через модель
        model = subject.model() if callable(subject.model) else subject.model
        data = model.dict() if hasattr(model, 'dict') else model.__dict__
        planet_keys = [
            'sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter', 'saturn',
            'uranus', 'neptune', 'pluto', 'chiron', 'mean_lilith', 'true_lilith',
            'ceres', 'pallas', 'juno', 'vesta', 'eris', 'sedna', 'haumea', 'makemake',
            'mean_north_lunar_node', 'true_north_lunar_node',
            'mean_south_lunar_node', 'true_south_lunar_node'
        ]
        for key in planet_keys:
            if key in data:
                obj = data[key]
                if isinstance(obj, dict):
                    if 'position' in obj:
                        planets.append({
                            "name": key.capitalize(),
                            "sign": obj.get('sign', 'unknown'),
                            "degree": obj.get('position', 0.0),
                            "house": obj.get('house', 0),
                            "retrograde": obj.get('retrograde', False),
                            "speed": obj.get('speed', 0.0),
                        })
                else:
                    if hasattr(obj, 'position'):
                        planets.append({
                            "name": key.capitalize(),
                            "sign": getattr(obj, 'sign', 'unknown'),
                            "degree": getattr(obj, 'position', 0.0),
                            "house": getattr(obj, 'house', 0),
                            "retrograde": getattr(obj, 'retrograde', False),
                            "speed": getattr(obj, 'speed', 0.0),
                        })
    return planets

def extract_houses_from_subject(subject) -> List[Dict]:
    """Извлекает куспиды домов из субъекта."""
    houses = []
    model = subject.model() if callable(subject.model) else subject.model
    data = model.dict() if hasattr(model, 'dict') else model.__dict__
    house_keys = [
        'first_house', 'second_house', 'third_house', 'fourth_house',
        'fifth_house', 'sixth_house', 'seventh_house', 'eighth_house',
        'ninth_house', 'tenth_house', 'eleventh_house', 'twelfth_house'
    ]
    for i, key in enumerate(house_keys, 1):
        if key in data:
            obj = data[key]
            if isinstance(obj, dict):
                if 'position' in obj:
                    houses.append({
                        "number": i,
                        "sign": obj.get('sign', 'unknown'),
                        "degree": obj.get('position', 0.0),
                    })
            else:
                if hasattr(obj, 'position'):
                    houses.append({
                        "number": i,
                        "sign": getattr(obj, 'sign', 'unknown'),
                        "degree": getattr(obj, 'position', 0.0),
                    })
    return houses

def calculate_aspects_manual(planets1: List[Dict], planets2: List[Dict],
                             aspect_types: Optional[Dict[str, float]] = None) -> List[Dict]:
    """Ручной расчёт аспектов между двумя списками планет (по умолчанию мажорные)."""
    if aspect_types is None:
        aspect_types = {
            'conjunction': 8, 'opposition': 8, 'trine': 6,
            'square': 6, 'sextile': 5,
        }
    aspects = []
    for p1 in planets1:
        for p2 in planets2:
            if p1['name'] == p2['name']:
                continue
            diff = abs(p1['degree'] - p2['degree']) % 360
            if diff > 180:
                diff = 360 - diff
            for aspect_name, orb in aspect_types.items():
                target = {
                    'conjunction': 0, 'opposition': 180, 'trine': 120,
                    'square': 90, 'sextile': 60
                }.get(aspect_name, 0)
                if abs(diff - target) <= orb:
                    aspects.append({
                        'p1': p1['name'],
                        'p2': p2['name'],
                        'aspect': aspect_name,
                        'orb': abs(diff - target),
                    })
                    break
    return aspects