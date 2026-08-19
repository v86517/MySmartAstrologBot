# bot/calculators/context_builder.py
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)


class AstrologyContextBuilder:
    """
    Класс для построения текстового контекста для LLM на основе астрологических данных.
    Формирует три типа контекста: DAY, MONTH, YEAR.
    """

    # Веса планет для сортировки (не для расчёта, только для приоритизации)
    PLANET_WEIGHTS = {
        'Sun': 1.00,
        'Moon': 0.70,
        'Mercury': 0.85,
        'Venus': 0.85,
        'Mars': 0.90,
        'Jupiter': 1.00,
        'Saturn': 1.00,
        'Uranus': 1.00,
        'Neptune': 1.00,
        'Pluto': 1.00,
        'Chiron': 0.70,
        'Mean_Lilith': 0.40,
        'True_North_Lunar_Node': 0.60,
        'True_South_Lunar_Node': 0.60,
    }

    # Пороги для фильтрации по типам
    THRESHOLDS = {
        'DAY': {
            'score': 6.8,
            'confidence': 0.30,
            'orb_planets': {
                'Sun': 3.0, 'Moon': 3.0, 'Mercury': 3.0, 'Venus': 3.0, 'Mars': 3.0,
                'Jupiter': 2.0, 'Saturn': 2.0, 'Uranus': 2.0, 'Neptune': 2.0, 'Pluto': 2.0,
                'Chiron': 3.0, 'Mean_Lilith': 4.0, 'True_North_Lunar_Node': 4.0, 'True_South_Lunar_Node': 4.0
            },
            'orb_angles': 3.0,
            'max_aspects': 12,
            'max_themes': 6,
            'max_transits': 15,
        },
        'MONTH': {
            'score': 6.5,
            'confidence': 0.35,
            'orb_planets': {
                'Sun': 5.0, 'Moon': 5.0, 'Mercury': 5.0, 'Venus': 5.0, 'Mars': 5.0,
                'Jupiter': 4.0, 'Saturn': 4.0, 'Uranus': 3.0, 'Neptune': 3.0, 'Pluto': 3.0,
                'Chiron': 5.0, 'Mean_Lilith': 6.0, 'True_North_Lunar_Node': 6.0, 'True_South_Lunar_Node': 6.0
            },
            'orb_angles': 5.0,
            'max_aspects': 12,
            'max_themes': 8,
            'max_transits': 25,
        },
        'YEAR': {
            'score': 6.0,
            'confidence': 0.40,
            'orb_planets': {
                'Sun': 5.0, 'Moon': 5.0, 'Mercury': 5.0, 'Venus': 5.0, 'Mars': 5.0,
                'Jupiter': 4.0, 'Saturn': 4.0, 'Uranus': 3.0, 'Neptune': 3.0, 'Pluto': 3.0,
                'Chiron': 5.0, 'Mean_Lilith': 6.0, 'True_North_Lunar_Node': 6.0, 'True_South_Lunar_Node': 6.0
            },
            'orb_angles': 5.0,
            'max_aspects': 15,
            'max_themes': 10,
            'max_transits': 30,
        }
    }

    # Названия знаков и планет для локализации (русский)
    SIGN_NAMES_RU = {
        'Aries': 'Овен', 'Taurus': 'Телец', 'Gemini': 'Близнецы',
        'Cancer': 'Рак', 'Leo': 'Лев', 'Virgo': 'Дева',
        'Libra': 'Весы', 'Scorpio': 'Скорпион', 'Sagittarius': 'Стрелец',
        'Capricorn': 'Козерог', 'Aquarius': 'Водолей', 'Pisces': 'Рыбы'
    }
    PLANET_NAMES_RU = {
        'Sun': 'Солнце', 'Moon': 'Луна', 'Mercury': 'Меркурий',
        'Venus': 'Венера', 'Mars': 'Марс', 'Jupiter': 'Юпитер',
        'Saturn': 'Сатурн', 'Uranus': 'Уран', 'Neptune': 'Нептун',
        'Pluto': 'Плутон', 'Chiron': 'Хирон', 'Mean_Lilith': 'Лилит',
        'True_North_Lunar_Node': 'Северный узел', 'True_South_Lunar_Node': 'Южный узел'
    }
    ASPECT_NAMES_RU = {
        'conjunction': 'соединение',
        'opposition': 'оппозиция',
        'trine': 'трин',
        'square': 'квадрат',
        'sextile': 'секстиль',
        'quincunx': 'квинконкс',
        'semisextile': 'полусекстиль',
        'sesquiquadrate': 'полутораквадрат',
        'quintile': 'квинтиль',
        'biquintile': 'биквинтиль'
    }

    def __init__(self, user_data: Dict[str, Any], natal_data: Dict[str, Any],
                 transit_data: Dict[str, Any], lang: str = 'ru'):
        self.user_data = user_data
        self.natal_data = natal_data
        self.transit_data = transit_data
        self.lang = lang
        self.natal = natal_data.get('natal', {})
        self.planets = self.natal.get('planets', [])
        self.houses = self.natal.get('houses', [])
        self.aspects = self.natal.get('aspects', [])
        self.angles = self.natal.get('angles', {})
        self.transit_aspects = transit_data.get('transit_aspects', [])
        self.transit_angle_aspects = transit_data.get('transit_angle_aspects', [])
        self.transit_ingresses = transit_data.get('transit_ingresses', [])
        self.transit_stations = transit_data.get('transit_stations', [])
        self.transit_passes = transit_data.get('transit_passes', [])
        self.transit_themes = transit_data.get('transit_themes', {})
        self.active_periods = transit_data.get('active_periods', [])
        self.period = transit_data.get('period', 'today')
        self.start_utc = transit_data.get('start_utc')
        self.end_utc = transit_data.get('end_utc')
        self.birth_date = user_data.get('birth_date', '')
        self.birth_time = user_data.get('birth_time', '')
        self.birth_place = user_data.get('birth_place', '')
        self.name = user_data.get('name', '')

    # ---------- ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ----------
    def _format_planet(self, planet: Dict) -> str:
        """Форматирует натальную планету для вывода."""
        name = planet.get('name', '')
        sign_raw = planet.get('sign', '')
        sign = self.SIGN_NAMES_RU.get(sign_raw, sign_raw)
        degree = planet.get('degree', 0.0)
        house = planet.get('house', 0)
        retro = planet.get('retrograde', False)
        retr_str = ", ретроградный" if retro else ""
        return f"{self.PLANET_NAMES_RU.get(name, name)} — {sign} {degree:.2f}°, дом {house}{retr_str}"

    def _format_natal_aspect(self, asp: Dict) -> str:
        """Форматирует натальный аспект."""
        p1 = self.PLANET_NAMES_RU.get(asp.get('p1', ''), asp.get('p1', ''))
        p2 = self.PLANET_NAMES_RU.get(asp.get('p2', ''), asp.get('p2', ''))
        aspect = self.ASPECT_NAMES_RU.get(asp.get('aspect', ''), asp.get('aspect', ''))
        orb = asp.get('orb', 0.0)
        return f"{p1} {aspect} {p2}, орб {orb:.2f}°"

    def _format_transit_aspect(self, asp: Dict) -> str:
        """Форматирует транзитный аспект для вывода."""
        t_planet = self.PLANET_NAMES_RU.get(asp.get('transit_planet', ''), asp.get('transit_planet', ''))
        n_planet = self.PLANET_NAMES_RU.get(asp.get('natal_planet', ''), asp.get('natal_planet', ''))
        aspect = self.ASPECT_NAMES_RU.get(asp.get('aspect', ''), asp.get('aspect', ''))
        orb = asp.get('orb', 0.0)
        phase = asp.get('phase', '')
        score = asp.get('score', 0.0)
        conf = asp.get('confidence', 0.0)
        exact_date = asp.get('exact_date', '')
        line = f"{t_planet} {aspect} натальный {n_planet}"
        if exact_date:
            line = f"{exact_date} — {line}"
        line += f", орб {orb:.2f}°, {phase}, score {score:.2f}, confidence {conf:.2f}"
        return line

    def _get_sign_name(self, sign_abbr: str) -> str:
        return self.SIGN_NAMES_RU.get(sign_abbr, sign_abbr)

    def _get_planet_name(self, name: str) -> str:
        return self.PLANET_NAMES_RU.get(name, name)

    def _filter_natal_aspects(self, limit: int = 12) -> List[Dict]:
        """Фильтрует натальные аспекты, оставляя сильнейшие."""
        # Сортируем по весу (если есть) и орбу
        def key_func(a):
            weight = a.get('weight', 0.0)
            orb = a.get('orb', 10.0)
            # Приоритет: высокий вес, малый орб
            return (weight, -orb)
        sorted_aspects = sorted(self.aspects, key=key_func, reverse=True)
        # Оставляем только уникальные (по паре планет + аспект)
        seen = set()
        filtered = []
        for a in sorted_aspects:
            key = (a.get('p1'), a.get('p2'), a.get('aspect'))
            if key not in seen:
                seen.add(key)
                filtered.append(a)
            if len(filtered) >= limit:
                break
        return filtered

    def _filter_transit_aspects(self, type_: str) -> List[Dict]:
        """Фильтрует транзитные аспекты в зависимости от типа прогноза."""
        thresholds = self.THRESHOLDS[type_]
        orb_planets = thresholds['orb_planets']
        score_min = thresholds['score']
        conf_min = thresholds['confidence']
        aspects = self.transit_aspects

        # Функция для проверки, попадает ли аспект в период
        def in_period(date_str):
            if not date_str or not self.start_utc or not self.end_utc:
                return True
            try:
                dt = datetime.strptime(date_str, '%Y-%m-%d')
                # Для DAY проверяем точное совпадение с днём
                if type_ == 'DAY':
                    target_date = self.start_utc.date()
                    return dt.date() == target_date
                else:
                    return self.start_utc.date() <= dt.date() <= self.end_utc.date()
            except:
                return False

        filtered = []
        for a in aspects:
            # Проверяем дату
            if not in_period(a.get('exact_date')):
                continue
            # Проверяем score и confidence
            if a.get('score', 0) < score_min:
                continue
            if a.get('confidence', 0) < conf_min:
                continue
            # Проверяем орб по планете
            t_planet = a.get('transit_planet', '')
            max_orb = orb_planets.get(t_planet, 5.0)
            if a.get('orb', 0.0) > max_orb:
                continue
            filtered.append(a)

        # Сортировка по score (desc) и орбу (asc)
        filtered.sort(key=lambda x: (-x.get('score', 0), x.get('orb', 10)))
        # Ограничиваем количество
        max_transits = thresholds['max_transits']
        return filtered[:max_transits]

    def _filter_transit_angle_aspects(self, type_: str) -> List[Dict]:
        """Фильтрует транзитные аспекты к углам."""
        thresholds = self.THRESHOLDS[type_]
        orb_angles = thresholds['orb_angles']
        score_min = thresholds['score']
        aspects = self.transit_angle_aspects

        def in_period(date_str):
            if not date_str or not self.start_utc or not self.end_utc:
                return True
            try:
                dt = datetime.strptime(date_str, '%Y-%m-%d')
                if type_ == 'DAY':
                    target_date = self.start_utc.date()
                    return dt.date() == target_date
                else:
                    return self.start_utc.date() <= dt.date() <= self.end_utc.date()
            except:
                return False

        filtered = []
        for a in aspects:
            if not in_period(a.get('exact_date')):
                continue
            if a.get('orb', 10.0) > orb_angles:
                continue
            if a.get('score', 0) < score_min:
                continue
            filtered.append(a)
        filtered.sort(key=lambda x: (-x.get('score', 0), x.get('orb', 10)))
        return filtered

    def _filter_ingresses(self, type_: str) -> List[Dict]:
        """Фильтрует ингрессии."""
        if type_ == 'DAY':
            # Только переходы основных планет сегодня
            today = self.start_utc.strftime('%Y-%m-%d') if self.start_utc else None
            important = ['Sun', 'Mercury', 'Venus', 'Mars', 'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']
            filtered = []
            for ing in self.transit_ingresses:
                if ing.get('date') != today:
                    continue
                if ing.get('planet') in important:
                    filtered.append(ing)
            return filtered
        elif type_ == 'MONTH':
            # Оставляем только переходы основных планет, удаляем Moon
            filtered = []
            for ing in self.transit_ingresses:
                if ing.get('planet') == 'Moon':
                    continue
                # Проверяем, что дата в пределах месяца
                if self.start_utc and self.end_utc:
                    try:
                        dt = datetime.strptime(ing.get('date', ''), '%Y-%m-%d')
                        if self.start_utc.date() <= dt.date() <= self.end_utc.date():
                            filtered.append(ing)
                    except:
                        continue
            return filtered
        else:  # YEAR
            # Оставляем только переходы медленных планет и важные смены домов
            important = ['Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto', 'Sun', 'Mercury', 'Venus', 'Mars']
            filtered = []
            for ing in self.transit_ingresses:
                if ing.get('planet') not in important:
                    continue
                if self.start_utc and self.end_utc:
                    try:
                        dt = datetime.strptime(ing.get('date', ''), '%Y-%m-%d')
                        if self.start_utc.date() <= dt.date() <= self.end_utc.date():
                            filtered.append(ing)
                    except:
                        continue
            return filtered

    def _filter_stations(self, type_: str) -> List[Dict]:
        """Фильтрует станции."""
        if type_ == 'DAY':
            today = self.start_utc.strftime('%Y-%m-%d') if self.start_utc else None
            important = ['Sun', 'Mercury', 'Venus', 'Mars', 'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']
            filtered = []
            for st in self.transit_stations:
                date = st.get('date')
                if date != today:
                    continue
                if st.get('planet') in important:
                    filtered.append(st)
            return filtered
        elif type_ == 'MONTH':
            # Оставляем только важные станции в течение месяца
            important = ['Sun', 'Mercury', 'Venus', 'Mars', 'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']
            filtered = []
            for st in self.transit_stations:
                if st.get('planet') not in important:
                    continue
                if self.start_utc and self.end_utc:
                    try:
                        dt = datetime.strptime(st.get('date', ''), '%Y-%m-%d')
                        if self.start_utc.date() <= dt.date() <= self.end_utc.date():
                            filtered.append(st)
                    except:
                        continue
            return filtered
        else:  # YEAR
            # Оставляем все станции, кроме Moon
            filtered = []
            for st in self.transit_stations:
                if st.get('planet') == 'Moon':
                    continue
                if self.start_utc and self.end_utc:
                    try:
                        dt = datetime.strptime(st.get('date', ''), '%Y-%m-%d')
                        if self.start_utc.date() <= dt.date() <= self.end_utc.date():
                            filtered.append(st)
                    except:
                        continue
            return filtered

    def _build_themes_from_aspects(self, aspects: List[Dict], max_themes: int) -> List[Dict]:
        """Из перечня аспектов строит темы (агрегирует по темам)."""
        theme_groups = defaultdict(list)
        for a in aspects:
            for theme in a.get('themes', []):
                if theme:
                    theme_groups[theme].append(a)

        # Сортируем группы по среднему score
        theme_list = []
        for theme, asp_list in theme_groups.items():
            avg_score = sum(a.get('score', 0) for a in asp_list) / len(asp_list) if asp_list else 0
            avg_conf = sum(a.get('confidence', 0) for a in asp_list) / len(asp_list) if asp_list else 0
            evidence = []
            for a in asp_list[:3]:
                evidence.append(f"{self._get_planet_name(a['transit_planet'])} {self.ASPECT_NAMES_RU.get(a['aspect'], a['aspect'])} {self._get_planet_name(a['natal_planet'])}")
            theme_list.append({
                'theme': theme,
                'avg_score': avg_score,
                'avg_conf': avg_conf,
                'evidence': evidence,
                'count': len(asp_list)
            })
        theme_list.sort(key=lambda x: (-x['avg_score'], -x['avg_conf']))
        return theme_list[:max_themes]

    def _aggregate_periods(self, aspects: List[Dict], type_: str) -> List[Dict]:
        """
        Агрегирует аспекты в периоды (для MONTH и YEAR).
        Группирует по связанным темам и датам.
        """
        if not aspects:
            return []

        # Сортируем по дате
        def get_date(asp):
            d = asp.get('exact_date')
            return d if d else '1970-01-01'
        aspects_sorted = sorted(aspects, key=get_date)

        # Группируем по темам (основная тема из первых в списке)
        # Для простоты группируем по первой теме
        periods = []
        used = set()
        i = 0
        while i < len(aspects_sorted):
            asp = aspects_sorted[i]
            themes = asp.get('themes', [])
            if not themes:
                i += 1
                continue
            main_theme = themes[0]
            # Собираем все аспекты с этой темой в пределах 7 дней (для MONTH) или 30 дней (для YEAR)
            cluster = [asp]
            j = i + 1
            while j < len(aspects_sorted):
                if main_theme in aspects_sorted[j].get('themes', []):
                    # Проверяем разницу дат
                    d1 = asp.get('exact_date')
                    d2 = aspects_sorted[j].get('exact_date')
                    if d1 and d2:
                        try:
                            dt1 = datetime.strptime(d1, '%Y-%m-%d')
                            dt2 = datetime.strptime(d2, '%Y-%m-%d')
                            if (dt2 - dt1).days <= 7 if type_ == 'MONTH' else 30:
                                cluster.append(aspects_sorted[j])
                                j += 1
                                continue
                        except:
                            pass
                j += 1
            # Сохраняем кластер
            if cluster:
                start = min(a.get('exact_date') for a in cluster if a.get('exact_date'))
                end = max(a.get('exact_date') for a in cluster if a.get('exact_date'))
                avg_score = sum(a.get('score', 0) for a in cluster) / len(cluster)
                avg_conf = sum(a.get('confidence', 0) for a in cluster) / len(cluster)
                evidence = []
                for a in cluster[:3]:
                    evidence.append(f"{self._get_planet_name(a['transit_planet'])} {self.ASPECT_NAMES_RU.get(a['aspect'], a['aspect'])} {self._get_planet_name(a['natal_planet'])}")
                periods.append({
                    'start': start,
                    'end': end,
                    'theme': main_theme,
                    'intensity': avg_score,
                    'confidence': avg_conf,
                    'evidence': evidence,
                    'count': len(cluster)
                })
                # Перемещаем i на следующий неиспользованный
                i = j
                # Отмечаем все использованные аспекты
                for a in cluster:
                    used.add(id(a))
            else:
                i += 1

        # Сортируем по интенсивности
        periods.sort(key=lambda x: -x['intensity'])
        return periods

    # ---------- ОСНОВНЫЕ МЕТОДЫ ПОСТРОЕНИЯ КОНТЕКСТА ----------
    def build_day_context(self) -> str:
        """Формирует контекст для дневного прогноза."""
        lines = []
        lines.append("## КОНТЕКСТ ПРОГНОЗА\n")
        lines.append(f"Тип прогноза: ДЕНЬ")
        if self.start_utc:
            date_str = self.start_utc.strftime('%d.%m.%Y')
            lines.append(f"Дата: {date_str}")
            lines.append(f"Период: {self.start_utc.strftime('%H:%M')}–{self.end_utc.strftime('%H:%M')} UTC" if self.end_utc else f"Дата: {date_str}")

        # Натальная основа
        lines.append("\n## НАТАЛЬНАЯ ОСНОВА\n")
        lines.append(f"Дата рождения: {self.birth_date}")
        lines.append(f"Время рождения: {self.birth_time}")
        lines.append(f"Место рождения: {self.birth_place}")
        asc = self.angles.get('ASC', 0.0)
        mc = self.angles.get('MC', 0.0)
        lines.append(f"ASC: {asc:.2f}°")
        lines.append(f"MC: {mc:.2f}°")

        # Натальные планеты (без скоростей)
        lines.append("\nНатальные положения:")
        for p in self.planets:
            lines.append(self._format_planet(p))

        # Ключевые натальные аспекты
        natal_aspects = self._filter_natal_aspects(limit=10)
        if natal_aspects:
            lines.append("\nКлючевые натальные аспекты:")
            for a in natal_aspects:
                lines.append(self._format_natal_aspect(a))

        # Транзиты
        filtered_transits = self._filter_transit_aspects('DAY')
        if filtered_transits:
            lines.append("\n## КЛЮЧЕВЫЕ ТРАНЗИТЫ ДНЯ\n")
            for i, a in enumerate(filtered_transits, 1):
                lines.append(f"{i}. {self._format_transit_aspect(a)}")

        # Транзиты к углам
        angle_aspects = self._filter_transit_angle_aspects('DAY')
        if angle_aspects:
            lines.append("\n## ТРАНЗИТЫ К УГЛАМ\n")
            for a in angle_aspects:
                t_planet = self._get_planet_name(a['transit_planet'])
                angle = a['angle']
                aspect = self.ASPECT_NAMES_RU.get(a['aspect'], a['aspect'])
                orb = a['orb']
                score = a['score']
                lines.append(f"{t_planet} {aspect} {angle}, орб {orb:.2f}°, score {score:.2f}")

        # Ингрессии
        ingresses = self._filter_ingresses('DAY')
        if ingresses:
            lines.append("\n## ЗНАЧИМЫЕ ИНГРЕССИИ\n")
            for ing in ingresses:
                planet = self._get_planet_name(ing['planet'])
                if ing['type'] == 'sign':
                    to_sign = self._get_sign_name(ing['to'])
                    lines.append(f"{planet} переходит в знак {to_sign}")
                else:
                    lines.append(f"{planet} переходит в дом {ing['to']}")

        # Станции
        stations = self._filter_stations('DAY')
        if stations:
            lines.append("\n## ЗНАЧИМЫЕ СТАНЦИИ\n")
            for st in stations:
                planet = self._get_planet_name(st['planet'])
                sign = self._get_sign_name(st.get('sign', ''))
                lines.append(f"{planet} stationary в {sign}")

        # Темы дня (из отфильтрованных транзитов)
        themes = self._build_themes_from_aspects(filtered_transits, max_themes=6)
        if themes:
            lines.append("\n## КЛЮЧЕВЫЕ ТЕМЫ ДНЯ\n")
            for theme in themes:
                lines.append(f"{theme['theme']}: интенсивность {theme['avg_score']:.1f}, confidence {theme['avg_conf']:.2f}")
                if theme['evidence']:
                    lines.append(f"  основание: {', '.join(theme['evidence'])}")

        return "\n".join(lines)

    def build_month_context(self) -> str:
        """Формирует контекст для месячного прогноза."""
        lines = []
        lines.append("## КОНТЕКСТ ПРОГНОЗА\n")
        lines.append("Тип прогноза: МЕСЯЦ")
        if self.start_utc and self.end_utc:
            start_str = self.start_utc.strftime('%d.%m.%Y')
            end_str = self.end_utc.strftime('%d.%m.%Y')
            lines.append(f"Период: {start_str} – {end_str}")

        # Натальная основа (та же, что и для DAY)
        lines.append("\n## НАТАЛЬНАЯ ОСНОВА\n")
        lines.append(f"Дата рождения: {self.birth_date}")
        lines.append(f"Время рождения: {self.birth_time}")
        lines.append(f"Место рождения: {self.birth_place}")
        asc = self.angles.get('ASC', 0.0)
        mc = self.angles.get('MC', 0.0)
        lines.append(f"ASC: {asc:.2f}°")
        lines.append(f"MC: {mc:.2f}°")

        lines.append("\nНатальные положения:")
        for p in self.planets:
            lines.append(self._format_planet(p))

        natal_aspects = self._filter_natal_aspects(limit=12)
        if natal_aspects:
            lines.append("\nКлючевые натальные аспекты:")
            for a in natal_aspects:
                lines.append(self._format_natal_aspect(a))

        # Транзиты месяца (фильтр по периоду с порогами MONTH)
        filtered_transits = self._filter_transit_aspects('MONTH')
        if filtered_transits:
            lines.append("\n## ГЛАВНЫЕ ТРАНЗИТЫ МЕСЯЦА\n")
            for a in filtered_transits:
                lines.append(self._format_transit_aspect(a))

        # Транзиты к углам
        angle_aspects = self._filter_transit_angle_aspects('MONTH')
        if angle_aspects:
            lines.append("\n## ТРАНЗИТЫ К УГЛАМ\n")
            for a in angle_aspects:
                t_planet = self._get_planet_name(a['transit_planet'])
                angle = a['angle']
                aspect = self.ASPECT_NAMES_RU.get(a['aspect'], a['aspect'])
                orb = a['orb']
                score = a['score']
                lines.append(f"{t_planet} {aspect} {angle}, орб {orb:.2f}°, score {score:.2f}")

        # Агрегация периодов
        periods = self._aggregate_periods(filtered_transits, 'MONTH')
        if periods:
            lines.append("\n## КЛЮЧЕВЫЕ ПЕРИОДЫ\n")
            for p in periods:
                lines.append(f"{p['start']} – {p['end']}: {p['theme']}, интенсивность {p['intensity']:.1f}, confidence {p['confidence']:.2f}")
                if p['evidence']:
                    lines.append(f"  основания: {', '.join(p['evidence'])}")

        # Ингрессии месяца
        ingresses = self._filter_ingresses('MONTH')
        if ingresses:
            lines.append("\n## ЗНАЧИМЫЕ ИНГРЕССИИ\n")
            for ing in ingresses:
                planet = self._get_planet_name(ing['planet'])
                if ing['type'] == 'sign':
                    to_sign = self._get_sign_name(ing['to'])
                    lines.append(f"{ing['date']} — {planet} переходит в знак {to_sign}")
                else:
                    lines.append(f"{ing['date']} — {planet} переходит в дом {ing['to']}")

        # Станции месяца
        stations = self._filter_stations('MONTH')
        if stations:
            lines.append("\n## ЗНАЧИМЫЕ СТАНЦИИ\n")
            for st in stations:
                planet = self._get_planet_name(st['planet'])
                sign = self._get_sign_name(st.get('sign', ''))
                lines.append(f"{st.get('date', '')} — {planet} stationary в {sign}")

        # Темы месяца (из отфильтрованных транзитов)
        themes = self._build_themes_from_aspects(filtered_transits, max_themes=8)
        if themes:
            lines.append("\n## ОСНОВНЫЕ ТЕМЫ МЕСЯЦА\n")
            for i, theme in enumerate(themes, 1):
                lines.append(f"{i}. {theme['theme']}")
                if theme['evidence']:
                    lines.append(f"   основания: {', '.join(theme['evidence'])}")

        return "\n".join(lines)

    def build_year_context(self) -> str:
        """Формирует контекст для годового прогноза."""
        lines = []
        lines.append("## КОНТЕКСТ ПРОГНОЗА\n")
        lines.append("Тип прогноза: ГОД")
        if self.start_utc and self.end_utc:
            start_str = self.start_utc.strftime('%d.%m.%Y')
            end_str = self.end_utc.strftime('%d.%m.%Y')
            lines.append(f"Период: {start_str} – {end_str}")

        # Натальная основа
        lines.append("\n## НАТАЛЬНАЯ ОСНОВА\n")
        lines.append(f"Дата рождения: {self.birth_date}")
        lines.append(f"Время рождения: {self.birth_time}")
        lines.append(f"Место рождения: {self.birth_place}")
        asc = self.angles.get('ASC', 0.0)
        mc = self.angles.get('MC', 0.0)
        lines.append(f"ASC: {asc:.2f}°")
        lines.append(f"MC: {mc:.2f}°")

        lines.append("\nНатальные положения:")
        for p in self.planets:
            lines.append(self._format_planet(p))

        natal_aspects = self._filter_natal_aspects(limit=15)
        if natal_aspects:
            lines.append("\nКлючевые натальные аспекты:")
            for a in natal_aspects:
                lines.append(self._format_natal_aspect(a))

        # Транзиты года (фильтр с порогами YEAR)
        filtered_transits = self._filter_transit_aspects('YEAR')
        # Группируем по планетам-транзиторам (медленные)
        if filtered_transits:
            lines.append("\n## ГЛАВНЫЕ ДОЛГОСРОЧНЫЕ ТРАНЗИТЫ\n")
            # Группируем по транзитной планете
            groups = defaultdict(list)
            for a in filtered_transits:
                groups[a['transit_planet']].append(a)
            for planet, aspects in groups.items():
                if planet not in ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars']:
                    lines.append(f"\n### {self._get_planet_name(planet)}\n")
                    for a in aspects:
                        lines.append(self._format_transit_aspect(a))
        else:
            lines.append("\n## ГЛАВНЫЕ ТРАНЗИТЫ\n")
            for a in filtered_transits:
                lines.append(self._format_transit_aspect(a))

        # Агрегация периодов (для YEAR группируем шире)
        periods = self._aggregate_periods(filtered_transits, 'YEAR')
        if periods:
            lines.append("\n## КЛЮЧЕВЫЕ ПЕРИОДЫ ГОДА\n")
            for p in periods:
                lines.append(f"{p['start']} – {p['end']}: {p['theme']}, интенсивность {p['intensity']:.1f}, confidence {p['confidence']:.2f}")
                if p['evidence']:
                    lines.append(f"  основания: {', '.join(p['evidence'])}")

        # Ингрессии (только важные)
        ingresses = self._filter_ingresses('YEAR')
        if ingresses:
            lines.append("\n## ЗНАЧИМЫЕ ИНГРЕССИИ\n")
            for ing in ingresses:
                planet = self._get_planet_name(ing['planet'])
                if ing['type'] == 'sign':
                    to_sign = self._get_sign_name(ing['to'])
                    lines.append(f"{ing['date']} — {planet} переходит в знак {to_sign}")
                else:
                    lines.append(f"{ing['date']} — {planet} переходит в дом {ing['to']}")

        # Станции года
        stations = self._filter_stations('YEAR')
        if stations:
            lines.append("\n## ЗНАЧИМЫЕ СТАНЦИИ\n")
            for st in stations:
                planet = self._get_planet_name(st['planet'])
                sign = self._get_sign_name(st.get('sign', ''))
                lines.append(f"{st.get('date', '')} — {planet} stationary в {sign}")

        # Темы года
        themes = self._build_themes_from_aspects(filtered_transits, max_themes=10)
        if themes:
            lines.append("\n## ОСНОВНЫЕ ТЕМЫ ГОДА\n")
            for i, theme in enumerate(themes, 1):
                lines.append(f"{i}. {theme['theme']}")
                if theme['evidence']:
                    lines.append(f"   основания: {', '.join(theme['evidence'])}")

        return "\n".join(lines)