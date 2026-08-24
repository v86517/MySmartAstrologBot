import logging
import zoneinfo
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple

from kerykeion import AstrologicalSubject, ChartDataFactory

from bot.utils.place_resolver import PlaceResolver

logger = logging.getLogger(__name__)


class CompatibilityCalculator:
    """
    Генерирует текстовый контекст для анализа совместимости двух людей.
    Использует штатный механизм Kerykeion для синастрии.
    """

    # ========== MAPPING ==========
    SIGN_MAP = {
        'Ari': 'Овен', 'Tau': 'Телец', 'Gem': 'Близнецы',
        'Can': 'Рак', 'Leo': 'Лев', 'Vir': 'Дева',
        'Lib': 'Весы', 'Sco': 'Скорпион', 'Sag': 'Стрелец',
        'Cap': 'Козерог', 'Aqu': 'Водолей', 'Pis': 'Рыбы'
    }

    PLANET_MAP = {
        'Sun': 'Солнце', 'Moon': 'Луна', 'Mercury': 'Меркурий',
        'Venus': 'Венера', 'Mars': 'Марс', 'Jupiter': 'Юпитер',
        'Saturn': 'Сатурн', 'Uranus': 'Уран', 'Neptune': 'Нептун',
        'Pluto': 'Плутон',
        'True_North_Lunar_Node': 'Северный узел',
        'True_South_Lunar_Node': 'Южный узел',
        'Chiron': 'Хирон',
        'True_Lilith': 'Лилит'
    }

    ASPECT_MAP = {
        'conjunction': 'соединение',
        'opposition': 'оппозиция',
        'trine': 'тригон',
        'square': 'квадрат',
        'sextile': 'секстиль'
    }

    PHASE_MAP = {
        'applying': 'сходящийся',
        'separating': 'расходящийся'
    }

    HOUSE_MAP = {
        'First_House': '1 дом',
        'Second_House': '2 дом',
        'Third_House': '3 дом',
        'Fourth_House': '4 дом',
        'Fifth_House': '5 дом',
        'Sixth_House': '6 дом',
        'Seventh_House': '7 дом',
        'Eighth_House': '8 дом',
        'Ninth_House': '9 дом',
        'Tenth_House': '10 дом',
        'Eleventh_House': '11 дом',
        'Twelfth_House': '12 дом'
    }

    # ========== ОРБЫ ==========
    SYNASTRY_ASPECT_ORBS = {
        'conjunction': 8.0,
        'opposition': 8.0,
        'trine': 7.0,
        'square': 7.0,
        'sextile': 5.0
    }

    EXTRA_ASPECT_ORBS = {
        'conjunction': 5.0,
        'opposition': 5.0,
        'trine': 5.0,
        'square': 5.0,
        'sextile': 5.0
    }

    LILITH_ASPECT_ORBS = {
        'conjunction': 3.0,
        'opposition': 3.0,
        'trine': 3.0,
        'square': 3.0,
        'sextile': 3.0
    }

    ALLOWED_ASPECTS = {'conjunction', 'opposition', 'trine', 'square', 'sextile'}
    MAIN_PLANETS = {'Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                    'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto'}
    EXTRA_OBJECTS = {'True_North_Lunar_Node', 'True_South_Lunar_Node',
                     'Chiron', 'True_Lilith', 'ASC', 'MC', 'DSC', 'IC'}

    def __init__(self, person_a_data: Dict[str, Any], person_b_data: Dict[str, Any],
                 lang: str = 'ru',
                 telegram_id: Optional[int] = None,
                 save_for_person_a: bool = False):
        self.person_a_data = person_a_data
        self.person_b_data = person_b_data
        self.lang = lang
        self.telegram_id = telegram_id
        self.save_for_person_a = save_for_person_a

        self._computed_coords_a = None
        self._computed_coords_b = None
        self._utc_dt_a = None
        self._utc_dt_b = None

        self.subject_a = self._create_subject(person_a_data, '1', save_to_db=save_for_person_a)
        if self.subject_a is None:
            raise ValueError("Не удалось создать субъект для человека A")
        self.subject_b = self._create_subject(person_b_data, '2', save_to_db=False)
        if self.subject_b is None:
            raise ValueError("Не удалось создать субъект для человека B")

        self.synastry_data = self._get_synastry_data()

        self.person_a = {}
        self.person_b = {}
        self._aspects = {'planetary': [], 'extra': []}
        self._planets_in_houses = {}

    def _create_subject(self, data: Dict[str, Any], label: str, save_to_db: bool = False) -> Optional[AstrologicalSubject]:
        """Создаёт AstrologicalSubject из данных пользователя."""
        try:
            name = data.get('name', f'Человек {label}')
            birth_date = data.get('birth_date')
            birth_time = data.get('birth_time')
            birth_place = data.get('birth_place', '')
            utc_str = data.get('birth_timezone')
            lat = data.get('birth_lat')
            lng = data.get('birth_lng')

            def parse_local_datetime():
                try:
                    return datetime.strptime(f"{birth_date} {birth_time}", "%d.%m.%Y %H:%M")
                except:
                    logger.warning(f"Не удалось распарсить дату/время для {name}, используем 2000-01-01 12:00")
                    return datetime(2000, 1, 1, 12, 0)

            def local_to_utc(local_dt: datetime, iana_tz: str) -> datetime:
                try:
                    tz = zoneinfo.ZoneInfo(iana_tz)
                    local_with_tz = local_dt.replace(tzinfo=tz)
                    return local_with_tz.astimezone(timezone.utc)
                except Exception as e:
                    logger.warning(f"Ошибка преобразования времени для {name}: {e}, используем UTC как fallback")
                    return local_dt.replace(tzinfo=timezone.utc)

            coords_available = lat is not None and lng is not None and utc_str is not None

            if coords_available:
                try:
                    utc_str_clean = utc_str.replace('Z', '+00:00')
                    utc_dt = datetime.fromisoformat(utc_str_clean)
                    year, month, day = utc_dt.year, utc_dt.month, utc_dt.day
                    hour, minute = utc_dt.hour, utc_dt.minute
                    logger.info(f"✅ Используем UTC-время из БД для {name}: {utc_dt}")
                    tz_str_for_subject = "UTC"
                except ValueError:
                    logger.warning(f"Не удалось распарсить UTC-строку {utc_str} для {name}, выполняем геокодинг")
                    coords_available = False

            if not coords_available:
                resolver = PlaceResolver()
                city, country = self._parse_place(birth_place)
                logger.info(f"🌐 Выполняем геокодинг для {name}: {city}, {country}")
                lat, lng, iana_tz = resolver.resolve(city, country)
                logger.info(f"🌐 Геокодинг выполнен: ({lat}, {lng}, {iana_tz})")

                local_dt = parse_local_datetime()
                utc_dt = local_to_utc(local_dt, iana_tz)
                year, month, day = utc_dt.year, utc_dt.month, utc_dt.day
                hour, minute = utc_dt.hour, utc_dt.minute
                tz_str_for_subject = "UTC"
                utc_str_saved = utc_dt.isoformat(timespec='seconds')
                logger.info(f"✅ После геокодинга и преобразования: UTC {utc_dt} для {name}")

                computed = (lat, lng, utc_str_saved)
                if label == '1':
                    self._computed_coords_a = computed
                else:
                    self._computed_coords_b = computed

                if save_to_db and self.telegram_id:
                    self._computed_coords_for_db = computed

            # Сохраняем UTC-время для вывода в промпте
            if label == '1':
                self._utc_dt_a = utc_dt
            else:
                self._utc_dt_b = utc_dt

            return AstrologicalSubject(
                name=name,
                year=year, month=month, day=day,
                hour=hour, minute=minute,
                lat=lat, lng=lng,
                tz_str=tz_str_for_subject
            )
        except Exception as e:
            logger.error(f"Ошибка создания субъекта для {label}: {e}")
            return None

    def _parse_place(self, place: str) -> Tuple[str, str]:
        place = place.strip()
        if not place:
            return "Москва", "RU"
        parts = [p.strip() for p in place.split(',') if p.strip()]
        city = parts[0] if parts else "Москва"
        country = parts[1] if len(parts) > 1 else "RU"
        return city, country

    def _get_synastry_data(self) -> Any:
        try:
            chart_data = ChartDataFactory.create_synastry_chart_data(
                first_subject=self.subject_a.model(),
                second_subject=self.subject_b.model(),
                include_house_comparison=True
            )
            logger.info("✅ Synastry Chart Data получен")
            return chart_data
        except Exception as e:
            logger.error(f"❌ Ошибка получения синастрии: {e}")
            raise

    def _extract_person_data(self, subject: AstrologicalSubject, label: str, raw_data: Dict[str, Any]) -> Dict:
        """Извлекает данные одной карты + UTC-дату/время/координаты."""
        if subject is None:
            raise ValueError(f"Subject for {label} is None")
        model = subject.model() if callable(subject.model) else subject.model
        data = model.dict() if hasattr(model, 'dict') else model.__dict__

        # Получаем UTC-дату и время из сохранённых значений
        utc_dt = self._utc_dt_a if label == '1' else self._utc_dt_b
        if utc_dt:
            birth_date_utc = utc_dt.strftime('%d.%m.%Y')
            birth_time_utc = utc_dt.strftime('%H:%M')
        else:
            birth_date_utc = raw_data.get('birth_date', 'не указана')
            birth_time_utc = raw_data.get('birth_time', 'не указано')

        # Координаты
        lat = raw_data.get('birth_lat')
        lng = raw_data.get('birth_lng')
        if lat is None or lng is None:
            if label == '1' and self._computed_coords_a:
                lat, lng, _ = self._computed_coords_a
            elif label == '2' and self._computed_coords_b:
                lat, lng, _ = self._computed_coords_b

        result = {
            'label': label,
            'name': subject.name,
            'birth_date': birth_date_utc,
            'birth_time': birth_time_utc,
            'birth_place': raw_data.get('birth_place'),
            'lat': lat,
            'lng': lng,
            'timezone': "UTC",
            'planets': [],
            'angles': {},
            'houses': []
        }

        # Планеты
        planet_keys = ['sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter',
                       'saturn', 'uranus', 'neptune', 'pluto']
        for key in planet_keys:
            if key in data:
                obj = data[key]
                if isinstance(obj, dict):
                    if 'sign' in obj and 'position' in obj:
                        result['planets'].append({
                            'name': key.capitalize(),
                            'sign': obj.get('sign'),
                            'position': obj.get('position'),
                            'abs_pos': obj.get('abs_pos'),
                            'house': obj.get('house'),
                            'retrograde': obj.get('retrograde', False),
                        })
                else:
                    if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                        result['planets'].append({
                            'name': key.capitalize(),
                            'sign': getattr(obj, 'sign'),
                            'position': getattr(obj, 'position'),
                            'abs_pos': getattr(obj, 'abs_pos'),
                            'house': getattr(obj, 'house'),
                            'retrograde': getattr(obj, 'retrograde', False),
                        })

        # Дополнительные точки (только True_Lilith)
        extra_keys = [
            ('true_north_lunar_node', 'True_North_Lunar_Node'),
            ('true_south_lunar_node', 'True_South_Lunar_Node'),
            ('chiron', 'Chiron'),
            ('true_lilith', 'True_Lilith')
        ]
        for key, name in extra_keys:
            if key in data and data[key] is not None:
                obj = data[key]
                if isinstance(obj, dict):
                    if 'sign' in obj and 'position' in obj:
                        result['planets'].append({
                            'name': name,
                            'sign': obj.get('sign'),
                            'position': obj.get('position'),
                            'abs_pos': obj.get('abs_pos'),
                            'house': obj.get('house'),
                            'retrograde': obj.get('retrograde', False),
                        })
                else:
                    if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                        result['planets'].append({
                            'name': name,
                            'sign': getattr(obj, 'sign'),
                            'position': getattr(obj, 'position'),
                            'abs_pos': getattr(obj, 'abs_pos'),
                            'house': getattr(obj, 'house'),
                            'retrograde': getattr(obj, 'retrograde', False),
                        })

        if not any(p['name'] == 'True_Lilith' for p in result['planets']):
            logger.warning(f"True_Lilith отсутствует для {subject.name}")

        # Углы
        def _extract_angle(obj):
            if obj is None:
                return None
            if isinstance(obj, dict):
                return {'sign': obj.get('sign'), 'position': obj.get('position'), 'abs_pos': obj.get('abs_pos')}
            if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                return {'sign': getattr(obj, 'sign'), 'position': getattr(obj, 'position'), 'abs_pos': getattr(obj, 'abs_pos')}
            return None

        asc = _extract_angle(data.get('ascendant'))
        mc = _extract_angle(data.get('medium_coeli'))
        dsc = _extract_angle(data.get('descendant'))
        ic = _extract_angle(data.get('imum_coeli'))

        if not asc and hasattr(subject, 'ascendant'):
            asc = _extract_angle(subject.ascendant)
        if not mc and hasattr(subject, 'midheaven'):
            mc = _extract_angle(subject.midheaven)

        result['angles'] = {
            'ASC': asc,
            'MC': mc,
            'DSC': dsc,
            'IC': ic
        }

        # Дома
        house_keys = [
            'first_house', 'second_house', 'third_house', 'fourth_house',
            'fifth_house', 'sixth_house', 'seventh_house', 'eighth_house',
            'ninth_house', 'tenth_house', 'eleventh_house', 'twelfth_house'
        ]
        for key in house_keys:
            if key in data:
                obj = data[key]
                if isinstance(obj, dict):
                    if 'sign' in obj and 'position' in obj:
                        result['houses'].append({
                            'key': key,
                            'sign': obj.get('sign'),
                            'position': obj.get('position'),
                            'abs_pos': obj.get('abs_pos'),
                        })
                else:
                    if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                        result['houses'].append({
                            'key': key,
                            'sign': getattr(obj, 'sign'),
                            'position': getattr(obj, 'position'),
                            'abs_pos': getattr(obj, 'abs_pos'),
                        })

        return result

    def _filter_aspects(self) -> None:
        if not self.synastry_data:
            logger.warning("Нет данных синастрии")
            return

        if not hasattr(self.synastry_data, 'aspects'):
            logger.warning("Нет аспектов в синастрии")
            return

        aspects = self.synastry_data.aspects
        logger.info(f"Всего аспектов в синастрии: {len(aspects)}")

        if aspects:
            first = aspects[0]
            logger.info(f"Первый аспект: {first}")
            logger.info(f"Атрибуты первого аспекта: {dir(first)}")

        planetary = []
        extra = []

        seen_planetary = set()
        seen_extra = set()

        angle_map = {
            'Ascendant': 'ASC',
            'Midheaven': 'MC',
            'Descendant': 'DSC',
            'ImumCoeli': 'IC'
        }

        def normalize_name(name):
            return angle_map.get(name, name)

        for a in aspects:
            p1 = getattr(a, 'p1_name', None)
            p2 = getattr(a, 'p2_name', None)
            if not p1 or not p2:
                p1 = getattr(a, 'first_point_name', None)
                p2 = getattr(a, 'second_point_name', None)

            aspect = getattr(a, 'aspect', None)
            orbit = getattr(a, 'orbit', getattr(a, 'orb', None))
            movement = getattr(a, 'aspect_movement', None)

            if not p1 or not p2 or not aspect or orbit is None:
                continue

            p1_norm = normalize_name(p1)
            p2_norm = normalize_name(p2)

            owner1 = '1'
            owner2 = '2'

            logger.info(f"Аспект: {p1_norm}({owner1}) — {aspect} — {p2_norm}({owner2}), орб {orbit:.2f}")

            if aspect.lower() not in self.ALLOWED_ASPECTS:
                logger.info(f"Аспект {aspect} не входит в ALLOWED_ASPECTS, пропускаем")
                continue

            p1_in_main = p1_norm in self.MAIN_PLANETS
            p2_in_main = p2_norm in self.MAIN_PLANETS
            p1_in_extra = p1_norm in self.EXTRA_OBJECTS
            p2_in_extra = p2_norm in self.EXTRA_OBJECTS

            if p1_in_main and p2_in_main:
                key = (p1_norm, p2_norm, aspect.lower())
                if key in seen_planetary:
                    continue
                seen_planetary.add(key)
                max_orb = self.SYNASTRY_ASPECT_ORBS.get(aspect.lower(), 8.0)
                if orbit <= max_orb:
                    planetary.append({
                        'p1': p1_norm,
                        'p2': p2_norm,
                        'owner1': owner1,
                        'owner2': owner2,
                        'aspect': aspect,
                        'orb': orbit,
                        'movement': movement
                    })
                    logger.info(f"Добавлен планетарный аспект: {p1_norm} — {aspect} — {p2_norm}, орб {orbit:.2f}")
                else:
                    logger.info(f"Планетарный аспект {p1_norm} — {aspect} — {p2_norm} имеет орб {orbit:.2f} > {max_orb}, пропускаем")

            elif (p1_in_main and p2_in_extra) or (p2_in_main and p1_in_extra):
                if p1_in_main:
                    planet, extra_obj = p1_norm, p2_norm
                    owner_planet, owner_extra = owner1, owner2
                else:
                    planet, extra_obj = p2_norm, p1_norm
                    owner_planet, owner_extra = owner2, owner1

                key = (planet, extra_obj, aspect.lower())
                if key in seen_extra:
                    continue
                seen_extra.add(key)

                if extra_obj == 'True_Lilith':
                    max_orb = self.LILITH_ASPECT_ORBS.get(aspect.lower(), 3.0)
                else:
                    max_orb = self.EXTRA_ASPECT_ORBS.get(aspect.lower(), 5.0)

                if orbit <= max_orb:
                    extra.append({
                        'p1': planet,
                        'p2': extra_obj,
                        'owner1': owner_planet,
                        'owner2': owner_extra,
                        'aspect': aspect,
                        'orb': orbit,
                        'movement': movement
                    })
                    logger.info(f"Добавлен extra аспект: {planet} — {aspect} — {extra_obj}, орб {orbit:.2f}")
                else:
                    logger.info(f"Extra аспект {planet} — {aspect} — {extra_obj} имеет орб {orbit:.2f} > {max_orb}, пропускаем")
            else:
                logger.info(f"Аспект {p1_norm} — {aspect} — {p2_norm} не подходит ни под одну категорию, пропускаем")

        self._aspects = {'planetary': planetary, 'extra': extra}
        logger.info(f"Итого: планетарных {len(planetary)}, extra {len(extra)}")

    def _get_planets_in_houses(self) -> Dict:
        """Извлекает попадание планет одного человека в дома другого.
        Исключает Mean_Lilith и углы (ASC, MC, DSC, IC)."""
        result = {'a_in_b': [], 'b_in_a': []}

        if not self.synastry_data:
            return result

        if not hasattr(self.synastry_data, 'house_comparison'):
            return result

        hc = self.synastry_data.house_comparison

        allowed_objects = set(self.MAIN_PLANETS)
        allowed_objects.add('True_North_Lunar_Node')
        allowed_objects.add('True_South_Lunar_Node')
        allowed_objects.add('Chiron')
        allowed_objects.add('True_Lilith')

        def is_allowed(point_name):
            return point_name in allowed_objects

        if hasattr(hc, 'first_points_in_second_houses') and hc.first_points_in_second_houses:
            for item in hc.first_points_in_second_houses:
                if isinstance(item, dict):
                    point_name = item.get('point_name')
                    house = item.get('projected_house_number')
                else:
                    point_name = getattr(item, 'point_name', None)
                    house = getattr(item, 'projected_house_number', None)
                if point_name and house and is_allowed(point_name):
                    result['a_in_b'].append({'planet': point_name, 'house': house})

        if hasattr(hc, 'second_points_in_first_houses') and hc.second_points_in_first_houses:
            for item in hc.second_points_in_first_houses:
                if isinstance(item, dict):
                    point_name = item.get('point_name')
                    house = item.get('projected_house_number')
                else:
                    point_name = getattr(item, 'point_name', None)
                    house = getattr(item, 'projected_house_number', None)
                if point_name and house and is_allowed(point_name):
                    result['b_in_a'].append({'planet': point_name, 'house': house})

        logger.info(f"Планеты 1 в домах 2: {len(result['a_in_b'])}, Планеты 2 в домах 1: {len(result['b_in_a'])}")
        return result

    def build_context(self) -> str:
        """
        Строит контекст синастрии в новом формате (без системной инструкции).
        Используется для вставки в prompt_connect.txt.
        """
        self.person_a = self._extract_person_data(self.subject_a, '1', self.person_a_data)
        self.person_b = self._extract_person_data(self.subject_b, '2', self.person_b_data)

        self._filter_aspects()
        self._planets_in_houses = self._get_planets_in_houses()

        return self._format_context()

    def _format_context(self) -> str:
        """
        Формирует контекст в новом формате с заголовками ###.
        """
        lines = []

        # 1. Параметры
        lines.append("### Параметры")
        lines.append("")
        lines.append("Тип анализа: Натальная синастрия")
        lines.append("Зодиак: Tropical")
        lines.append("Система домов: Placidus")
        lines.append("Перспектива: Geocentric")
        lines.append("")

        # 2. Человек 1
        lines.extend(self._format_person_context(self.person_a, '1'))

        # 3. Человек 2
        lines.extend(self._format_person_context(self.person_b, '2'))

        # 4. Аспекты между планетами
        if self._aspects['planetary']:
            lines.append("### Аспекты между планетами")
            lines.append("")
            for a in self._aspects['planetary']:
                lines.append(self._format_aspect(a))
            lines.append("")
        else:
            lines.append("### Аспекты между планетами")
            lines.append("")
            lines.append("Нет значимых аспектов")
            lines.append("")

        # 5. Аспекты к дополнительным точкам и углам
        if self._aspects['extra']:
            lines.append("### Аспекты к дополнительным точкам и углам")
            lines.append("")
            for a in self._aspects['extra']:
                lines.append(self._format_aspect(a))
            lines.append("")
        else:
            lines.append("### Аспекты к дополнительным точкам и углам")
            lines.append("")
            lines.append("Нет значимых аспектов")
            lines.append("")

        # 6. Планеты человека 1 в домах человека 2
        if self._planets_in_houses['a_in_b']:
            lines.append("### Планеты человека 1 в домах человека 2")
            lines.append("")
            for item in self._planets_in_houses['a_in_b']:
                planet = self.PLANET_MAP.get(item['planet'], item['planet'])
                lines.append(f"{planet} 1 → {item['house']} дом 2")
            lines.append("")
        else:
            lines.append("### Планеты человека 1 в домах человека 2")
            lines.append("")
            lines.append("Нет данных")
            lines.append("")

        # 7. Планеты человека 2 в домах человека 1
        if self._planets_in_houses['b_in_a']:
            lines.append("### Планеты человека 2 в домах человека 1")
            lines.append("")
            for item in self._planets_in_houses['b_in_a']:
                planet = self.PLANET_MAP.get(item['planet'], item['planet'])
                lines.append(f"{planet} 2 → {item['house']} дом 1")
            lines.append("")
        else:
            lines.append("### Планеты человека 2 в домах человека 1")
            lines.append("")
            lines.append("Нет данных")
            lines.append("")

        return "\n".join(lines)

    def _format_person_context(self, person: Dict, label: str) -> List[str]:
        """
        Форматирует данные одного человека для нового формата.
        """
        lines = []
        lines.append(f"### Человек {label}")
        lines.append("")
        lines.append(f"Имя: {person['name']}")
        lines.append(f"Дата рождения: {person.get('birth_date', 'не указана')}")
        lines.append(f"Время рождения: {person.get('birth_time', 'не указано')}")
        lat = person.get('lat')
        lng = person.get('lng')
        if lat is not None and lng is not None:
            lines.append(f"Координаты рождения: {lat:.4f}° N, {lng:.4f}° E")
        else:
            lines.append("Координаты рождения: не указаны")
        lines.append("Часовой пояс: UTC")
        lines.append("")

        # Углы
        lines.append(f"### Углы человека {label}")
        lines.append("")
        for angle_name in ['ASC', 'MC', 'DSC', 'IC']:
            angle = person['angles'].get(angle_name)
            if angle:
                sign = self.SIGN_MAP.get(angle.get('sign'), angle.get('sign'))
                pos = angle.get('position', 0.0)
                lines.append(f"{angle_name}: {sign} {pos:.2f}°")
            else:
                lines.append(f"{angle_name}: —")
        lines.append("")

        # Планеты
        lines.append(f"### Планеты человека {label}")
        lines.append("")
        planet_order = ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                        'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']
        for name in planet_order:
            planet = next((p for p in person['planets'] if p['name'] == name), None)
            if planet:
                lines.append(self._format_planet(planet))
        lines.append("")

        # Дополнительные точки
        extra_order = ['True_North_Lunar_Node', 'True_South_Lunar_Node', 'Chiron', 'True_Lilith']
        lines.append(f"### Дополнительные точки человека {label}")
        lines.append("")
        has_extra = False
        for name in extra_order:
            point = next((p for p in person['planets'] if p['name'] == name), None)
            if point:
                lines.append(self._format_planet(point))
                has_extra = True
        if not has_extra:
            lines.append("Нет дополнительных точек")
        lines.append("")

        # Куспиды домов
        lines.append(f"### Куспиды домов человека {label}")
        lines.append("")
        house_order = ['first_house', 'second_house', 'third_house', 'fourth_house',
                       'fifth_house', 'sixth_house', 'seventh_house', 'eighth_house',
                       'ninth_house', 'tenth_house', 'eleventh_house', 'twelfth_house']
        for key in house_order:
            house = next((h for h in person['houses'] if h['key'] == key), None)
            if house:
                sign = self.SIGN_MAP.get(house['sign'], house['sign'])
                pos = house['position']
                house_display = self.HOUSE_MAP.get(self._house_key_to_standard(key), key)
                lines.append(f"{house_display}: {sign} {pos:.2f}°")
            else:
                house_display = self.HOUSE_MAP.get(self._house_key_to_standard(key), key)
                lines.append(f"{house_display}: —")
        lines.append("")

        return lines

    def _house_key_to_standard(self, key: str) -> str:
        return key.replace('_', ' ').title().replace(' ', '_')

    def _format_planet(self, planet: Dict) -> str:
        name = self.PLANET_MAP.get(planet['name'], planet['name'])
        sign = self.SIGN_MAP.get(planet['sign'], planet['sign'])
        pos = planet['position']
        house = planet['house']
        retro = planet['retrograde']

        if house is None or house == 0:
            house_display = "неизвестный дом"
        elif isinstance(house, int):
            house_display = f"{house} дом"
        elif isinstance(house, str):
            house_display = self.HOUSE_MAP.get(house, house)
        else:
            house_display = "неизвестный дом"

        if retro:
            return f"{name}: {sign} {pos:.2f}°, {house_display}, ретроградный"
        return f"{name}: {sign} {pos:.2f}°, {house_display}"

    def _format_aspect(self, aspect: Dict) -> str:
        p1 = aspect['p1']
        p2 = aspect['p2']
        owner1 = aspect.get('owner1', '?')
        owner2 = aspect.get('owner2', '?')

        p1_display = self._get_display_name(p1, owner1)
        p2_display = self._get_display_name(p2, owner2)

        aspect_name = self.ASPECT_MAP.get(aspect['aspect'].lower(), aspect['aspect'])
        orb = aspect['orb']
        movement = aspect.get('movement')

        if movement:
            phase = self.PHASE_MAP.get(movement.lower(), '')
            if phase:
                return f"{p1_display} — {aspect_name} — {p2_display}, орб {orb:.2f}°, {phase}"

        return f"{p1_display} — {aspect_name} — {p2_display}, орб {orb:.2f}°"

    def _get_display_name(self, name: str, label: str) -> str:
        display = self.PLANET_MAP.get(name, name)
        if label and label != '?':
            return f"{display} {label}"
        return display