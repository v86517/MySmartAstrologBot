# bot\calculators\astrology_calculator.py
import logging
import zoneinfo
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple
from pathlib import Path

from kerykeion import (
    AstrologicalSubject,
    AspectsFactory,
)
from bot.utils.place_resolver import PlaceResolver
from bot.db import save_user_coords
from bot.services.gemini import GeminiService
from bot.calculators.natal_context_builder import NatalContextBuilder

logger = logging.getLogger(__name__)


class AstrologyCalculator:
    """
    Калькулятор для услуги «Натальная карта» (астрология).
    Использует PlaceResolver для геокодинга, zoneinfo для преобразования времени,
    и NatalContextBuilder для формирования структурированного текста для LLM.
    """

    def __init__(self, user_data: Dict[str, Any], lang: str = 'ru',
                 telegram_id: Optional[int] = None,
                 coords: Optional[Tuple[float, float, str]] = None,
                 emulation_mode: bool = False,
                 gemini_service: Optional[GeminiService] = None):
        self.user_data = user_data
        self.lang = lang
        self.telegram_id = telegram_id
        self._coords = coords  # (lat, lng, iana_tz) – если переданы готовые
        self.emulation_mode = emulation_mode
        self.gemini = gemini_service or GeminiService()

        self.name = user_data.get('name', 'Человек')
        self.gender = user_data.get('gender', 'M')
        self.birth_date = user_data.get('birth_date')
        self.birth_time = user_data.get('birth_time')
        self.birth_place = user_data.get('birth_place', '')

        self._calculated_coords = None      # (lat, lng) – для записи в БД
        self._calculated_utc_str = None     # строка UTC для записи в БД
        self._utc_dt = None                 # datetime (aware UTC) для расчётов
        self._natal_data = None             # словарь с данными карты
        self._subject = None                # объект AstrologicalSubject для билдера

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
        Приоритет: 1) БД (координаты + UTC-строка), 2) переданные координаты (iana_tz),
        3) геокодинг + преобразование через zoneinfo.
        """
        # 1. Проверяем наличие координат и UTC-строки в БД
        lat = self.user_data.get('birth_lat')
        lng = self.user_data.get('birth_lng')
        utc_str = self.user_data.get('birth_timezone')  # теперь это UTC-строка

        if lat is not None and lng is not None and utc_str:
            try:
                utc_dt = datetime.fromisoformat(utc_str)
                if utc_dt.tzinfo is None:
                    utc_dt = utc_dt.replace(tzinfo=timezone.utc)
                if utc_dt.utcoffset() != timezone.utc.utcoffset(utc_dt):
                    raise ValueError("Not UTC")
                logger.info(f"✅ Используем координаты и UTC из БД: lat={lat}, lng={lng}, utc={utc_dt}")
                self._calculated_coords = (lat, lng)
                self._calculated_utc_str = utc_str
                self._utc_dt = utc_dt
                return lat, lng, utc_dt
            except Exception as e:
                logger.warning(f"⚠️ Не удалось распарсить UTC-строку из БД: {utc_str}, ошибка: {e}. Выполняем пересчёт.")

        # 2. Проверяем переданные координаты (если есть)
        if self._coords:
            iana_lat, iana_lng, iana_tz = self._coords
            if iana_tz in zoneinfo.available_timezones():
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

        utc_dt = self._local_to_utc(iana_tz)

        self._calculated_coords = (lat, lng)
        self._utc_dt = utc_dt
        self._calculated_utc_str = utc_dt.isoformat(timespec='seconds')

        logger.info(f"🔍 _calculated_coords установлен: {self._calculated_coords}")
        logger.info(f"🔍 _calculated_utc_str: {self._calculated_utc_str}")
        return lat, lng, utc_dt

    def _local_to_utc(self, iana_tz: str) -> datetime:
        """Преобразует локальное время рождения в UTC для указанной IANA-зоны с учётом истории."""
        try:
            local_dt = datetime.strptime(f"{self.birth_date} {self.birth_time}", "%d.%m.%Y %H:%M")
        except:
            local_dt = datetime(2000, 1, 1, 12, 0)
            logger.warning("Не удалось распарсить дату/время, используем 2000-01-01 12:00")

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
        self._subject = subject
        logger.info(f"👤 Субъект создан: {subject.name}")

        # Извлекаем данные из модели (Kerykeion v5 использует Pydantic)
        model = subject.model() if callable(subject.model) else subject.model
        data = model.model_dump()

        # --- Планеты ---
        planet_keys = ['sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter', 'saturn',
                       'uranus', 'neptune', 'pluto', 'chiron', 'true_north_lunar_node',
                       'true_south_lunar_node', 'true_lilith']
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
                            'abs_pos': obj.get('abs_pos', 0.0),
                            'house': obj.get('house', 0),
                            'retrograde': obj.get('retrograde', False),
                        })
                else:
                    if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                        planets.append({
                            'name': key.capitalize(),
                            'sign': getattr(obj, 'sign', 'unknown'),
                            'degree': getattr(obj, 'position', 0.0),
                            'abs_pos': getattr(obj, 'abs_pos', 0.0),
                            'house': getattr(obj, 'house', 0),
                            'retrograde': getattr(obj, 'retrograde', False),
                        })

        # --- Дома ---
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
                            'abs_pos': obj.get('abs_pos', 0.0),
                        })
                else:
                    if hasattr(obj, 'sign') and hasattr(obj, 'position'):
                        houses.append({
                            'number': i,
                            'sign': getattr(obj, 'sign', 'unknown'),
                            'degree': getattr(obj, 'position', 0.0),
                            'abs_pos': getattr(obj, 'abs_pos', 0.0),
                        })

        # --- Аспекты ---
        aspects = []
        try:
            # Получаем модель субъекта
            subject_model = (
                subject.model()
                if callable(subject.model)
                else subject.model
            )

            # Вызываем фабрику с моделью
            aspects_result = AspectsFactory.single_chart_aspects(
                subject_model
            )

            # Извлекаем список аспектов
            if hasattr(aspects_result, 'aspects'):
                for a in aspects_result.aspects:
                    aspects.append({
                        'p1': getattr(a, 'p1_name', 'unknown'),
                        'p2': getattr(a, 'p2_name', 'unknown'),
                        'aspect': getattr(a, 'aspect', 'unknown'),
                        'orb': getattr(a, 'orbit', getattr(a, 'orb', 0.0)),
                        'movement': getattr(a, 'aspect_movement', None),
                    })

            logger.info("✅ AspectsFactory: получено %d натальных аспектов", len(aspects))

        except Exception as e:
            logger.exception("❌ Ошибка AspectsFactory.single_chart_aspects()")
            raise  # падаем, чтобы не использовать устаревший NatalAspects

        # --- Углы ---
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

        if not asc and hasattr(self._subject, 'ascendant'):
            asc = _extract_angle(self._subject.ascendant)
        if not mc and hasattr(self._subject, 'midheaven'):
            mc = _extract_angle(self._subject.midheaven)
        if not dsc and hasattr(self._subject, 'descendant'):
            dsc = _extract_angle(self._subject.descendant)
        if not ic and hasattr(self._subject, 'imum_coeli'):
            ic = _extract_angle(self._subject.imum_coeli)

        # --- Метаданные ---
        zodiac_type = data.get('zodiac_type', 'Tropical')
        house_system = data.get('house_system', 'Placidus')
        element_dist = data.get('element_distribution')
        quality_dist = data.get('quality_distribution')

        # --- Лунная фаза ---
        lunar_phase = None
        if hasattr(self._subject, 'lunar_phase'):
            phase = self._subject.lunar_phase
            if phase:
                lunar_phase = {
                    'name': getattr(phase, 'name', None),
                    'angle': getattr(phase, 'angle', None)
                }

        self._natal_data = {
            'planets': planets,
            'houses': houses,
            'aspects': aspects,
            'angles': {'ASC': asc, 'MC': mc, 'DSC': dsc, 'IC': ic},
            'metadata': {
                'zodiac_type': zodiac_type,
                'house_system': house_system,
                'perspective': 'Geocentric'
            },
            'elements': element_dist,
            'qualities': quality_dist,
            'lunar_phase': lunar_phase,
            'utc_datetime': getattr(subject, 'iso_formatted_utc_datetime', None),
            'location': {'lat': lat, 'lng': lng}
        }
        logger.info(f"✅ Натальная карта построена: {len(planets)} планет, {len(houses)} домов, {len(aspects)} аспектов")
        return self._natal_data

    def _load_prompt_template(self) -> str:
        """Загружает шаблон промпта из файла prompts/prompt_astrology.txt"""
        base = Path(__file__).parent.parent.parent / 'prompts' / 'prompt_astrology.txt'
        try:
            with open(base, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            logger.error(f"Шаблон {base} не найден")
            return ""

    def _build_prompt(self) -> str:
        """
        Формирует промпт для LLM:
        1. Загружает шаблон из prompts/prompt_astrology.txt
        2. Вставляет языковую инструкцию
        3. Вставляет имя пользователя
        4. Вставляет натальный контекст через {natal_context}
        """
        self._build_natal_chart()

        if not self._subject:
            raise RuntimeError("Subject не создан, невозможно построить контекст")

        # Строим натальный контекст
        builder = NatalContextBuilder(self._subject, lang=self.lang)
        natal_context = builder.build()

        # Загружаем шаблон
        template = self._load_prompt_template()
        if not template:
            return "❌ Шаблон промпта не найден."

        # Языковая инструкция
        if self.lang == 'en':
            language_instruction = "IMPORTANT: Respond in English only."
        else:
            language_instruction = "ВАЖНО: Отвечай только на русском языке."

        # Подставляем в шаблон
        prompt = template.replace('{language_instruction}', language_instruction)
        prompt = prompt.replace('{natal_context}', natal_context)
        prompt = prompt.replace('{name}', self.name)

        return prompt

    async def generate(self, save_to_db: bool = True) -> str:
        """
        Основной метод: строит карту, сохраняет координаты (если save_to_db=True),
        формирует промпт и возвращает ответ Gemini.
        """
        self._build_natal_chart()

        # Сохраняем координаты, только если явно разрешено
        if save_to_db and self._calculated_coords and self.telegram_id:
            lat, lng = self._calculated_coords
            utc_str = self._calculated_utc_str
            if not utc_str and self._utc_dt:
                utc_str = self._utc_dt.isoformat(timespec='seconds')
            if utc_str:
                logger.info(
                    f"💾 Сохраняем координаты и UTC в БД: lat={lat}, lng={lng}, utc={utc_str} для {self.telegram_id}")
                result = await save_user_coords(self.telegram_id, lat, lng, utc_str)
                if result:
                    logger.info(f"✅ Координаты и UTC сохранены в БД для {self.telegram_id}")
                else:
                    logger.error(f"❌ Ошибка сохранения координат для {self.telegram_id}")
            else:
                logger.warning("⚠️ Нет UTC-строки для сохранения")
        else:
            logger.info("ℹ️ Сохранение координат в БД отключено (save_to_db=False)")

        prompt = self._build_prompt()

        # 4. Режим эмуляции или реальный запрос
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
        data = self._build_natal_chart()
        loc = data.get('location', {})
        angles = data.get('angles', {})
        utc = data.get('utc_datetime', 'не известно')

        def format_angle(angle_data):
            if angle_data and isinstance(angle_data, dict):
                pos = angle_data.get('position', 0.0)
                return f"{pos:.2f}°"
            return "—"

        angles_str = (
            f"ASC: {format_angle(angles.get('ASC'))}, "
            f"MC: {format_angle(angles.get('MC'))}, "
            f"DSC: {format_angle(angles.get('DSC'))}, "
            f"IC: {format_angle(angles.get('IC'))}"
        )

        return {
            'name': self.name,
            'gender': 'Мужчина' if self.gender == 'M' else 'Женщина',
            'birth_date': self.birth_date or 'не указана',
            'birth_time': self.birth_time or 'не указано',
            'birth_place': self.birth_place or 'не указано',
            'lat': f"{loc.get('lat', 0.0):.4f}",
            'lng': f"{loc.get('lng', 0.0):.4f}",
            'timezone': 'UTC',
            'utc_datetime': utc,
            'angles': angles_str
        }

    def get_natal_context(self, lang: str) -> str:
        """Возвращает натальный контекст для администратора без пересчёта карты."""
        if not self._subject:
            return "Натальная карта не построена."
        from bot.calculators.natal_context_builder import NatalContextBuilder
        builder = NatalContextBuilder(self._subject, lang=lang)
        return builder.build()