import logging
import zoneinfo
from datetime import datetime
from typing import Dict, Any, Optional, Tuple
from pathlib import Path

from kerykeion import AstrologicalSubject

from bot.utils.place_resolver import PlaceResolver
from bot.db import save_user_coords
from bot.services.gemini import GeminiService

logger = logging.getLogger(__name__)


class AstrologyCalculator:
    def __init__(self, user_data: Dict[str, Any], lang: str = 'ru',
                 telegram_id: Optional[int] = None,
                 coords: Optional[Tuple[float, float, str]] = None,
                 emulation_mode: bool = False,
                 gemini_service: Optional[GeminiService] = None):
        self.user_data = user_data
        self.lang = lang
        self.telegram_id = telegram_id
        self._coords = coords
        self.emulation_mode = emulation_mode
        self.gemini = gemini_service or GeminiService()

        self.name = user_data.get('name', 'Человек')
        self.gender = user_data.get('gender', 'M')
        self.birth_date = user_data.get('birth_date')
        self.birth_time = user_data.get('birth_time')
        self.birth_place = user_data.get('birth_place', '')

        self._calculated_coords = None
        self._natal_data = None
        self._prompt_data = None

        self.resolver = PlaceResolver(gemini_service=self.gemini)

    def _parse_birth_place(self) -> Tuple[str, str]:
        place = self.birth_place.strip()
        if not place:
            return "Москва", "RU"
        parts = [p.strip() for p in place.split(',') if p.strip()]
        city = parts[0] if parts else "Москва"
        country = parts[1] if len(parts) > 1 else "RU"
        return city, country

    def _get_coordinates_and_timezone(self) -> Tuple[float, float, str]:
        # 1. БД
        lat = self.user_data.get('birth_lat')
        lng = self.user_data.get('birth_lng')
        tz = self.user_data.get('birth_timezone')
        if lat is not None and lng is not None and tz:
            if tz in zoneinfo.available_timezones():
                logger.info(f"✅ Используем координаты из БД: ({lat}, {lng}, {tz})")
                return lat, lng, tz
            elif tz == "UNKNOWN":
                logger.info(f"ℹ️ В БД таймзона 'UNKNOWN', используем координаты ({lat}, {lng}) и определяем таймзону по координатам")
                tz_from_coords = self.resolver._tf.timezone_at(lat=lat, lng=lng)
                if tz_from_coords and tz_from_coords in zoneinfo.available_timezones():
                    tz = tz_from_coords
                    self._calculated_coords = (lat, lng, tz)
                    return lat, lng, tz
                else:
                    logger.warning(f"Не удалось определить таймзону по координатам, используем DEFAULT_TZ")
                    tz = self.DEFAULT_TZ
                    self._calculated_coords = (lat, lng, tz)
                    return lat, lng, tz
            else:
                logger.warning(f"⚠️ Таймзона из БД {tz} невалидна, игнорируем")

        # 2. Переданные
        if self._coords:
            lat, lng, tz = self._coords
            if tz in zoneinfo.available_timezones():
                logger.info(f"✅ Используем переданные координаты: ({lat}, {lng}, {tz})")
                return lat, lng, tz
            else:
                logger.warning(f"⚠️ Переданная таймзона {tz} невалидна, игнорируем")

        # 3. PlaceResolver
        city, country = self._parse_birth_place()
        lat, lng, tz = self.resolver.resolve(
            city, country,
            self.birth_date or "01.01.2000",
            self.birth_time or "12:00"
        )
        self._calculated_coords = (lat, lng, tz)
        logger.info(f"🔍 _calculated_coords установлен: {self._calculated_coords}")
        return lat, lng, tz

    def _build_natal_chart(self) -> Dict[str, Any]:
        if self._natal_data is not None:
            return self._natal_data

        logger.info("🔮 Строим натальную карту...")
        lat, lng, tz_str = self._get_coordinates_and_timezone()

        utc_dt = self.resolver.get_utc_datetime()
        if utc_dt:
            year, month, day = utc_dt.year, utc_dt.month, utc_dt.day
            hour, minute = utc_dt.hour, utc_dt.minute
            tz_str_for_subject = "UTC"
            logger.info(f"✅ Используем уточнённое UTC время: {utc_dt}")
        else:
            try:
                dt = datetime.strptime(f"{self.birth_date} {self.birth_time}", "%d.%m.%Y %H:%M")
                year, month, day, hour, minute = dt.year, dt.month, dt.day, dt.hour, dt.minute
            except:
                year, month, day, hour, minute = 2000, 1, 1, 12, 0
            tz_str_for_subject = tz_str
            logger.info(f"⚠️ Используем локальное время и IANA: {tz_str_for_subject}")

        subject = AstrologicalSubject(
            name=self.name,
            year=year, month=month, day=day,
            hour=hour, minute=minute,
            lat=lat, lng=lng,
            tz_str=tz_str_for_subject
        )
        logger.info(f"👤 Субъект создан: {subject.name}")

        model = subject.model() if callable(subject.model) else subject.model
        data = model.dict() if hasattr(model, 'dict') else model.__dict__

        planet_keys = ['sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter', 'saturn',
                       'uranus', 'neptune', 'pluto', 'chiron', 'mean_lilith', 'true_lilith']
        planets = []
        for key in planet_keys:
            if key in data:
                obj = data[key]
                if isinstance(obj, dict):
                    if 'sign' in obj and 'position' in obj:
                        planets.append({
                            'name': key.capitalize(),
                            'sign': obj.get('sign', 'unknown'),
                            'degree': obj.get('position', 0.0),
                            'house': obj.get('house', 0),
                            'retrograde': obj.get('retrograde', False),
                        })
                else:
                    if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                        planets.append({
                            'name': key.capitalize(),
                            'sign': getattr(obj, 'sign', 'unknown'),
                            'degree': getattr(obj, 'position', 0.0),
                            'house': getattr(obj, 'house', 0),
                            'retrograde': getattr(obj, 'retrograde', False),
                        })

        house_keys = ['first_house', 'second_house', 'third_house', 'fourth_house',
                      'fifth_house', 'sixth_house', 'seventh_house', 'eighth_house',
                      'ninth_house', 'tenth_house', 'eleventh_house', 'twelfth_house']
        houses = []
        for i, key in enumerate(house_keys, 1):
            if key in data:
                obj = data[key]
                if isinstance(obj, dict):
                    if 'sign' in obj and 'position' in obj:
                        houses.append({
                            'number': i,
                            'sign': obj.get('sign', 'unknown'),
                            'degree': obj.get('position', 0.0),
                        })
                else:
                    if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                        houses.append({
                            'number': i,
                            'sign': getattr(obj, 'sign', 'unknown'),
                            'degree': getattr(obj, 'position', 0.0),
                        })

        aspects = []
        try:
            from kerykeion import AspectsFactory
            aspects_data = AspectsFactory.single_chart_aspects(subject)
            if aspects_data and hasattr(aspects_data, 'aspects') and aspects_data.aspects:
                for a in aspects_data.aspects:
                    aspects.append({
                        'p1': getattr(a, 'p1_name', 'unknown'),
                        'p2': getattr(a, 'p2_name', 'unknown'),
                        'aspect': getattr(a, 'aspect', 'unknown'),
                        'orb': getattr(a, 'orbit', getattr(a, 'orb', 0.0)),
                    })
        except Exception as e:
            logger.warning(f"⚠️ Не удалось получить аспекты: {e}")

        def _extract_angle(obj):
            if obj is None:
                return 0.0
            if isinstance(obj, (int, float)):
                return float(obj)
            if isinstance(obj, dict):
                if 'position' in obj:
                    return float(obj['position'])
                if 'value' in obj:
                    return float(obj['value'])
                for v in obj.values():
                    if isinstance(v, (int, float)):
                        return float(v)
                return 0.0
            if hasattr(obj, 'position'):
                return float(obj.position)
            if hasattr(obj, 'value'):
                return float(obj.value)
            try:
                return float(obj)
            except:
                return 0.0

        asc = _extract_angle(data.get('ascendant'))
        mc = _extract_angle(data.get('midheaven'))
        if asc == 0.0 and hasattr(subject, 'ascendant'):
            asc = _extract_angle(subject.ascendant)
        if mc == 0.0 and hasattr(subject, 'midheaven'):
            mc = _extract_angle(subject.midheaven)

        dsc = (asc + 180) % 360
        ic = (mc + 180) % 360

        self._natal_data = {
            'planets': planets,
            'houses': houses,
            'aspects': aspects,
            'angles': {'ASC': asc, 'MC': mc, 'DSC': dsc, 'IC': ic},
            'utc_datetime': getattr(subject, 'iso_formatted_utc_datetime', None),
            'timezone': tz_str,
            'location': {'lat': lat, 'lng': lng}
        }
        logger.info(f"✅ Натальная карта построена: {len(planets)} планет, {len(houses)} домов, {len(aspects)} аспектов")
        return self._natal_data

    def _prepare_prompt_data(self) -> Dict[str, str]:
        if self._prompt_data is not None:
            return self._prompt_data

        natal = self._build_natal_chart()
        planets = natal['planets']
        houses = natal['houses']
        aspects = natal['aspects']
        angles = natal['angles']
        loc = natal['location']

        def fmt_planets():
            return "\n".join(
                f"- {p['name']} в {p['sign']} ({p['degree']:.2f}°) в {p['house']} доме, ретроградность: {'да' if p['retrograde'] else 'нет'}"
                for p in planets
            )

        def fmt_houses():
            return "\n".join(
                f"- Дом {h['number']}: {h['sign']} ({h['degree']:.2f}°)"
                for h in houses
            )

        def fmt_aspects():
            return "\n".join(
                f"- {a['p1']} {a['aspect']} {a['p2']} (орбис: {a['orb']:.2f}°)"
                for a in aspects[:20]
            )

        gender_text = "Мужчина" if self.gender == 'M' else "Женщина"

        self._prompt_data = {
            'name': self.name,
            'gender': gender_text,
            'birth_date': self.birth_date or 'не указана',
            'birth_time': self.birth_time or 'не указано',
            'birth_place': self.birth_place or 'не указано',
            'lat': f"{loc['lat']:.4f}",
            'lng': f"{loc['lng']:.4f}",
            'timezone': natal['timezone'],
            'utc_datetime': natal['utc_datetime'] or 'не известно',
            'planets_list': fmt_planets(),
            'houses_list': fmt_houses(),
            'aspects_list': fmt_aspects(),
            'angles': f"ASC: {angles['ASC']:.2f}°, MC: {angles['MC']:.2f}°, DSC: {angles['DSC']:.2f}°, IC: {angles['IC']:.2f}°",
            'pronoun': 'он' if self.gender == 'M' else 'она',
            'possessive': 'его' if self.gender == 'M' else 'её',
        }
        return self._prompt_data

    def _load_prompt_template(self) -> str:
        base = Path(__file__).parent.parent.parent / 'prompts' / 'prompt_astrology_v4.txt'
        try:
            with open(base, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            logger.error(f"Шаблон {base} не найден")
            return ""

    def _build_prompt(self) -> str:
        template = self._load_prompt_template()
        if not template:
            return "❌ Шаблон промпта не найден."

        data = self._prepare_prompt_data()
        lang_inst = "IMPORTANT: Respond in English only." if self.lang == 'en' else "ВАЖНО: Отвечай только на русском языке."

        prompt = template
        for k, v in data.items():
            prompt = prompt.replace(f'{{{k}}}', str(v))
        prompt = prompt.replace('{language_instruction}', lang_inst)
        return prompt

    async def generate(self) -> str:
        # Сохраняем координаты и таймзону
        if self._calculated_coords and self.telegram_id:
            lat, lng, tz = self._calculated_coords
            refined_tz = self.resolver.get_refined_timezone()
            tz_to_save = tz if refined_tz != "UNKNOWN" else "UNKNOWN"
            logger.info(f"💾 Сохраняем координаты в БД: {lat}, {lng}, {tz_to_save} для {self.telegram_id}")
            result = await save_user_coords(self.telegram_id, lat, lng, tz_to_save)
            if result:
                logger.info(f"✅ Координаты сохранены в БД для {self.telegram_id}")
            else:
                logger.error(f"❌ Ошибка сохранения координат для {self.telegram_id}")

        prompt = self._build_prompt()

        if self.emulation_mode:
            return f"🔍 РЕЖИМ ЭМУЛЯЦИИ (промпт не отправлен в нейросеть):\n\n{prompt}"

        if not self.gemini:
            return "❌ Gemini сервис недоступен."

        try:
            return self.gemini.send_raw_prompt(prompt)
        except Exception as e:
            logger.error(f"Ошибка Gemini: {e}")
            return f"❌ Ошибка получения ответа: {str(e)}"

    def get_basic_parameters(self) -> Dict[str, str]:
        data = self._prepare_prompt_data()
        return {
            'name': data['name'],
            'gender': data['gender'],
            'birth_date': data['birth_date'],
            'birth_time': data['birth_time'],
            'birth_place': data['birth_place'],
            'lat': data['lat'],
            'lng': data['lng'],
            'timezone': data['timezone'],
            'utc_datetime': data['utc_datetime'],
            'angles': data['angles'],
        }