import logging
import zoneinfo
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple, Union
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
        self._coords = coords  # (lat, lng, tz_iana) – если переданы готовые
        self.emulation_mode = emulation_mode
        self.gemini = gemini_service or GeminiService()

        self.name = user_data.get('name', 'Человек')
        self.gender = user_data.get('gender', 'M')
        self.birth_date = user_data.get('birth_date')
        self.birth_time = user_data.get('birth_time')
        self.birth_place = user_data.get('birth_place', '')

        self._calculated_coords = None      # (lat, lng) – сохраняем для записи в БД
        self._calculated_utc_str = None     # строка UTC для записи в БД
        self._utc_dt = None                 # datetime (aware UTC) для расчётов
        self._natal_data = None
        self._prompt_data = None

        self.resolver = PlaceResolver()

    def _parse_birth_place(self) -> Tuple[str, str]:
        place = self.birth_place.strip()
        if not place:
            return "Москва", "RU"
        parts = [p.strip() for p in place.split(',') if p.strip()]
        city = parts[0] if parts else "Москва"
        country = parts[1] if len(parts) > 1 else "RU"
        return city, country

    def _get_coordinates_and_utc(self) -> Tuple[float, float, datetime]:
        """
        Возвращает (lat, lng, utc_datetime).
        utc_datetime – aware datetime в UTC.
        """
        # 1. Проверяем наличие координат и UTC-строки в БД
        lat = self.user_data.get('birth_lat')
        lng = self.user_data.get('birth_lng')
        utc_str = self.user_data.get('birth_timezone')  # теперь это UTC-строка

        if lat is not None and lng is not None and utc_str:
            try:
                # Парсим UTC-строку (ожидаем формат с +00:00)
                utc_dt = datetime.fromisoformat(utc_str)
                if utc_dt.tzinfo is None:
                    utc_dt = utc_dt.replace(tzinfo=timezone.utc)
                # Проверяем, что это UTC
                if utc_dt.utcoffset() != timezone.utc.utcoffset(utc_dt):
                    raise ValueError("Not UTC")
                logger.info(f"✅ Используем координаты и UTC из БД: lat={lat}, lng={lng}, utc={utc_dt}")
                self._utc_dt = utc_dt
                return lat, lng, utc_dt
            except Exception as e:
                logger.warning(f"⚠️ Не удалось распарсить UTC-строку из БД: {utc_str}, ошибка: {e}. Выполняем пересчёт.")

        # 2. Проверяем переданные координаты (если есть)
        if self._coords:
            iana_lat, iana_lng, iana_tz = self._coords
            if iana_tz in zoneinfo.available_timezones():
                # Преобразуем локальное время в UTC для этой зоны
                utc_dt = self._local_to_utc(iana_tz)
                logger.info(f"✅ Используем переданные координаты: ({iana_lat}, {iana_lng}, {iana_tz}) -> UTC {utc_dt}")
                self._calculated_coords = (iana_lat, iana_lng)
                self._utc_dt = utc_dt
                return iana_lat, iana_lng, utc_dt
            else:
                logger.warning(f"⚠️ Переданная таймзона {iana_tz} невалидна, игнорируем")

        # 3. Геокодинг и преобразование
        city, country = self._parse_birth_place()
        lat, lng, iana_tz = self.resolver.resolve(city, country)
        logger.info(f"🌐 Геокодинг выполнен: ({lat}, {lng}, {iana_tz})")

        # Преобразуем локальное время в UTC с учётом исторических переходов
        utc_dt = self._local_to_utc(iana_tz)

        # Сохраняем для последующей записи в БД
        self._calculated_coords = (lat, lng)
        self._utc_dt = utc_dt
        self._calculated_utc_str = utc_dt.isoformat(timespec='seconds')

        logger.info(f"🔍 _calculated_coords установлен: {self._calculated_coords}")
        logger.info(f"🔍 _calculated_utc_str: {self._calculated_utc_str}")
        return lat, lng, utc_dt

    def _local_to_utc(self, iana_tz: str) -> datetime:
        """Преобразует локальное время рождения в UTC для указанной IANA-зоны."""
        try:
            local_dt = datetime.strptime(f"{self.birth_date} {self.birth_time}", "%d.%m.%Y %H:%M")
        except:
            local_dt = datetime(2000, 1, 1, 12, 0)

        tz = zoneinfo.ZoneInfo(iana_tz)
        local_with_tz = local_dt.replace(tzinfo=tz)
        utc_dt = local_with_tz.astimezone(timezone.utc)
        return utc_dt

    def _build_natal_chart(self) -> Dict[str, Any]:
        if self._natal_data is not None:
            return self._natal_data

        logger.info("🔮 Строим натальную карту...")
        lat, lng, utc_dt = self._get_coordinates_and_utc()

        # Создаём субъект с UTC временем и tz_str="UTC"
        subject = AstrologicalSubject(
            name=self.name,
            year=utc_dt.year,
            month=utc_dt.month,
            day=utc_dt.day,
            hour=utc_dt.hour,
            minute=utc_dt.minute,
            lat=lat,
            lng=lng,
            tz_str="UTC"
        )
        logger.info(f"👤 Субъект создан: {subject.name}")

        # Извлекаем данные (планеты, дома, аспекты, углы)
        model = subject.model() if callable(subject.model) else subject.model
        data = model.dict() if hasattr(model, 'dict') else model.__dict__

        # --- планеты ---
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

        # --- дома ---
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

        # --- аспекты ---
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

        # --- углы ---
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
            'timezone': "UTC",  # мы передаём UTC в kerykeion
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
            'timezone': "UTC",  # показываем, что мы используем UTC
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
        # Сначала строим карту – это гарантирует, что координаты и UTC определены
        self._build_natal_chart()

        # Сохраняем координаты и UTC-строку в БД (если есть что сохранять)
        if self._calculated_coords and self.telegram_id:
            lat, lng = self._calculated_coords
            utc_str = self._calculated_utc_str
            if not utc_str and self._utc_dt:
                utc_str = self._utc_dt.isoformat(timespec='seconds')
            if utc_str:
                logger.info(f"💾 Сохраняем координаты и UTC в БД: lat={lat}, lng={lng}, utc={utc_str} для {self.telegram_id}")
                result = await save_user_coords(self.telegram_id, lat, lng, utc_str)
                if result:
                    logger.info(f"✅ Координаты и UTC сохранены в БД для {self.telegram_id}")
                else:
                    logger.error(f"❌ Ошибка сохранения координат для {self.telegram_id}")
            else:
                logger.warning("⚠️ Нет UTC-строки для сохранения")
        else:
            logger.warning(f"⚠️ Не удалось сохранить: _calculated_coords={self._calculated_coords}, telegram_id={self.telegram_id}")

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