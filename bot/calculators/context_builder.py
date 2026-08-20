# bot/calculators/context_builder.py
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


class AstrologyContextBuilder:
    """
    Класс для построения текстового контекста для трёх типов прогнозов: ДЕНЬ, МЕСЯЦ, ГОД.
    Возвращает структурированный текст для вставки в промпт LLM.
    """

    # Веса транзитных планет (объектов)
    TRANSIT_PLANET_WEIGHT = {
        'Pluto': 10, 'Neptune': 9, 'Uranus': 9, 'Saturn': 8,
        'Jupiter': 7, 'Mars': 5, 'Sun': 4, 'Venus': 3,
        'Mercury': 3, 'Moon': 1
    }

    # Веса натальных точек
    NATAL_POINT_WEIGHT = {
        'Sun': 10, 'Moon': 10, 'ASC': 10, 'MC': 10,
        'Venus': 9, 'Mars': 9, 'Mercury': 8, 'Jupiter': 8,
        'Saturn': 8, 'Uranus': 7, 'Neptune': 7, 'Pluto': 7,
        'NorthNode': 6, 'SouthNode': 5, 'Chiron': 4, 'Lilith': 2,
        'DSC': 10, 'IC': 10
    }

    # Коэффициенты аспектов
    ASPECT_WEIGHT = {
        'conjunction': 1.00,
        'opposition': 0.95,
        'square': 0.90,
        'trine': 0.80,
        'sextile': 0.65
    }

    # Коэффициенты орба
    ORB_WEIGHT = {
        0.0: 1.00,
        0.5: 0.95,
        1.0: 0.90,
        1.5: 0.80,
        2.0: 0.60,
        3.0: 0.35,
        4.0: 0.00
    }

    # Углы и бонус к ним
    ANGLE_BONUS = 2
    APPLYING_BONUS = 1.0

    # Длительность транзитов (условные веса для MONTH и YEAR)
    DURATION_WEIGHT = {
        'Moon': 0.1, 'Sun': 0.2, 'Mercury': 0.3, 'Venus': 0.3,
        'Mars': 0.5, 'Jupiter': 0.8, 'Saturn': 1.0,
        'Uranus': 1.0, 'Neptune': 1.0, 'Pluto': 1.0
    }

    # Лимиты
    DAY_LIMIT = 10
    MONTH_LIMIT = 8
    YEAR_LIMIT = 10

    # Локализация названий планет и знаков
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
        'sextile': 'секстиль'
    }

    def __init__(self, user_data: Dict, natal_data: Dict, transit_data: Dict, lang: str = 'ru'):
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
        self.period = transit_data.get('period', 'today')
        self.start_utc = transit_data.get('start_utc')
        self.end_utc = transit_data.get('end_utc')

    # ----- ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ -----

    def _get_orb_weight(self, orb: float) -> float:
        if orb <= 0.5:
            return 1.00
        elif orb <= 1.0:
            return 0.95
        elif orb <= 1.5:
            return 0.90
        elif orb <= 2.0:
            return 0.80
        elif orb <= 3.0:
            return 0.60
        elif orb <= 4.0:
            return 0.35
        else:
            return 0.0

    def _calculate_significance(self, aspect: Dict, transit_planet: str, natal_point: str,
                                is_angle: bool = False) -> float:
        obj_w = self.TRANSIT_PLANET_WEIGHT.get(transit_planet, 1)
        natal_w = self.NATAL_POINT_WEIGHT.get(natal_point, 1)
        aspect_w = self.ASPECT_WEIGHT.get(aspect.get('aspect', ''), 0.5)
        orb = aspect.get('orb', 10.0)
        orb_w = self._get_orb_weight(orb)
        base = obj_w * natal_w * aspect_w * orb_w
        angle_bonus = self.ANGLE_BONUS if is_angle else 0
        phase = aspect.get('phase', '')
        applying_bonus = self.APPLYING_BONUS if phase == 'applying' else 0
        return base + angle_bonus + applying_bonus

    def _validate_aspect(self, aspect: Dict) -> bool:
        required = ['transit_planet', 'aspect', 'orb', 'phase', 'exact_date']
        for field in required:
            if field not in aspect or aspect[field] is None:
                return False
        return True

    def _is_date_in_range(self, date_str: str, start: Optional[datetime], end: Optional[datetime]) -> bool:
        if not date_str or not start or not end:
            return False
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d').date()
            return start.date() <= dt <= end.date()
        except:
            return False

    def _is_same_day(self, date_str: str, target_date: datetime) -> bool:
        if not date_str:
            return False
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d').date()
            return dt == target_date.date()
        except:
            return False

    def _format_planet(self, name: str) -> str:
        return self.PLANET_NAMES_RU.get(name, name)

    def _format_aspect(self, name: str) -> str:
        return self.ASPECT_NAMES_RU.get(name, name)

    # ----- DAY_FILTER -----

    def _day_filter(self) -> Dict[str, Any]:
        target_date = self.start_utc
        all_aspects = self.transit_aspects + self.transit_angle_aspects
        day_events = []
        for asp in all_aspects:
            if not self._is_same_day(asp.get('exact_date'), target_date):
                continue
            if not self._validate_aspect(asp):
                continue
            orb = asp.get('orb', 10.0)
            transit_planet = asp.get('transit_planet', '')
            if transit_planet in ['Moon', 'Sun', 'Mercury', 'Venus', 'Mars'] and orb > 3.0:
                continue
            if transit_planet in ['Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto'] and orb > 4.0:
                continue
            natal_point = asp.get('natal_planet') or asp.get('angle')
            if not natal_point:
                continue
            is_angle = 'angle' in asp
            significance = self._calculate_significance(asp, transit_planet, natal_point, is_angle)
            asp['significance'] = significance
            day_events.append(asp)

        day_events.sort(key=lambda x: x['significance'], reverse=True)
        top_events = day_events[:self.DAY_LIMIT]

        # Группировка луны
        lunar_events = [e for e in top_events if e.get('transit_planet') == 'Moon']
        if len(lunar_events) > 2:
            top_events = [e for e in top_events if e.get('transit_planet') != 'Moon']
            top_events.extend(lunar_events[:2])
            top_events.sort(key=lambda x: x['significance'], reverse=True)

        result = {
            "top_events": [],
            "angle_events": [],
            "themes": []
        }
        for e in top_events:
            event = {
                "transit_planet": e.get('transit_planet'),
                "natal_point": e.get('natal_planet') or e.get('angle'),
                "aspect": e.get('aspect'),
                "orb": e.get('orb'),
                "phase": e.get('phase'),
                "significance": e.get('significance'),
                "house": e.get('transit_house'),
                "is_angle": 'angle' in e,
                "exact_date": e.get('exact_date')
            }
            if event['is_angle']:
                result["angle_events"].append(event)
            else:
                result["top_events"].append(event)

        # Темы
        themes = []
        for e in top_events[:5]:
            theme_name = f"{e.get('transit_planet')}_{e.get('natal_planet') or e.get('angle')}"
            theme = {
                "theme": theme_name,
                "significance": e.get('significance'),
                "primary_driver": f"{self._format_planet(e.get('transit_planet'))} {self._format_aspect(e.get('aspect'))} {self._format_planet(e.get('natal_planet') or e.get('angle'))}",
                "supporting_drivers": []
            }
            if not any(t['theme'] == theme['theme'] for t in themes):
                themes.append(theme)
        result["themes"] = themes[:5]
        return result

    # ----- MONTH_FILTER -----

    def _month_filter(self) -> Dict[str, Any]:
        start_date = self.start_utc
        end_date = self.end_utc
        if not start_date or not end_date:
            return {}

        month_aspects = []
        for asp in self.transit_aspects + self.transit_angle_aspects:
            if not self._is_date_in_range(asp.get('exact_date'), start_date, end_date):
                continue
            if not self._validate_aspect(asp):
                continue
            orb = asp.get('orb', 10.0)
            transit_planet = asp.get('transit_planet', '')
            if transit_planet in ['Pluto', 'Neptune', 'Uranus', 'Saturn'] and orb > 4.0:
                continue
            if transit_planet in ['Jupiter'] and orb > 5.0:
                continue
            if transit_planet in ['Moon', 'Sun', 'Mercury', 'Venus', 'Mars'] and orb > 5.0:
                continue
            significance = self._calculate_significance(asp, transit_planet,
                                                        asp.get('natal_planet') or asp.get('angle', ''),
                                                        'angle' in asp)
            duration_w = self.DURATION_WEIGHT.get(transit_planet, 0.5)
            significance = significance * (1 + 0.5 * duration_w)
            asp['significance'] = significance
            month_aspects.append(asp)

        grouped = defaultdict(list)
        for asp in month_aspects:
            key = (asp.get('transit_planet'), asp.get('natal_planet') or asp.get('angle'))
            grouped[key].append(asp)

        processes = []
        for (t_planet, n_point), aspects in grouped.items():
            if not aspects:
                continue
            aspects.sort(key=lambda x: x.get('exact_date'))
            first_date = aspects[0].get('exact_date')
            last_date = aspects[-1].get('exact_date')
            peak_asp = max(aspects, key=lambda x: x.get('significance', 0))
            phase = peak_asp.get('phase', '')
            significance = peak_asp.get('significance', 0)
            if first_date and last_date:
                try:
                    delta = (datetime.strptime(last_date, '%Y-%m-%d') - datetime.strptime(first_date, '%Y-%m-%d')).days
                    if delta > 7:
                        significance *= (1 + 0.2 * min(delta / 30, 1.0))
                except:
                    pass
            processes.append({
                "transit_planet": t_planet,
                "natal_point": n_point,
                "aspect": peak_asp.get('aspect'),
                "start_date": first_date,
                "peak_date": peak_asp.get('exact_date'),
                "end_date": last_date,
                "phase": phase,
                "significance": significance,
                "aspects": aspects
            })

        processes.sort(key=lambda x: x['significance'], reverse=True)
        main_processes = processes[:self.MONTH_LIMIT]

        key_dates = {}
        for p in main_processes:
            if p['peak_date']:
                if p['peak_date'] not in key_dates:
                    key_dates[p['peak_date']] = []
                key_dates[p['peak_date']].append(f"{self._format_planet(p['transit_planet'])} {self._format_aspect(p['aspect'])} {self._format_planet(p['natal_point'])}")

        important_ingresses = []
        for ing in self.transit_ingresses:
            if not self._is_date_in_range(ing.get('date'), start_date, end_date):
                continue
            planet = ing.get('planet')
            if planet in ['Pluto', 'Neptune', 'Uranus', 'Saturn', 'Jupiter']:
                important_ingresses.append(ing)
            elif planet == 'Mars' and ing.get('type') == 'house' and int(ing.get('to', 0)) in [1, 4, 5, 7, 8, 10]:
                important_ingresses.append(ing)

        themes = []
        for p in main_processes[:5]:
            themes.append({
                "theme": f"{self._format_planet(p['transit_planet'])} {self._format_aspect(p['aspect'])} {self._format_planet(p['natal_point'])}",
                "significance": p['significance'],
                "primary_driver": f"{self._format_planet(p['transit_planet'])} {self._format_aspect(p['aspect'])} {self._format_planet(p['natal_point'])}",
                "supporting_drivers": []
            })

        return {
            "main_processes": main_processes,
            "key_dates": key_dates,
            "important_ingresses": important_ingresses,
            "themes": themes[:7]
        }

    # ----- YEAR_FILTER -----

    def _year_filter(self) -> Dict[str, Any]:
        start_date = self.start_utc
        end_date = self.end_utc
        if not start_date or not end_date:
            return {}

        year_aspects = []
        for asp in self.transit_aspects:
            if not self._is_date_in_range(asp.get('exact_date'), start_date, end_date):
                continue
            transit_planet = asp.get('transit_planet', '')
            if transit_planet not in ['Pluto', 'Neptune', 'Uranus', 'Saturn', 'Jupiter']:
                continue
            if not self._validate_aspect(asp):
                continue
            orb = asp.get('orb', 10.0)
            if orb > 5.0:
                continue
            significance = self._calculate_significance(asp, transit_planet,
                                                        asp.get('natal_planet') or asp.get('angle', ''),
                                                        'angle' in asp)
            duration_w = self.DURATION_WEIGHT.get(transit_planet, 0.5)
            significance = significance * (1 + duration_w)
            asp['significance'] = significance
            year_aspects.append(asp)

        grouped = defaultdict(list)
        for asp in year_aspects:
            key = (asp.get('transit_planet'), asp.get('natal_planet') or asp.get('angle'))
            grouped[key].append(asp)

        long_term_processes = []
        for (t_planet, n_point), aspects in grouped.items():
            if not aspects:
                continue
            aspects.sort(key=lambda x: x.get('exact_date'))
            first_date = aspects[0].get('exact_date')
            last_date = aspects[-1].get('exact_date')
            peak_asp = max(aspects, key=lambda x: x.get('significance', 0))
            significance = peak_asp.get('significance', 0)
            duration_months = 0
            if first_date and last_date:
                try:
                    delta = (datetime.strptime(last_date, '%Y-%m-%d') - datetime.strptime(first_date, '%Y-%m-%d')).days
                    duration_months = delta / 30
                    significance *= (1 + 0.3 * min(duration_months / 6, 1.0))
                except:
                    pass
            long_term_processes.append({
                "transit_planet": t_planet,
                "natal_point": n_point,
                "aspect": peak_asp.get('aspect'),
                "start_date": first_date,
                "peak_period": peak_asp.get('exact_date'),
                "end_date": last_date,
                "duration_months": round(duration_months, 1),
                "significance": significance,
                "aspects": aspects
            })

        long_term_processes.sort(key=lambda x: x['significance'], reverse=True)
        main_processes = long_term_processes[:self.YEAR_LIMIT]

        periods = []
        for p in main_processes:
            periods.append({
                "start": p['start_date'],
                "end": p['end_date'],
                "theme": f"{self._format_planet(p['transit_planet'])} {self._format_aspect(p['aspect'])} {self._format_planet(p['natal_point'])}",
                "drivers": [p['transit_planet']],
                "significance": p['significance']
            })

        major_ingresses = []
        for ing in self.transit_ingresses:
            if not self._is_date_in_range(ing.get('date'), start_date, end_date):
                continue
            if ing.get('planet') in ['Pluto', 'Neptune', 'Uranus', 'Saturn', 'Jupiter']:
                major_ingresses.append(ing)

        themes = []
        for p in main_processes[:8]:
            themes.append({
                "theme": f"{self._format_planet(p['transit_planet'])} {self._format_aspect(p['aspect'])} {self._format_planet(p['natal_point'])}",
                "significance": p['significance'],
                "primary_driver": f"{self._format_planet(p['transit_planet'])} {self._format_aspect(p['aspect'])} {self._format_planet(p['natal_point'])}",
                "supporting_drivers": []
            })

        monthly_summary = []
        for month in range(1, 13):
            month_start = start_date.replace(month=month, day=1)
            if month_start > end_date:
                break
            month_themes = []
            for p in main_processes:
                if p['start_date'] and p['end_date']:
                    try:
                        p_start = datetime.strptime(p['start_date'], '%Y-%m-%d')
                        p_end = datetime.strptime(p['end_date'], '%Y-%m-%d')
                        if p_start <= month_start + timedelta(days=30) and p_end >= month_start:
                            month_themes.append(f"{self._format_planet(p['transit_planet'])} {self._format_aspect(p['aspect'])} {self._format_planet(p['natal_point'])}")
                    except:
                        pass
            monthly_summary.append({
                "month": month_start.strftime('%B'),
                "top_themes": month_themes[:3]
            })

        return {
            "long_term_processes": main_processes,
            "major_periods": periods,
            "major_ingresses": major_ingresses,
            "themes": themes[:8],
            "monthly_summary": monthly_summary
        }

    # ----- ФОРМАТТЕРЫ ДЛЯ ТЕКСТОВОГО ВЫВОДА -----

    def _format_day_result(self, data: Dict) -> str:
        lines = []
        lines.append("## КОНТЕКСТ ПРОГНОЗА")
        lines.append(f"Тип: ДЕНЬ")
        if self.start_utc:
            lines.append(f"Дата: {self.start_utc.strftime('%d.%m.%Y')}")
        lines.append("")

        if data.get("top_events"):
            lines.append("## КЛЮЧЕВЫЕ СОБЫТИЯ")
            for i, e in enumerate(data["top_events"], 1):
                planet = self._format_planet(e['transit_planet'])
                natal = self._format_planet(e['natal_point'])
                aspect = self._format_aspect(e['aspect'])
                orb = e['orb']
                phase = e['phase']
                sig = e['significance']
                lines.append(f"{i}. {planet} {aspect} {natal}, орб {orb:.2f}°, фаза {phase}, значимость {sig:.1f}")
            lines.append("")

        if data.get("angle_events"):
            lines.append("## ТРАНЗИТЫ К УГЛАМ")
            for e in data["angle_events"]:
                planet = self._format_planet(e['transit_planet'])
                angle = e['natal_point']
                aspect = self._format_aspect(e['aspect'])
                orb = e['orb']
                sig = e['significance']
                lines.append(f"- {planet} {aspect} {angle}, орб {orb:.2f}°, значимость {sig:.1f}")
            lines.append("")

        if data.get("themes"):
            lines.append("## ТЕМЫ")
            for i, theme in enumerate(data["themes"], 1):
                lines.append(f"{i}. {theme['theme']}: {theme['primary_driver']} (значимость {theme['significance']:.1f})")
            lines.append("")

        return "\n".join(lines)

    def _format_month_result(self, data: Dict) -> str:
        lines = []
        lines.append("## КОНТЕКСТ ПРОГНОЗА")
        lines.append("Тип: МЕСЯЦ")
        if self.start_utc and self.end_utc:
            lines.append(f"Период: {self.start_utc.strftime('%d.%m.%Y')} – {self.end_utc.strftime('%d.%m.%Y')}")
        lines.append("")

        if data.get("main_processes"):
            lines.append("## ГЛАВНЫЕ ПРОЦЕССЫ МЕСЯЦА")
            for p in data["main_processes"]:
                planet = self._format_planet(p['transit_planet'])
                natal = self._format_planet(p['natal_point'])
                aspect = self._format_aspect(p['aspect'])
                start = p['start_date']
                peak = p['peak_date']
                end = p['end_date']
                sig = p['significance']
                lines.append(f"{planet} {aspect} {natal}")
                lines.append(f"  Начало: {start}, пик: {peak}, окончание: {end}, значимость: {sig:.1f}")
            lines.append("")

        if data.get("key_dates"):
            lines.append("## КЛЮЧЕВЫЕ ДАТЫ")
            for date, events in sorted(data["key_dates"].items()):
                lines.append(f"{date}: {', '.join(events)}")
            lines.append("")

        if data.get("important_ingresses"):
            lines.append("## ЗНАЧИМЫЕ ИНГРЕССИИ")
            for ing in data["important_ingresses"]:
                planet = self._format_planet(ing.get('planet', ''))
                if ing.get('type') == 'sign':
                    lines.append(f"{ing.get('date')} — {planet} входит в знак {ing.get('to')}")
                else:
                    lines.append(f"{ing.get('date')} — {planet} входит в дом {ing.get('to')}")
            lines.append("")

        if data.get("themes"):
            lines.append("## ОСНОВНЫЕ ТЕМЫ МЕСЯЦА")
            for i, theme in enumerate(data["themes"], 1):
                lines.append(f"{i}. {theme['theme']} (значимость {theme['significance']:.1f})")
            lines.append("")

        return "\n".join(lines)

    def _format_year_result(self, data: Dict) -> str:
        lines = []
        lines.append("## КОНТЕКСТ ПРОГНОЗА")
        lines.append("Тип: ГОД")
        if self.start_utc:
            lines.append(f"Год: {self.start_utc.year}")
        lines.append("")

        if data.get("long_term_processes"):
            lines.append("## ГЛАВНЫЕ ДОЛГОСРОЧНЫЕ ПРОЦЕССЫ")
            for p in data["long_term_processes"]:
                planet = self._format_planet(p['transit_planet'])
                natal = self._format_planet(p['natal_point'])
                aspect = self._format_aspect(p['aspect'])
                start = p['start_date']
                peak = p['peak_period']
                end = p['end_date']
                duration = p['duration_months']
                sig = p['significance']
                lines.append(f"{planet} {aspect} {natal}")
                lines.append(f"  Начало: {start}, пик: {peak}, окончание: {end}, длительность: {duration} мес., значимость: {sig:.1f}")
            lines.append("")

        if data.get("major_periods"):
            lines.append("## КЛЮЧЕВЫЕ ПЕРИОДЫ ГОДА")
            for p in data["major_periods"]:
                lines.append(f"{p['start']} – {p['end']}: {p['theme']} (значимость {p['significance']:.1f})")
            lines.append("")

        if data.get("major_ingresses"):
            lines.append("## ЗНАЧИМЫЕ ИНГРЕССИИ")
            for ing in data["major_ingresses"]:
                planet = self._format_planet(ing.get('planet', ''))
                if ing.get('type') == 'sign':
                    lines.append(f"{ing.get('date')} — {planet} входит в знак {ing.get('to')}")
                else:
                    lines.append(f"{ing.get('date')} — {planet} входит в дом {ing.get('to')}")
            lines.append("")

        if data.get("themes"):
            lines.append("## ОСНОВНЫЕ ТЕМЫ ГОДА")
            for i, theme in enumerate(data["themes"], 1):
                lines.append(f"{i}. {theme['theme']} (значимость {theme['significance']:.1f})")
            lines.append("")

        if data.get("monthly_summary"):
            lines.append("## МЕСЯЧНАЯ АГРЕГАЦИЯ")
            for m in data["monthly_summary"]:
                if m['top_themes']:
                    lines.append(f"{m['month']}: {', '.join(m['top_themes'])}")
            lines.append("")

        return "\n".join(lines)

    # ----- ПУБЛИЧНЫЕ МЕТОДЫ (возвращают текст) -----

    def build_day_context(self) -> str:
        """Возвращает текстовый контекст для дневного прогноза."""
        data = self._day_filter()
        return self._format_day_result(data)

    def build_month_context(self) -> str:
        """Возвращает текстовый контекст для месячного прогноза."""
        data = self._month_filter()
        return self._format_month_result(data)

    def build_year_context(self) -> str:
        """Возвращает текстовый контекст для годового прогноза."""
        data = self._year_filter()
        return self._format_year_result(data)