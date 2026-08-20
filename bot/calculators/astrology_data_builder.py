#bot\calculators\astrology_data_builder.py
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import itertools

from .astrology_calculator import AstrologyCalculator
from .transit_horoscope_calculator import TransitHoroscopeCalculator
from .astrology_utils import (
    get_house_for_longitude,
    get_angles,
    find_dispositor,
    extract_planets_from_subject,
    extract_houses_from_subject,
    calculate_aspects_manual,
)

logger = logging.getLogger(__name__)


class AstrologyDataBuilder:
    def __init__(self, user_data: Dict[str, Any], lang: str = 'ru', include_transits: bool = True, telegram_id: Optional[int] = None):
        self.user_data = user_data
        self.lang = lang
        self.include_transits = include_transits  # <-- новый параметр
        self.telegram_id = telegram_id
        self.natal_calc = AstrologyCalculator(user_data)
        self.chart = self.natal_calc._calculate_chart()

        self.planet_weights = {
            'Sun': 10, 'Moon': 10, 'ASC': 10, 'MC': 10,
            'Mercury': 7, 'Venus': 7, 'Mars': 7, 'Jupiter': 6,
            'Saturn': 8, 'Uranus': 5, 'Neptune': 5, 'Pluto': 6,
            'Chiron': 3, 'True_North_Lunar_Node': 5, 'True_South_Lunar_Node': 5,
            'Mean_Lilith': 2,
        }

        self.planet_names_ru = {
            'Sun': 'Солнце', 'Moon': 'Луна', 'Mercury': 'Меркурий',
            'Venus': 'Венера', 'Mars': 'Марс', 'Jupiter': 'Юпитер',
            'Saturn': 'Сатурн', 'Uranus': 'Уран', 'Neptune': 'Нептун',
            'Pluto': 'Плутон', 'Chiron': 'Хирон',
            'True_North_Lunar_Node': 'Северный узел',
            'True_South_Lunar_Node': 'Южный узел',
            'Mean_Lilith': 'Лилит',
        }

    def build(self) -> Dict[str, Any]:
        chart = self.chart
        metadata = self._build_metadata()
        metadata.update({
            "timezone": chart.get('timezone'),
            "location": chart.get('location'),
            "utc_datetime": chart.get('utc_datetime'),
        })

        result = {
            "metadata": metadata,
            "natal": {
                "planets": self._build_natal_planets(),
                "houses": self._build_natal_houses(),
                "aspects": self._build_natal_aspects(),
                "house_rulers": self._build_house_rulers(),
                "dispositors": self._build_dispositors(),
                "dominant_elements": self._calculate_dominant_elements(),
                "dominant_modalities": self._calculate_dominant_modalities(),
                "dominant_houses": self._calculate_dominant_houses(),
                "dominant_planets": self._calculate_dominant_planets(),
                "dominant_signs": self._calculate_dominant_signs(),
                "angle_aspects": self._build_angle_aspects(),
                "patterns": self._build_patterns(),
                "summary": self._build_summary(),
                "angles": self.chart.get('angles', {}),
            },
            "themes": self._build_themes(include_transits=self.include_transits),
        }

        if self.include_transits:
            result["transits"] = self._build_transits(telegram_id=self.telegram_id)
            result["progressions"] = self._build_progressions()
            result["timeline"] = self._build_timeline()
        else:
            result["transits"] = {"planets": [], "aspects": [], "active_periods": []}
            result["progressions"] = {"planets": [], "aspects": []}
            result["timeline"] = []

        return result

    # ---------- METADATA ----------
    def _build_metadata(self) -> Dict[str, Any]:
        return {
            "calculation_date": datetime.now().isoformat(),
            "calculation_type": "natal",
            "version": "2.0",
            "settings": {
                "zodiac": "tropical",
                "house_system": "Placidus",
                "ephemeris": "kerykeion",
                "lunar_node": "true",
                "coordinate_system": "geocentric",
                "progression_type": "secondary",
                "major_aspects": {
                    "conjunction": 0, "opposition": 180, "trine": 120,
                    "square": 90, "sextile": 60,
                },
                "aspect_orb": {
                    "conjunction": 8, "opposition": 8, "trine": 6,
                    "square": 6, "sextile": 5,
                }
            }
        }

    # ---------- NATAL PLANETS ----------
    def _build_natal_planets(self) -> List[Dict[str, Any]]:
        planets = []
        planet_data = self.chart.get('planets', [])
        subject = self.natal_calc._get_natal_subject()
        angles = get_angles(subject)

        for p in planet_data:
            planet_name = p.get('name', 'Unknown')
            if planet_name in ['Ascendant', 'Descendant', 'Medium_Coeli', 'Imum_Coeli']:
                continue

            degree = float(p.get('degree', 0.0))
            house = int(p.get('house', 0))
            speed = p.get('speed', 0.0)
            retrograde = p.get('retrograde', False)
            latitude = p.get('latitude', 0.0)

            weight = self.planet_weights.get(planet_name, 5)
            angularity = self._calculate_angularity(subject, planet_name, degree, angles)
            dispositor_info = find_dispositor(planet_name, p.get('sign', ''), planet_data)

            planets.append({
                "name": planet_name,
                "name_local": self.planet_names_ru.get(planet_name, planet_name),
                "longitude": degree,
                "latitude": latitude,
                "speed": round(speed, 3),
                "retrograde": retrograde,
                "sign": p.get('sign', 'unknown'),
                "degree": degree % 30,
                "house": house,
                "angularity": angularity,
                "dispositor": dispositor_info.get('dispositor'),
                "dispositor_chain": dispositor_info.get('chain', []),
                "final_dispositor": dispositor_info.get('final_dispositor'),
                "weight": weight,
                "themes": self._get_planet_themes(planet_name, house, p.get('sign', ''))
            })

        return planets

    # ---------- ANGULARITY ----------
    def _calculate_angularity(self, subject, planet_name: str, degree: float, angles: Dict[str, float]) -> Dict[str, Any]:
        try:
            asc_degree = angles.get('ASC', 0.0)
            mc_degree = angles.get('MC', 0.0)

            asc_diff = abs(degree - asc_degree) % 360
            if asc_diff > 180:
                asc_diff = 360 - asc_diff

            mc_diff = abs(degree - mc_degree) % 360
            if mc_diff > 180:
                mc_diff = 360 - mc_diff

            asc_score = max(0, 10 - asc_diff / 10) if asc_diff < 100 else 0
            mc_score = max(0, 10 - mc_diff / 10) if mc_diff < 100 else 0
            total_score = max(asc_score, mc_score)

            return {
                "asc_distance": round(asc_diff, 2),
                "mc_distance": round(mc_diff, 2),
                "score": round(total_score, 2),
                "near_asc": asc_diff < 10,
                "near_mc": mc_diff < 10,
            }
        except:
            return {
                "asc_distance": 0,
                "mc_distance": 0,
                "score": 0,
                "near_asc": False,
                "near_mc": False,
            }

    # ==================== NATAL HOUSES ====================

    def _build_natal_houses(self) -> List[Dict[str, Any]]:
        houses = []
        house_data = self.chart.get('houses', [])
        for h in house_data:
            number = int(h.get('number', 0))
            sign = h.get('sign', 'unknown')
            degree = float(h.get('degree', 0.0))
            ruler = self._get_house_ruler(sign)
            houses.append({
                "number": number,
                "cusp": sign,
                "cusp_degree": round(degree, 2),
                "ruler": ruler,
                "ruler_sign": self._get_planet_sign(ruler),
                "ruler_house": self._get_planet_house(ruler),
            })
        return houses

    def _get_house_ruler(self, sign: str) -> str:
        sign_abbr_to_full = {
            'Ari': 'Aries', 'Tau': 'Taurus', 'Gem': 'Gemini',
            'Can': 'Cancer', 'Leo': 'Leo', 'Vir': 'Virgo',
            'Lib': 'Libra', 'Sco': 'Scorpio', 'Sag': 'Sagittarius',
            'Cap': 'Capricorn', 'Aqu': 'Aquarius', 'Pis': 'Pisces'
        }
        full_sign = sign_abbr_to_full.get(sign, sign)
        sign_rulers = {
            'Aries': 'Mars', 'Taurus': 'Venus', 'Gemini': 'Mercury',
            'Cancer': 'Moon', 'Leo': 'Sun', 'Virgo': 'Mercury',
            'Libra': 'Venus', 'Scorpio': 'Pluto', 'Sagittarius': 'Jupiter',
            'Capricorn': 'Saturn', 'Aquarius': 'Uranus', 'Pisces': 'Neptune',
        }
        return sign_rulers.get(full_sign, 'unknown')

    def _get_planet_sign(self, planet_name: str) -> str:
        for p in self.chart.get('planets', []):
            if p.get('name') == planet_name:
                return p.get('sign', 'unknown')
        return 'unknown'

    def _get_planet_house(self, planet_name: str) -> int:
        for p in self.chart.get('planets', []):
            if p.get('name') == planet_name:
                return int(p.get('house', 0))
        return 0

    # ==================== NATAL ASPECTS ====================

    def _build_natal_aspects(self) -> List[Dict[str, Any]]:
        aspects = []
        aspect_data = self.chart.get('aspects', [])
        for a in aspect_data:
            p1 = a.get('p1', '')
            p2 = a.get('p2', '')
            aspect = a.get('aspect', '')
            orb = float(a.get('orb', 0.0))

            p1_house = self._get_planet_house(p1)
            p2_house = self._get_planet_house(p2)
            p1_sign = self._get_planet_sign(p1)
            p2_sign = self._get_planet_sign(p2)
            themes = self._get_aspect_themes(p1, p2, aspect)
            weight = self._get_aspect_weight(p1, p2, aspect, orb)

            aspects.append({
                "p1": p1,
                "p1_name_local": self.planet_names_ru.get(p1, p1),
                "p2": p2,
                "p2_name_local": self.planet_names_ru.get(p2, p2),
                "aspect": aspect,
                "aspect_local": self._translate_aspect(aspect),
                "orb": round(orb, 2),
                "exact_angle": self._get_exact_angle(aspect),
                "actual_angle": orb,
                "phase": self._determine_phase(),
                "weight": round(weight, 2),
                "p1_house": p1_house,
                "p2_house": p2_house,
                "p1_sign": p1_sign,
                "p2_sign": p2_sign,
                "themes": themes,
            })
        return aspects

    def _get_exact_angle(self, aspect: str) -> int:
        aspect_map = {
            'conjunction': 0, 'opposition': 180, 'trine': 120,
            'square': 90, 'sextile': 60, 'quincunx': 150,
            'semisextile': 30, 'sesquiquadrate': 135,
            'quintile': 72, 'biquintile': 144,
        }
        return aspect_map.get(aspect.lower(), 0)

    def _translate_aspect(self, aspect: str) -> str:
        aspect_map_ru = {
            'conjunction': 'соединение', 'opposition': 'оппозиция',
            'trine': 'трин', 'square': 'квадрат', 'sextile': 'секстиль',
            'quincunx': 'квинконкс', 'semisextile': 'полусекстиль',
            'sesquiquadrate': 'полутораквадрат', 'quintile': 'квинтиль',
            'biquintile': 'биквинтиль',
        }
        return aspect_map_ru.get(aspect.lower(), aspect)

    def _determine_phase(self) -> str:
        return 'unknown'

    def _get_aspect_weight(self, p1: str, p2: str, aspect: str, orb: float) -> float:
        base_weight = 5
        planet_weight = (self.planet_weights.get(p1, 5) + self.planet_weights.get(p2, 5)) / 2
        aspect_weight_map = {'conjunction': 10, 'opposition': 9, 'trine': 8, 'square': 7, 'sextile': 6}
        aspect_weight = aspect_weight_map.get(aspect.lower(), 5)
        orb_penalty = max(0, orb / 10)
        weight = (base_weight + planet_weight + aspect_weight) / 3 - orb_penalty
        return max(1, min(10, weight))

    # ==================== THEMES ====================

    def _get_planet_themes(self, planet_name: str, house: int, sign: str) -> List[str]:
        themes = {
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
        }
        return themes.get(planet_name, ['unknown'])

    def _get_aspect_themes(self, p1: str, p2: str, aspect: str) -> List[str]:
        themes1 = self._get_planet_themes(p1, 0, '')
        themes2 = self._get_planet_themes(p2, 0, '')
        combined = themes1 + themes2
        return list(dict.fromkeys(combined))

    # ==================== HOUSE RULERS ====================

    def _build_house_rulers(self) -> List[Dict[str, Any]]:
        rulers = []
        for h in self.chart.get('houses', []):
            number = int(h.get('number', 0))
            sign = h.get('sign', 'unknown')
            degree = float(h.get('degree', 0.0))
            ruler = self._get_house_ruler(sign)
            rulers.append({
                "house": number,
                "cusp": f"{sign} {degree:.2f}°",
                "ruler": ruler,
                "ruler_sign": self._get_planet_sign(ruler),
                "ruler_house": self._get_planet_house(ruler),
                "ruler_retrograde": self._is_planet_retrograde(ruler),
            })
        return rulers

    def _is_planet_retrograde(self, planet_name: str) -> bool:
        for p in self.chart.get('planets', []):
            if p.get('name') == planet_name:
                return p.get('retrograde', False)
        return False

    # ==================== DISPOSITORS ====================

    def _build_dispositors(self) -> List[Dict[str, Any]]:
        dispositors = []
        planets_data = self.chart.get('planets', [])
        processed = set()
        for p in planets_data:
            planet_name = p.get('name', '')
            if planet_name in processed:
                continue
            processed.add(planet_name)
            sign = p.get('sign', '')
            info = find_dispositor(planet_name, sign, planets_data)
            if info.get('dispositor'):
                dispositors.append({
                    "planet": planet_name,
                    "dispositor": info.get('dispositor'),
                    "chain": info.get('chain', []),
                    "final_dispositor": info.get('final_dispositor'),
                    "chain_length": len(info.get('chain', [])),
                })
        return dispositors

    # ==================== DOMINANT CALCULATIONS ====================

    def _calculate_dominant_elements(self) -> Dict[str, int]:
        sign_elements = {
            'Aries': 'Fire', 'Leo': 'Fire', 'Sagittarius': 'Fire',
            'Taurus': 'Earth', 'Virgo': 'Earth', 'Capricorn': 'Earth',
            'Gemini': 'Air', 'Libra': 'Air', 'Aquarius': 'Air',
            'Cancer': 'Water', 'Scorpio': 'Water', 'Pisces': 'Water',
        }
        elements = {'Fire': 0, 'Earth': 0, 'Air': 0, 'Water': 0}
        element_weights = {
            'Sun': 3, 'Moon': 3, 'Mercury': 2, 'Venus': 2, 'Mars': 2,
            'Jupiter': 1, 'Saturn': 1, 'Uranus': 0.5, 'Neptune': 0.5, 'Pluto': 0.5,
        }
        for p in self.chart.get('planets', []):
            sign = p.get('sign', '')
            if sign in sign_elements:
                elem = sign_elements[sign]
                weight = element_weights.get(p.get('name', ''), 1)
                elements[elem] = elements.get(elem, 0) + weight
        return {k: round(v) for k, v in elements.items()}

    def _calculate_dominant_modalities(self) -> Dict[str, int]:
        sign_modalities = {
            'Aries': 'Cardinal', 'Cancer': 'Cardinal', 'Libra': 'Cardinal', 'Capricorn': 'Cardinal',
            'Taurus': 'Fixed', 'Leo': 'Fixed', 'Scorpio': 'Fixed', 'Aquarius': 'Fixed',
            'Gemini': 'Mutable', 'Virgo': 'Mutable', 'Sagittarius': 'Mutable', 'Pisces': 'Mutable',
        }
        modalities = {'Cardinal': 0, 'Fixed': 0, 'Mutable': 0}
        modality_weights = {
            'Sun': 3, 'Moon': 3, 'Mercury': 2, 'Venus': 2, 'Mars': 2,
            'Jupiter': 1, 'Saturn': 1, 'Uranus': 0.5, 'Neptune': 0.5, 'Pluto': 0.5,
        }
        for p in self.chart.get('planets', []):
            sign = p.get('sign', '')
            if sign in sign_modalities:
                mod = sign_modalities[sign]
                weight = modality_weights.get(p.get('name', ''), 1)
                modalities[mod] = modalities.get(mod, 0) + weight
        return {k: round(v) for k, v in modalities.items()}

    def _calculate_dominant_houses(self) -> Dict[str, int]:
        houses = {}
        for p in self.chart.get('planets', []):
            house = int(p.get('house', 0))
            if house > 0:
                houses[str(house)] = houses.get(str(house), 0) + 1
        return houses

    def _calculate_dominant_planets(self) -> Dict[str, int]:
        result = {}
        for name, weight in self.planet_weights.items():
            if any(p.get('name') == name for p in self.chart.get('planets', [])):
                result[name] = weight
        return result

    def _calculate_dominant_signs(self) -> Dict[str, int]:
        sign_weights = {
            'Sun': 3, 'Moon': 3, 'Mercury': 2, 'Venus': 2, 'Mars': 2,
            'Jupiter': 1, 'Saturn': 1, 'Uranus': 0.5, 'Neptune': 0.5, 'Pluto': 0.5,
        }
        signs = {}
        for p in self.chart.get('planets', []):
            sign = p.get('sign', '')
            name = p.get('name', '')
            if sign:
                signs[sign] = signs.get(sign, 0) + sign_weights.get(name, 1)
        return {k: round(v) for k, v in signs.items()}

    # ==================== ANGLE ASPECTS ====================

    def _build_angle_aspects(self) -> List[Dict[str, Any]]:
        subject = self.natal_calc._get_natal_subject()
        angles = get_angles(subject)
        aspects = []
        planets = self.chart.get('planets', [])
        aspect_targets = {
            'conjunction': 0,
            'opposition': 180,
            'trine': 120,
            'square': 90,
            'sextile': 60,
        }
        angle_names = ['ASC', 'MC', 'DSC', 'IC']
        for p in planets:
            planet_name = p.get('name')
            if not planet_name:
                continue
            deg = p.get('longitude')
            if deg is None:
                continue
            for angle_name in angle_names:
                angle_deg = angles.get(angle_name, 0)
                if angle_deg == 0:
                    continue
                diff = abs(deg - angle_deg) % 360
                if diff > 180:
                    diff = 360 - diff
                for aspect_name, target_angle in aspect_targets.items():
                    orb = 8 if aspect_name in ['conjunction', 'opposition'] else 6
                    if abs(diff - target_angle) <= orb:
                        aspects.append({
                            "planet": planet_name,
                            "planet_local": self.planet_names_ru.get(planet_name, planet_name),
                            "angle": angle_name,
                            "aspect": aspect_name,
                            "aspect_local": self._translate_aspect(aspect_name),
                            "orb": round(abs(diff - target_angle), 2),
                            "exact_angle": target_angle,
                            "actual_angle": diff,
                            "score": self._get_aspect_weight(planet_name, angle_name, aspect_name,
                                                             abs(diff - target_angle)),
                            "themes": self._get_planet_themes(planet_name, 0, '')
                        })
        return aspects

    # ==================== PATTERNS ====================

    def _build_patterns(self) -> List[Dict[str, Any]]:
        patterns = []
        planets = self.chart.get('planets', [])
        if not planets:
            return patterns

        longitudes = {p['name']: p.get('longitude', 0.0) for p in planets}
        signs = {p['name']: p.get('sign', '') for p in planets}
        houses = {p['name']: p.get('house', 0) for p in planets}

        # Стеллумы
        st_sign = self._find_cluster_by_key(signs, 3)
        if st_sign:
            patterns.append({
                "type": "stellium_sign",
                "objects": st_sign['objects'],
                "sign": st_sign['key'],
                "strength": len(st_sign['objects']) * 2,
                "themes": self._get_sign_themes(st_sign['key'])
            })
        st_house = self._find_cluster_by_key(houses, 3)
        if st_house:
            patterns.append({
                "type": "stellium_house",
                "objects": st_house['objects'],
                "house": st_house['key'],
                "strength": len(st_house['objects']) * 2,
                "themes": self._get_house_themes(st_house['key'])
            })
        st_deg = self._find_cluster_by_degree(longitudes, 3, 10.0)
        if st_deg:
            patterns.append({
                "type": "stellium_degree",
                "objects": st_deg['objects'],
                "center_degree": round(st_deg['center'], 2),
                "strength": len(st_deg['objects']) * 2,
                "themes": self._get_combined_themes(st_deg['objects'])
            })

        # Конфигурации
        for finder in [
            self._find_t_square,
            self._find_grand_trine,
            self._find_grand_cross,
            self._find_yod,
            self._find_kite,
            self._find_grand_sextile
        ]:
            pattern = finder(longitudes)
            if pattern:
                patterns.append(pattern)

        return patterns

    def _find_cluster_by_key(self, mapping: Dict[str, Any], threshold: int) -> Optional[Dict]:
        from collections import defaultdict
        groups = defaultdict(list)
        for planet, val in mapping.items():
            if val:
                groups[val].append(planet)
        for val, objs in groups.items():
            if len(objs) >= threshold:
                return {"key": val, "objects": objs}
        return None

    def _find_cluster_by_degree(self, longitudes: Dict[str, float], threshold: int, orb: float) -> Optional[Dict]:
        names = list(longitudes.keys())
        for i, p1 in enumerate(names):
            cluster = [p1]
            for p2 in names[i+1:]:
                if self._angle_between(longitudes[p1], longitudes[p2]) <= orb:
                    cluster.append(p2)
            if len(cluster) >= threshold:
                avg_deg = sum(longitudes[p] for p in cluster) / len(cluster)
                return {"objects": cluster, "center": avg_deg}
        return None

    def _angle_between(self, deg1: float, deg2: float) -> float:
        diff = abs(deg1 - deg2) % 360
        return diff if diff <= 180 else 360 - diff

    def _is_aspect(self, deg1: float, deg2: float, target: float, orb: float) -> bool:
        return abs(self._angle_between(deg1, deg2) - target) <= orb

    def _find_t_square(self, longitudes: Dict[str, float]) -> Optional[Dict]:
        names = list(longitudes.keys())
        for i, p1 in enumerate(names):
            for j in range(i+1, len(names)):
                p2 = names[j]
                if not self._is_aspect(longitudes[p1], longitudes[p2], 180, 8):
                    continue
                for k in range(len(names)):
                    if k == i or k == j:
                        continue
                    p3 = names[k]
                    if (self._is_aspect(longitudes[p3], longitudes[p1], 90, 8) and
                        self._is_aspect(longitudes[p3], longitudes[p2], 90, 8)):
                        return {
                            "type": "T-square",
                            "planets": [p1, p2, p3],
                            "apex": p3,
                            "strength": 8,
                            "themes": self._get_combined_themes([p1, p2, p3])
                        }
        return None

    def _find_grand_trine(self, longitudes: Dict[str, float]) -> Optional[Dict]:
        names = list(longitudes.keys())
        for i, p1 in enumerate(names):
            for j in range(i+1, len(names)):
                p2 = names[j]
                if not self._is_aspect(longitudes[p1], longitudes[p2], 120, 6):
                    continue
                for k in range(j+1, len(names)):
                    p3 = names[k]
                    if (self._is_aspect(longitudes[p1], longitudes[p3], 120, 6) and
                        self._is_aspect(longitudes[p2], longitudes[p3], 120, 6)):
                        return {
                            "type": "Grand Trine",
                            "planets": [p1, p2, p3],
                            "strength": 9,
                            "themes": self._get_combined_themes([p1, p2, p3])
                        }
        return None

    def _find_grand_cross(self, longitudes: Dict[str, float]) -> Optional[Dict]:
        names = list(longitudes.keys())
        if len(names) < 4:
            return None
        for i in range(len(names)):
            for j in range(i+1, len(names)):
                for k in range(j+1, len(names)):
                    for l in range(k+1, len(names)):
                        p1, p2, p3, p4 = names[i], names[j], names[k], names[l]
                        pairs = [(p1,p2),(p1,p3),(p1,p4),(p2,p3),(p2,p4),(p3,p4)]
                        count = 0
                        for a, b in pairs:
                            if (self._is_aspect(longitudes[a], longitudes[b], 90, 8) or
                                self._is_aspect(longitudes[a], longitudes[b], 180, 8)):
                                count += 1
                        if count >= 4:
                            return {
                                "type": "Grand Cross",
                                "planets": [p1, p2, p3, p4],
                                "strength": 8,
                                "themes": self._get_combined_themes([p1, p2, p3, p4])
                            }
        return None

    def _find_yod(self, longitudes: Dict[str, float]) -> Optional[Dict]:
        names = list(longitudes.keys())
        for i, p1 in enumerate(names):
            for j in range(i+1, len(names)):
                p2 = names[j]
                if not self._is_aspect(longitudes[p1], longitudes[p2], 60, 5):
                    continue
                for k in range(len(names)):
                    if k == i or k == j:
                        continue
                    p3 = names[k]
                    if (self._is_aspect(longitudes[p1], longitudes[p3], 150, 5) and
                        self._is_aspect(longitudes[p2], longitudes[p3], 150, 5)):
                        return {
                            "type": "Yod",
                            "planets": [p1, p2, p3],
                            "apex": p3,
                            "strength": 7,
                            "themes": self._get_combined_themes([p1, p2, p3])
                        }
        return None

    def _find_kite(self, longitudes: Dict[str, float]) -> Optional[Dict]:
        names = list(longitudes.keys())
        trines = []
        for i, p1 in enumerate(names):
            for j in range(i+1, len(names)):
                p2 = names[j]
                if not self._is_aspect(longitudes[p1], longitudes[p2], 120, 6):
                    continue
                for k in range(j+1, len(names)):
                    p3 = names[k]
                    if (self._is_aspect(longitudes[p1], longitudes[p3], 120, 6) and
                        self._is_aspect(longitudes[p2], longitudes[p3], 120, 6)):
                        trines.append([p1, p2, p3])
        if not trines:
            return None
        for tri in trines:
            p1, p2, p3 = tri
            for p4 in names:
                if p4 in (p1, p2, p3):
                    continue
                if (self._is_aspect(longitudes[p4], longitudes[p1], 60, 5) and
                    self._is_aspect(longitudes[p4], longitudes[p2], 60, 5)):
                    return {
                        "type": "Kite",
                        "planets": [p1, p2, p3, p4],
                        "strength": 8,
                        "themes": self._get_combined_themes([p1, p2, p3, p4])
                    }
                if (self._is_aspect(longitudes[p4], longitudes[p1], 60, 5) and
                    self._is_aspect(longitudes[p4], longitudes[p3], 60, 5)):
                    return {
                        "type": "Kite",
                        "planets": [p1, p2, p3, p4],
                        "strength": 8,
                        "themes": self._get_combined_themes([p1, p2, p3, p4])
                    }
                if (self._is_aspect(longitudes[p4], longitudes[p2], 60, 5) and
                    self._is_aspect(longitudes[p4], longitudes[p3], 60, 5)):
                    return {
                        "type": "Kite",
                        "planets": [p1, p2, p3, p4],
                        "strength": 8,
                        "themes": self._get_combined_themes([p1, p2, p3, p4])
                    }
        return None

    def _find_grand_sextile(self, longitudes: Dict[str, float]) -> Optional[Dict]:
        main_planets = ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                        'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']
        available = [p for p in main_planets if p in longitudes]
        if len(available) < 6:
            return None

        ORB = 10
        for combo in itertools.combinations(available, 6):
            sorted_combo = sorted(combo, key=lambda x: longitudes[x])
            ok = True
            for i in range(6):
                next_idx = (i + 1) % 6
                diff = (longitudes[sorted_combo[next_idx]] - longitudes[sorted_combo[i]]) % 360
                if abs(diff - 60) > ORB and abs(diff - 300) > ORB:
                    ok = False
                    break
            if ok:
                return {
                    "type": "Grand Sextile",
                    "planets": sorted_combo,
                    "strength": 9,
                    "themes": self._get_combined_themes(sorted_combo)
                }
        return None

    def _get_sign_themes(self, sign: str) -> List[str]:
        sign_themes = {
            'Aries': ['action', 'initiative', 'courage'],
            'Taurus': ['stability', 'finance', 'sensuality'],
            'Gemini': ['communication', 'learning', 'social'],
            'Cancer': ['family', 'emotions', 'home'],
            'Leo': ['self_expression', 'creativity', 'leadership'],
            'Virgo': ['health', 'service', 'detail'],
            'Libra': ['relationships', 'balance', 'partnership'],
            'Scorpio': ['transformation', 'intensity', 'power'],
            'Sagittarius': ['expansion', 'travel', 'philosophy'],
            'Capricorn': ['career', 'ambition', 'structure'],
            'Aquarius': ['innovation', 'friendship', 'individuality'],
            'Pisces': ['intuition', 'spirituality', 'compassion'],
        }
        return sign_themes.get(sign, ['unknown'])

    def _get_house_themes(self, house: int) -> List[str]:
        house_themes = {
            1: ['self_expression', 'appearance', 'personality'],
            2: ['finance', 'values', 'resources'],
            3: ['communication', 'learning', 'siblings'],
            4: ['home', 'family', 'roots'],
            5: ['creativity', 'children', 'leisure'],
            6: ['health', 'work', 'service'],
            7: ['partnerships', 'relationships', 'marriage'],
            8: ['transformation', 'shared_resources', 'intimacy'],
            9: ['travel', 'philosophy', 'higher_education'],
            10: ['career', 'status', 'ambition'],
            11: ['friendships', 'groups', 'hopes'],
            12: ['spirituality', 'subconscious', 'solitude'],
        }
        return house_themes.get(house, ['unknown'])

    def _get_combined_themes(self, planet_names: List[str]) -> List[str]:
        themes = []
        for name in planet_names:
            themes.extend(self._get_planet_themes(name, 0, ''))
        return list(dict.fromkeys(themes))

    # ==================== SUMMARY ====================

    def _build_summary(self) -> Dict[str, Any]:
        planets = self.chart.get('planets', [])
        aspects = self.chart.get('aspects', [])

        dominant_planets = sorted(self.planet_weights.items(), key=lambda x: x[1], reverse=True)[:3]
        dominant_planets = [{"planet": p[0], "weight": p[1]} for p in dominant_planets if any(pl.get('name') == p[0] for pl in planets)]

        elements = self._calculate_dominant_elements()
        dominant_elements = sorted(elements.items(), key=lambda x: x[1], reverse=True)[:2]
        dominant_elements = [{"element": e[0], "value": e[1]} for e in dominant_elements]

        modalities = self._calculate_dominant_modalities()
        dominant_modalities = sorted(modalities.items(), key=lambda x: x[1], reverse=True)[:2]
        dominant_modalities = [{"modality": m[0], "value": m[1]} for m in dominant_modalities]

        signs = self._calculate_dominant_signs()
        dominant_signs = sorted(signs.items(), key=lambda x: x[1], reverse=True)[:3]
        dominant_signs = [{"sign": s[0], "value": s[1]} for s in dominant_signs]

        houses = self._calculate_dominant_houses()
        dominant_houses = sorted(houses.items(), key=lambda x: x[1], reverse=True)[:3]
        dominant_houses = [{"house": h[0], "count": h[1]} for h in dominant_houses]

        themes_data = self._build_themes()
        core_themes = sorted(themes_data.items(), key=lambda x: x[1]['score'], reverse=True)[:5]
        core_themes = [{"theme": t[0], "score": t[1]['score']} for t in core_themes]

        strong_list = []
        for a in aspects:
            weight = float(a.get('weight', 0))
            strong_list.append((a, weight))
        strong_list.sort(key=lambda x: x[1], reverse=True)
        strong_aspects = []
        for a, _ in strong_list[:3]:
            strong_aspects.append({
                "p1": a.get('p1', ''),
                "p2": a.get('p2', ''),
                "aspect": a.get('aspect', ''),
                "orb": a.get('orb', 0)
            })

        tension_list = []
        for a in aspects:
            aspect = a.get('aspect', '').lower()
            if aspect in ('square', 'opposition'):
                orb_val = float(a.get('orb', 10))
                if orb_val < 5:
                    weight = float(a.get('weight', 0))
                    tension_list.append((a, weight))
        tension_list.sort(key=lambda x: x[1], reverse=True)
        major_tensions = []
        for a, _ in tension_list[:3]:
            major_tensions.append({
                "p1": a.get('p1', ''),
                "p2": a.get('p2', ''),
                "aspect": a.get('aspect', ''),
                "orb": a.get('orb', 0)
            })

        resource_list = []
        for a in aspects:
            aspect = a.get('aspect', '').lower()
            if aspect in ('trine', 'sextile'):
                orb_val = float(a.get('orb', 10))
                if orb_val < 5:
                    weight = float(a.get('weight', 0))
                    resource_list.append((a, weight))
        resource_list.sort(key=lambda x: x[1], reverse=True)
        major_resources = []
        for a, _ in resource_list[:3]:
            major_resources.append({
                "p1": a.get('p1', ''),
                "p2": a.get('p2', ''),
                "aspect": a.get('aspect', ''),
                "orb": a.get('orb', 0)
            })

        return {
            "dominant_planets": dominant_planets,
            "dominant_elements": dominant_elements,
            "dominant_modalities": dominant_modalities,
            "dominant_signs": dominant_signs,
            "dominant_houses": dominant_houses,
            "core_themes": core_themes,
            "strongest_aspects": strong_aspects,
            "major_tensions": major_tensions,
            "major_resources": major_resources,
        }

    # ==================== TRANSITS ====================

    def _build_transits(self, telegram_id: Optional[int] = None) -> Dict[str, Any]:
        transit_calc = TransitHoroscopeCalculator(
            self.user_data,
            self.lang,
            natal_calc=self.natal_calc,
            telegram_id=telegram_id
        )
        transit_data = transit_calc.calculate()

        transit_planets = self._build_transit_planets(transit_calc)
        transit_aspects = self._build_transit_aspects(transit_calc, transit_data)
        active_periods = self._build_active_periods(transit_aspects)

        return {
            "planets": transit_planets,
            "aspects": transit_aspects,
            "active_periods": active_periods,
        }

    def _build_transit_planets(self, transit_calc) -> List[Dict[str, Any]]:
        transit_chart = transit_calc._get_transit_chart()
        planets = []
        for key in ['sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter', 'saturn',
                    'uranus', 'neptune', 'pluto', 'chiron']:
            if key in transit_chart:
                obj = transit_chart[key]
                if isinstance(obj, dict):
                    planet_name = key.capitalize()
                    longitude = obj.get('position', 0.0)
                    transit_house = transit_calc._get_transit_house_for_planet(longitude)
                    planets.append({
                        "name": planet_name,
                        "name_local": self.planet_names_ru.get(planet_name, planet_name),
                        "longitude": longitude,
                        "speed": obj.get('speed', 0.0),
                        "retrograde": obj.get('retrograde', False),
                        "sign": obj.get('sign', 'unknown'),
                        "degree": longitude % 30,
                        "house": transit_house,
                        "themes": self._get_planet_themes(planet_name, transit_house, obj.get('sign', ''))
                    })
        return planets

    def _build_transit_aspects(self, transit_calc, transit_data: Dict) -> List[Dict[str, Any]]:
        aspects = []
        raw_aspects = transit_data.get('transit_aspects', '')
        if not raw_aspects or raw_aspects == "Нет значимых транзитных аспектов":
            return aspects

        transit_calc._get_transit_chart()
        if not transit_calc.transit_houses:
            transit_calc.transit_chart = None
            transit_calc._get_transit_chart()

        lines = raw_aspects.strip().split('\n')
        for line in lines:
            if '→' not in line:
                continue
            parts = [p.strip() for p in line.split('→')]
            if len(parts) != 4:
                continue

            transit_planet = parts[0].replace('Transit ', '')
            natal_planet = parts[1].replace('Natal ', '')
            aspect = parts[2]
            orb_str = parts[3].replace('°', '')
            try:
                orb = float(orb_str)
            except ValueError:
                continue

            phase = self._determine_transit_phase(transit_planet, orb, transit_calc)
            exact_date = self._estimate_exact_date(transit_planet, orb, transit_calc)

            transit_chart = transit_calc._get_transit_chart()
            transit_key = transit_planet.lower()
            if transit_key in transit_chart:
                obj = transit_chart[transit_key]
                if isinstance(obj, dict):
                    transit_longitude = obj.get('position', 0.0)
                else:
                    transit_longitude = getattr(obj, 'position', 0.0)
            else:
                transit_longitude = 0.0

            transit_house = transit_calc._get_transit_house_for_planet(transit_longitude)
            natal_house = self._get_planet_house(natal_planet)
            transit_sign = self._get_transit_planet_sign(transit_planet, transit_calc)
            natal_sign = self._get_planet_sign(natal_planet)

            score = self._calculate_transit_score(transit_planet, natal_planet, aspect, orb)
            confidence = self._calculate_confidence(score, orb)
            passes = self._calculate_passes(transit_planet, natal_planet, aspect)

            aspects.append({
                "transit_planet": transit_planet,
                "transit_planet_local": self.planet_names_ru.get(transit_planet, transit_planet),
                "natal_planet": natal_planet,
                "natal_planet_local": self.planet_names_ru.get(natal_planet, natal_planet),
                "aspect": aspect,
                "aspect_local": self._translate_aspect(aspect),
                "orb": round(orb, 2),
                "exact_angle": self._get_exact_angle(aspect),
                "actual_angle": orb,
                "phase": phase,
                "transit_house": transit_house,
                "natal_house": natal_house,
                "transit_sign": transit_sign,
                "natal_sign": natal_sign,
                "exact_date": exact_date,
                "passes": passes,
                "themes": self._get_aspect_themes(transit_planet, natal_planet, aspect),
                "life_areas": self._get_life_areas(aspect, transit_planet, natal_planet),
                "score": round(score, 2),
                "confidence": round(confidence, 2),
            })

        return aspects

    def _determine_transit_phase(self, transit_planet: str, orb: float, transit_calc) -> str:
        speed = self._get_planet_speed(transit_planet, is_transit=True, transit_calc=transit_calc)
        if abs(speed) < 0.01:
            return 'stationary'
        if speed > 0:
            return 'applying'
        elif speed < 0:
            return 'separating'
        return 'unknown'

    def _estimate_exact_date(self, transit_planet: str, orb: float, transit_calc) -> Optional[str]:
        speed = self._get_planet_speed(transit_planet, is_transit=True, transit_calc=transit_calc)
        if abs(speed) < 0.001:
            return None
        days_to_exact = orb / abs(speed)
        exact_date = datetime.now() + timedelta(days=days_to_exact)
        return exact_date.strftime('%Y-%m-%d')

    def _get_planet_speed(self, planet: str, is_transit: bool = False, transit_calc=None) -> float:
        AVERAGE_SPEEDS = {
            'Sun': 0.9856, 'Moon': 13.1764, 'Mercury': 1.383,
            'Venus': 1.2, 'Mars': 0.524, 'Jupiter': 0.083,
            'Saturn': 0.033, 'Uranus': 0.012, 'Neptune': 0.006,
            'Pluto': 0.004, 'Chiron': 0.02, 'Mean_Lilith': 0.1,
            'True_North_Lunar_Node': -0.05, 'True_South_Lunar_Node': 0.05,
        }
        try:
            if is_transit and transit_calc is not None:
                transit_subject = transit_calc._get_transit_subject()
                if hasattr(transit_subject, 'planets'):
                    for p in transit_subject.planets:
                        if p.name.lower() == planet.lower():
                            return p.speed if hasattr(p, 'speed') else AVERAGE_SPEEDS.get(planet, 0.0)
            else:
                subject = self.natal_calc._get_natal_subject()
                if hasattr(subject, 'planets'):
                    for p in subject.planets:
                        if p.name.lower() == planet.lower():
                            return p.speed if hasattr(p, 'speed') else AVERAGE_SPEEDS.get(planet, 0.0)
        except:
            pass
        return AVERAGE_SPEEDS.get(planet, 0.0)

    def _get_transit_planet_sign(self, planet: str, transit_calc) -> str:
        try:
            transit_chart = transit_calc._get_transit_chart()
            key = planet.lower()
            if key in transit_chart:
                obj = transit_chart[key]
                return obj.get('sign', 'unknown') if isinstance(obj, dict) else getattr(obj, 'sign', 'unknown')
        except:
            pass
        return 'unknown'

    def _calculate_transit_score(self, transit_planet: str, natal_planet: str, aspect: str, orb: float) -> float:
        base = 5
        planet_weight = (self.planet_weights.get(transit_planet, 5) + self.planet_weights.get(natal_planet, 5)) / 2
        aspect_weight = {
            'conjunction': 10, 'opposition': 9, 'trine': 8,
            'square': 7, 'sextile': 6,
        }.get(aspect.lower(), 5)
        orb_penalty = orb / 10
        score = (base + planet_weight + aspect_weight) / 3 - orb_penalty
        return max(1, min(10, score))

    def _calculate_confidence(self, score: float, orb: float) -> float:
        confidence = (score / 10) * (1 - orb / 10)
        return max(0.1, min(1.0, confidence))

    def _calculate_passes(self, transit_planet: str, natal_planet: str, aspect: str) -> List[Dict]:
        slow_planets = ['Saturn', 'Jupiter', 'Uranus', 'Neptune', 'Pluto']
        if transit_planet not in slow_planets:
            return []
        passes = []
        base_date = datetime.now()
        for i in range(3):
            date = base_date + timedelta(days=120 * i)
            passes.append({
                "number": i + 1,
                "date": date.strftime('%Y-%m-%d'),
                "direction": "direct" if i % 2 == 0 else "retrograde"
            })
        return passes

    def _get_life_areas(self, aspect: str, transit_planet: str, natal_planet: str) -> List[str]:
        areas = []
        if 'Saturn' in transit_planet or 'Saturn' in natal_planet:
            areas.extend(['career', 'responsibility'])
        if 'Venus' in transit_planet or 'Venus' in natal_planet:
            areas.extend(['relationships', 'love'])
        if 'Mars' in transit_planet or 'Mars' in natal_planet:
            areas.extend(['action', 'conflict'])
        if 'Jupiter' in transit_planet or 'Jupiter' in natal_planet:
            areas.extend(['growth', 'expansion'])
        if 'Moon' in transit_planet or 'Moon' in natal_planet:
            areas.extend(['emotions', 'family'])
        if 'Sun' in transit_planet or 'Sun' in natal_planet:
            areas.extend(['identity', 'self_expression'])
        return list(set(areas))

    def _build_active_periods(self, transit_aspects: List[Dict]) -> List[Dict]:
        periods = []
        themes = {}
        for asp in transit_aspects:
            for theme in asp.get('themes', []):
                if theme not in themes:
                    themes[theme] = []
                themes[theme].append(asp)

        for theme, aspects in themes.items():
            if not aspects:
                continue
            avg_score = sum(a['score'] for a in aspects) / len(aspects)
            avg_conf = sum(a['confidence'] for a in aspects) / len(aspects)
            dates = [a.get('exact_date') for a in aspects if a.get('exact_date')]
            if dates:
                start = min(dates)
                end = max(dates)
            else:
                start = datetime.now().strftime('%Y-%m-%d')
                end = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
            evidence = []
            for a in aspects[:5]:
                evidence.append({
                    "transit": a['transit_planet_local'],
                    "natal": a['natal_planet_local'],
                    "aspect": a['aspect_local'],
                    "orb": a['orb'],
                    "phase": a['phase'],
                    "exact_date": a.get('exact_date'),
                    "transit_house": a['transit_house'],
                    "natal_house": a['natal_house'],
                    "score": a['score'],
                    "confidence": a['confidence']
                })
            periods.append({
                "start": start,
                "end": end,
                "theme": theme,
                "intensity": round(avg_score, 1),
                "confidence": round(avg_conf, 2),
                "score": round(avg_score, 2),
                "evidence": evidence
            })
        return periods

    # ==================== PROGRESSIONS ====================

    def _build_progressions(self) -> Dict[str, Any]:
        progression_str = self.natal_calc._get_progression_aspects_string(self.lang)
        if not progression_str or "Ошибка" in progression_str:
            return {"planets": [], "aspects": []}

        aspects = []
        lines = progression_str.strip().split('\n')
        for line in lines:
            if '→' not in line:
                continue
            parts = [p.strip() for p in line.split('→')]
            if len(parts) != 4:
                continue

            progressed = parts[0].replace('Progressed ', '')
            natal = parts[1].replace('Natal ', '')
            aspect = parts[2]
            orb_str = parts[3].replace('°', '')
            try:
                orb = float(orb_str)
            except ValueError:
                continue

            phase = 'applying' if orb < 0.5 else 'separating'
            exact_date = self._estimate_exact_date(progressed, orb, transit_calc=None)

            score = self._calculate_transit_score(progressed, natal, aspect, orb)
            aspects.append({
                "progressed_planet": progressed,
                "progressed_planet_local": self.planet_names_ru.get(progressed, progressed),
                "natal_planet": natal,
                "natal_planet_local": self.planet_names_ru.get(natal, natal),
                "aspect": aspect,
                "aspect_local": self._translate_aspect(aspect),
                "orb": round(orb, 2),
                "exact_angle": self._get_exact_angle(aspect),
                "actual_angle": orb,
                "phase": phase,
                "progressed_date": datetime.now().strftime('%Y-%m-%d'),
                "progressed_longitude": 0.0,
                "natal_longitude": 0.0,
                "exact_date": exact_date,
                "natal_house": self._get_planet_house(natal),
                "themes": self._get_aspect_themes(progressed, natal, aspect),
                "score": round(score, 2),
                "confidence": round(self._calculate_confidence(score, orb), 2),
            })

        return {"planets": [], "aspects": aspects}

    # ==================== THEMES ====================

    def _build_themes(self, include_transits: bool = True) -> Dict[str, Any]:
        themes = {}

        # 1. Натальные планеты (всегда)
        for p in self.chart.get('planets', []):
            name = p['name']
            weight = self.planet_weights.get(name, 5)
            for theme in self._get_planet_themes(name, p.get('house', 0), p.get('sign', '')):
                self._add_evidence(themes, theme, 'natal_planet', name, f"{name} weight {weight}", weight)

        # 2. Дома (управители) (всегда)
        for ruler in self._build_house_rulers():
            house = ruler['house']
            ruler_name = ruler['ruler']
            if ruler_name != 'unknown':
                for theme in self._get_house_themes(house):
                    self._add_evidence(themes, theme, 'house_ruler', f"House {house}", f"ruler {ruler_name}", 6)
                for theme in self._get_planet_themes(ruler_name, 0, ''):
                    self._add_evidence(themes, theme, 'house_ruler', f"House {house}", f"ruler {ruler_name}", 6)

        # 3. Натальные аспекты (всегда)
        for a in self.chart.get('aspects', []):
            orb_val = float(a.get('orb', 10))
            if orb_val <= 3:
                weight = float(a.get('weight', 5))
                p1, p2 = a['p1'], a['p2']
                for theme in self._get_aspect_themes(p1, p2, a['aspect']):
                    self._add_evidence(themes, theme, 'natal_aspect', f"{p1} {a['aspect']} {p2}", f"orb {orb_val:.2f}°",
                                       weight)

        # 4. Аспекты к углам (всегда)
        for angle_aspect in self._build_angle_aspects():
            weight = float(angle_aspect.get('score', 5))
            theme = angle_aspect.get('themes', ['unknown'])[0]
            self._add_evidence(themes, theme, 'angle_aspect',
                               f"{angle_aspect['planet']} {angle_aspect['aspect']} {angle_aspect['angle']}",
                               f"orb {angle_aspect.get('orb', 0):.2f}°", weight)

        # 5. Паттерны (всегда)
        for pat in self._build_patterns():
            strength = float(pat.get('strength', 5))
            for theme in pat.get('themes', []):
                self._add_evidence(themes, theme, 'pattern', pat['type'], f"strength {strength}", strength)

        # 6. Транзиты (только если include_transits)
        if include_transits:
            transit_data = self._build_transits(telegram_id=self.telegram_id)
            for ta in transit_data.get('aspects', []):
                score_val = float(ta.get('score', 0))
                if score_val > 6:
                    for theme in ta.get('themes', []):
                        self._add_evidence(themes, theme, 'transit',
                                           f"{ta['transit_planet']} {ta['aspect']} {ta['natal_planet']}",
                                           f"score {score_val}", score_val)

        # 7. Прогрессии (только если include_transits)
        if include_transits:
            prog_data = self._build_progressions()
            for pa in prog_data.get('aspects', []):
                score_val = float(pa.get('score', 0))
                if score_val > 6:
                    for theme in pa.get('themes', []):
                        self._add_evidence(themes, theme, 'progression',
                                           f"{pa['progressed_planet']} {pa['aspect']} {pa['natal_planet']}",
                                           f"score {score_val}", score_val)

        # Финальный расчёт
        result = {}
        for theme, data in themes.items():
            ev = data['evidence']
            total_weight = sum(e['weight'] for e in ev)
            count = len(ev)
            strong_count = sum(1 for e in ev if e['weight'] >= 7)
            exact_aspect_count = sum(1 for e in ev if e['type'] == 'natal_aspect' and e.get('orb', 10) <= 2)
            repeating = count >= 3 and strong_count >= 2
            avg_weight = total_weight / count if count else 0
            score = min(10, avg_weight * 1.2)
            confidence = min(1.0, (count / 10) * (score / 10) + 0.2)
            result[theme] = {
                "score": round(score, 2),
                "confidence": round(confidence, 2),
                "evidence_count": count,
                "strong_evidence_count": strong_count,
                "exact_aspect_count": exact_aspect_count,
                "repeating_theme": repeating,
                "evidence": ev[:10]
            }
        return result

    def _add_evidence(self, themes: Dict, theme: str, source_type: str, source: str, description: str, weight: float):
        if theme not in themes:
            themes[theme] = {"evidence": []}
        themes[theme]["evidence"].append({
            "type": source_type,
            "source": source,
            "description": description,
            "weight": round(weight, 2)
        })

    # ==================== TIMELINE ====================

    def _build_timeline(self) -> List[Dict[str, Any]]:
        timeline = []
        transit_data = self._build_transits(telegram_id=self.telegram_id)
        for ta in transit_data.get('aspects', []):
            if ta.get('exact_date'):
                timeline.append({
                    "date": ta['exact_date'],
                    "event_type": "transit",
                    "description": f"{ta['transit_planet']} {ta['aspect']} {ta['natal_planet']}",
                    "score": ta.get('score', 0),
                    "theme": ta.get('themes', ['unknown'])[0] if ta.get('themes') else 'unknown'
                })
        prog_data = self._build_progressions()
        for pa in prog_data.get('aspects', []):
            if pa.get('exact_date'):
                timeline.append({
                    "date": pa['exact_date'],
                    "event_type": "progression",
                    "description": f"{pa['progressed_planet']} {pa['aspect']} {pa['natal_planet']}",
                    "score": pa.get('score', 0),
                    "theme": pa.get('themes', ['unknown'])[0] if pa.get('themes') else 'unknown'
                })
        timeline.sort(key=lambda x: x['date'])
        return timeline[:20]