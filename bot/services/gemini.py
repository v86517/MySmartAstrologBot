import os
import requests
import json
import logging
import traceback
from typing import Optional, Dict, Any
from datetime import datetime

from bot.calculators.base_calculator import BaseCalculator
from bot.calculators.natal_calculator import NatalCalculator
from bot.db import get_user_language

DEBUG_PRINT_PROMPT = False
logger = logging.getLogger(__name__)


class GeminiService:
    def __init__(self):
        self.api_key = os.getenv('GEMINI_API_KEY')
        if not self.api_key:
            raise ValueError("❌ GEMINI_API_KEY не найден в .env файле!")
        self.base_url = "https://proxy.gen-api.ru/v1/chat/completions"
        self.model = "gemini-3-1-flash-lite"
        self.prompts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'prompts')
        self._base_calc = BaseCalculator()
        self.user_data = None
        self.lang = 'ru'

    def _load_prompt_template(self, filename: str) -> str:
        filepath = os.path.join(self.prompts_dir, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            logger.error(f"Файл {filename} не найден")
            return None

    def _replace_placeholders(self, template: str, data: Dict[str, str]) -> str:
        result = template
        for key, value in data.items():
            result = result.replace(f'{{{key}}}', str(value))
        return result

    def _add_language_instruction(self, prompt: str, lang: str) -> str:
        if lang == 'en':
            instruction = ("\n\n==================================================\n"
                           "LANGUAGE INSTRUCTION:\n"
                           "Please respond in English only. All your output must be in English.\n"
                           "==================================================")
        else:
            instruction = ("\n\n==================================================\n"
                           "ЯЗЫКОВАЯ ИНСТРУКЦИЯ:\n"
                           "Отвечай только на русском языке. Весь твой ответ должен быть на русском.\n"
                           "==================================================")
        return prompt + instruction

    def _send_prompt(self, prompt: str, lang: str = 'ru') -> str:
        if DEBUG_PRINT_PROMPT:
            logger.info("=" * 80)
            logger.info("📤 ОТПРАВЛЯЕМЫЙ ПРОМПТ (полный текст):")
            logger.info("=" * 80)
            logger.info(prompt)
            logger.info("=" * 80)
            logger.info("📤 КОНЕЦ ПРОМПТА")
            logger.info("=" * 80)
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Ты - профессиональный астролог с глубокими знаниями."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 4000
        }
        try:
            response = requests.post(self.base_url, headers=headers, json=payload, timeout=90)
            if response.status_code == 200:
                data = response.json()
                if 'choices' in data and data['choices']:
                    return data['choices'][0]['message']['content']
                else:
                    return "❌ Не удалось получить ответ от ИИ."
            else:
                return f"❌ Ошибка API: {response.status_code}"
        except Exception as e:
            return f"❌ Ошибка: {str(e)}"

    # ---- СТАРЫЕ МЕТОДЫ (сохранены для обратной совместимости) ----
    def generate_from_prompt(self, prompt_data: Dict[str, Any], prompt_file: str, lang: str = 'ru') -> str:
        template = self._load_prompt_template(prompt_file)
        if not template:
            return f"❌ Шаблон {prompt_file} не найден."
        prompt = self._replace_placeholders(template, prompt_data)
        return self._send_prompt(prompt, lang)

    def generate_horoscope(self, user_data: Dict[str, Any], lang: str = 'ru') -> str:
        from bot.calculators.transit_horoscope_calculator import TransitHoroscopeCalculator
        calculator = TransitHoroscopeCalculator(user_data, lang)
        prompt_data = calculator.calculate()
        if lang == 'en':
            prompt_data['language_instruction'] = "IMPORTANT: Respond in English only. All your forecast must be in English."
        else:
            prompt_data['language_instruction'] = "ВАЖНО: Отвечай только на русском языке. Весь прогноз должен быть на русском."
        return self.generate_from_prompt(prompt_data, 'prompt_horoscope.txt', lang)

    def generate_compatibility_from_prompt(self, person1: Dict[str, Any], person2: Dict[str, Any], lang: str = 'ru') -> str:
        from bot.calculators.compatibility_calculator import CompatibilityCalculator
        calculator = CompatibilityCalculator(person1, person2)
        prompt_data = calculator.get_prompt_data()
        if lang == 'en':
            prompt_data['language_instruction'] = "IMPORTANT: Respond in English only. All your analysis must be in English."
        else:
            prompt_data['language_instruction'] = "ВАЖНО: Отвечай только на русском языке. Весь анализ должен быть на русском."
        return self.generate_from_prompt(prompt_data, 'prompt_connect.txt', lang)

    def generate_numerology(self, user_data: Dict[str, Any], lang: str = 'ru') -> str:
        calc = NatalCalculator(
            birth_date=user_data.get('birth_date'),
            name=user_data.get('name'),
            birth_time=user_data.get('birth_time'),
            birth_place=user_data.get('birth_place'),
            gender=user_data.get('gender')
        )
        matrix = calc.calculate()
        prompt_data = matrix.copy()
        prompt_data['name'] = user_data.get('name', '')
        prompt_data['gender_display'] = "Мужчина" if user_data.get('gender') == 'M' else "Женщина"
        prompt_data['birth_date'] = user_data.get('birth_date', '')
        prompt_data['birth_time'] = user_data.get('birth_time', 'не указано')
        prompt_data['birth_place'] = user_data.get('birth_place', 'не указано')
        prompt_data['pronoun'] = "он" if user_data.get('gender') == 'M' else "она"
        prompt_data['possessive'] = "его" if user_data.get('gender') == 'M' else "её"
        name = user_data.get('name', '')
        prompt_data['expression_number'] = self._base_calc.calculate_expression_number(name) or "не рассчитано"
        prompt_data['soul_urge_number'] = self._base_calc.calculate_soul_urge_number(name) or "не рассчитано"
        prompt_data['personality_number'] = self._base_calc.calculate_personality_number(name) or "не рассчитано"
        target_date = datetime.now().strftime('%d.%m.%Y')
        birth_date = user_data.get('birth_date')
        if birth_date:
            prompt_data['personal_year'] = self._base_calc.calculate_personal_year(birth_date, target_date)
            prompt_data['personal_month'] = self._base_calc.calculate_personal_month(birth_date, target_date)
            prompt_data['personal_day'] = self._base_calc.calculate_personal_day(birth_date, target_date)
        else:
            prompt_data['personal_year'] = prompt_data['personal_month'] = prompt_data['personal_day'] = "не рассчитано"
        if lang == 'en':
            prompt_data['language_instruction'] = "IMPORTANT: Respond in English only. All your analysis must be in English."
        else:
            prompt_data['language_instruction'] = "ВАЖНО: Отвечай только на русском языке. Весь анализ должен быть на русском."
        return self.generate_from_prompt(prompt_data, 'prompt_numerology.txt', lang)

    def generate_astrology(self, user_data: Dict[str, Any], lang: str = 'ru') -> str:
        from bot.calculators.astrology_calculator import AstrologyCalculator
        calculator = AstrologyCalculator(user_data)
        prompt = calculator.build_prompt(lang)
        return self._send_prompt(prompt, lang)

    def send_raw_prompt(self, prompt: str, lang: str = 'ru') -> str:
        return self._send_prompt(prompt, lang)

    async def generate_astrology_v2(self, user_data: Dict[str, Any], lang: str = 'ru') -> str:
        from bot.db import get_emulation_mode
        user_id = user_data.get('telegram_id') or user_data.get('user_id')
        if user_id:
            emulation = await get_emulation_mode(user_id)
            if emulation:
                from bot.calculators.astrology_data_builder import AstrologyDataBuilder
                builder = AstrologyDataBuilder(user_data, lang, include_transits=False)
                json_data = builder.build()
                prompt = self._build_astrology_prompt(json_data, lang)
                return f"🔍 РЕЖИМ ЭМУЛЯЦИИ (промпт не отправлен в нейросеть):\n\n{prompt}"
        self.user_data = user_data
        self.lang = lang
        try:
            from bot.calculators.astrology_data_builder import AstrologyDataBuilder
            builder = AstrologyDataBuilder(user_data, lang, include_transits=False)
            json_data = builder.build()
            prompt = self._build_astrology_prompt(json_data, lang)
            return self._send_prompt(prompt, lang)
        except Exception as e:
            logger.error(f"❌ Ошибка в generate_astrology_v2: {e}")
            logger.error(traceback.format_exc())
            return f"❌ Произошла ошибка при построении натальной карты: {str(e)}"

    # ---- НОВЫЕ МЕТОДЫ ДЛЯ ТРАНЗИТОВ И СИНАСТРИИ (по ТЗ) ----

    # В bot/services/gemini.py

    async def generate_horoscope_with_data(self, user_id: int, user_data: Dict[str, Any],
                                           natal_data: Dict[str, Any], transit_data: Dict[str, Any],
                                           lang: str, period: str = 'today',
                                           display_date: str = None, start_utc=None, end_utc=None) -> str:
        from bot.db import get_emulation_mode
        emulation = await get_emulation_mode(user_id)
        template = self._load_prompt_template('prompt_horoscope_v2.txt')
        if not template:
            logger.error("Шаблон prompt_horoscope_v2.txt не найден, используем старый метод")
            return self.generate_horoscope(user_data, lang)

        replacements = self._prepare_horoscope_replacements(
            user_data, natal_data, transit_data, lang, period=period, display_date=display_date, start_utc=start_utc, end_utc=end_utc)
        if lang == 'en':
            replacements[
                'language_instruction'] = "IMPORTANT: Respond in English only. All your output must be in English."
        else:
            replacements[
                'language_instruction'] = "ВАЖНО: Отвечай только на русском языке. Весь твой ответ должен быть на русском."

        prompt = self._replace_placeholders(template, replacements)
        if emulation:
            return f"🔍 РЕЖИМ ЭМУЛЯЦИИ (промпт не отправлен в нейросеть):\n\n{prompt}"
        return self._send_prompt(prompt, lang)

    async def generate_compatibility_with_data(self, user_id: int, user_data_a: Dict[str, Any],
                                               user_data_b: Dict[str, Any],
                                               natal1: Dict[str, Any], natal2: Dict[str, Any],
                                               synastry_data: Dict[str, Any],
                                               lang: str) -> str:
        """Генерирует анализ совместимости с поддержкой эмуляции."""
        from bot.db import get_emulation_mode
        emulation = await get_emulation_mode(user_id)
        template = self._load_prompt_template('prompt_connect_v2.txt')
        if not template:
            logger.error("Шаблон prompt_connect_v2.txt не найден, используем старый метод")
            return self.generate_compatibility_from_prompt(user_data_a, user_data_b, lang)

        replacements = self._prepare_compatibility_replacements(user_data_a, user_data_b,
                                                                natal1, natal2, synastry_data, lang)
        if lang == 'en':
            replacements[
                'language_instruction'] = "IMPORTANT: Respond in English only. All your output must be in English."
        else:
            replacements[
                'language_instruction'] = "ВАЖНО: Отвечай только на русском языке. Весь твой ответ должен быть на русском."

        prompt = self._replace_placeholders(template, replacements)
        if emulation:
            return f"🔍 РЕЖИМ ЭМУЛЯЦИИ (промпт не отправлен в нейросеть):\n\n{prompt}"
        return self._send_prompt(prompt, lang)

    # ---- ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ДЛЯ ПОДГОТОВКИ ЗАМЕН ----

    def _prepare_horoscope_replacements(self, user_data: Dict, natal_data: Dict, transit_data: Dict,
                                        lang: str, period: str = 'today',
                                        display_date: str = None, start_utc=None, end_utc=None) -> Dict[str, str]:
        from datetime import datetime
        from bot.utils.zodiac import get_zodiac_sign_localized

        # Базовые данные
        name = user_data.get('name', 'Пользователь')
        gender = user_data.get('gender', 'M')
        if lang == 'ru':
            gender_text = "Мужской" if gender == 'M' else "Женский" if gender == 'F' else "Не указан"
        else:
            gender_text = "Male" if gender == 'M' else "Female" if gender == 'F' else "Not specified"
        birth_date = user_data.get('birth_date', 'не указана')
        birth_time = user_data.get('birth_time', 'не указано')
        birth_place = user_data.get('birth_place', 'не указано')

        # Формируем строку периода
        if period == 'today':
            if start_utc and end_utc:
                period_str = f"с {start_utc.strftime('%Y-%m-%d %H:%M')} по {end_utc.strftime('%Y-%m-%d %H:%M')} UTC"
            else:
                period_str = f"на {display_date or datetime.now().strftime('%d.%m.%Y')}"
        elif period == 'month':
            if start_utc and end_utc:
                period_str = f"с {start_utc.strftime('%Y-%m-%d')} по {end_utc.strftime('%Y-%m-%d')} UTC"
            else:
                period_str = "на текущий месяц"
        else:  # year
            if start_utc and end_utc:
                period_str = f"с {start_utc.strftime('%Y-%m-%d')} по {end_utc.strftime('%Y-%m-%d')} UTC"
            else:
                period_str = "на текущий год"

        # Натальные секции
        natal = natal_data.get('natal', {})
        planets = natal.get('planets', [])
        # Формируем таблицу планет (без колонки Вес, можно убрать)
        planets_table = self._format_planets_table(planets, include_weight=False)  # добавим параметр
        angles = natal.get('angles', {})
        angles_str = f"ASC: {angles.get('ASC', 0):.2f}°, MC: {angles.get('MC', 0):.2f}°, DSC: {angles.get('DSC', 0):.2f}°, IC: {angles.get('IC', 0):.2f}°"

        # Натальные аспекты с орбисом <= 3°
        aspects = natal.get('aspects', [])
        natal_aspects_filtered = [a for a in aspects if a.get('orb', 10) <= 3.0]
        natal_aspects_str = self._format_aspects(natal_aspects_filtered)

        # Транзитные секции (получаем из transit_data, но фильтруем по дате)
        transit_planets = transit_data.get('transit_planets', [])
        transit_planets_str = self._format_transit_planets(transit_planets)

        # Фильтруем транзитные аспекты по дате, если есть start_utc/end_utc
        transit_aspects = transit_data.get('transit_aspects', [])
        if start_utc and end_utc:
            filtered_aspects = []
            for a in transit_aspects:
                exact_date = a.get('exact_date')
                if exact_date:
                    try:
                        dt = datetime.strptime(exact_date, '%Y-%m-%d')
                        if start_utc.date() <= dt.date() <= end_utc.date():
                            filtered_aspects.append(a)
                    except:
                        pass
                else:
                    # Если точной даты нет, можно включить, если аспект имеет маленький орбис, но для фильтрации по периоду лучше не включать
                    # Для сегодня можно включить все, для месяца/года – лучше не включать без даты.
                    # Для простоты включим все (можно настроить позже)
                    filtered_aspects.append(a)
            transit_aspects = filtered_aspects
        transit_aspects_str = self._format_transit_aspects(transit_aspects)

        # Аспекты к углам
        transit_angle_aspects = transit_data.get('transit_angle_aspects', [])
        if start_utc and end_utc:
            filtered_angle = []
            for a in transit_angle_aspects:
                exact_date = a.get('exact_date')
                if exact_date:
                    try:
                        dt = datetime.strptime(exact_date, '%Y-%m-%d')
                        if start_utc.date() <= dt.date() <= end_utc.date():
                            filtered_angle.append(a)
                    except:
                        pass
                else:
                    filtered_angle.append(a)
            transit_angle_aspects = filtered_angle
        transit_angle_aspects_str = self._format_transit_angle_aspects(transit_angle_aspects)

        # Активные периоды (фильтруем по пересечению)
        active_periods = transit_data.get('active_periods', [])
        if start_utc and end_utc:
            filtered_periods = []
            for p in active_periods:
                try:
                    start_dt = datetime.strptime(p['start'], '%Y-%m-%d')
                    end_dt = datetime.strptime(p['end'], '%Y-%m-%d')
                    # Проверяем пересечение
                    if not (end_dt < start_utc or start_dt > end_utc):
                        filtered_periods.append(p)
                except:
                    pass
            active_periods = filtered_periods
        active_periods_str = self._format_active_periods(active_periods)

        # Убираем ненужные разделы: метаданные, управители, темы, проходы, ингрессии, станции, timeline, сводные темы.

        replacements = {
            "person_name": name,
            "person_gender": gender_text,
            "birth_date": birth_date,
            "birth_time": birth_time,
            "birth_place": birth_place,
            "period": period_str,
            "planets_table": planets_table,
            "angles": angles_str,
            "natal_aspects_list": natal_aspects_str,
            "transit_planets": transit_planets_str,
            "transit_aspects_list": transit_aspects_str,
            "transit_angle_aspects_list": transit_angle_aspects_str,
            "transit_passes": self._format_transit_passes(transit_data.get('transit_passes', [])),
            "transit_ingresses": self._format_transit_ingresses(transit_data.get('transit_ingresses', [])),
            "transit_stations": self._format_transit_stations(transit_data.get('transit_stations', [])),
            "active_periods": self._format_active_periods(transit_data.get('active_periods', [])),
            "language_instruction": "",  # добавим позже отдельно
        }
        return replacements

    def _prepare_compatibility_replacements(self, user_data_a: Dict, user_data_b: Dict,
                                            natal1: Dict, natal2: Dict, synastry_data: Dict, lang: str) -> Dict[
        str, str]:
        """Подготавливает замены для промпта совместимости."""
        # Базовые данные людей
        name_a = user_data_a.get('name', 'Человек A')
        name_b = user_data_b.get('name', 'Человек B')

        # Натальные данные человека A
        natal_a = natal1.get('natal', {})
        planets_a = self._format_planets_table(natal_a.get('planets', []))
        cusps_a = self._format_cusps(natal_a.get('houses', []))
        house_rulers_a = self._format_house_rulers(natal_a.get('house_rulers', []))
        aspects_a = self._format_aspects(natal_a.get('aspects', []))
        themes_a = self._format_themes(natal1.get('themes', {}))  # <-- ИСПРАВЛЕНО

        # Натальные данные человека B
        natal_b = natal2.get('natal', {})
        planets_b = self._format_planets_table(natal_b.get('planets', []))
        cusps_b = self._format_cusps(natal_b.get('houses', []))
        house_rulers_b = self._format_house_rulers(natal_b.get('house_rulers', []))
        aspects_b = self._format_aspects(natal_b.get('aspects', []))
        themes_b = self._format_themes(natal2.get('themes', {}))  # <-- ИСПРАВЛЕНО

        # Синастрические данные
        syn_aspects_a_to_b = self._format_synastry_aspects(synastry_data.get('synastry_aspects_a_to_b', []))
        syn_aspects_b_to_a = self._format_synastry_aspects(synastry_data.get('synastry_aspects_b_to_a', []))
        planets_in_houses = self._format_planets_in_houses(synastry_data.get('planets_in_houses', {}))
        syn_angle_aspects = self._format_synastry_angle_aspects(synastry_data.get('synastry_angle_aspects', []))
        mutual_receptions = self._format_mutual_receptions(synastry_data.get('mutual_receptions', []))
        comp_themes = self._format_synastry_themes(synastry_data.get('compatibility_themes', {}))

        return {
            "person_a_name": name_a,
            "person_b_name": name_b,
            "person_a_planets": planets_a,
            "person_a_cusps": cusps_a,
            "person_a_house_rulers": house_rulers_a,
            "person_a_aspects": aspects_a,
            "person_a_themes": themes_a,
            "person_b_planets": planets_b,
            "person_b_cusps": cusps_b,
            "person_b_house_rulers": house_rulers_b,
            "person_b_aspects": aspects_b,
            "person_b_themes": themes_b,
            "synastry_aspects_a_to_b": syn_aspects_a_to_b,
            "synastry_aspects_b_to_a": syn_aspects_b_to_a,
            "planets_in_houses": planets_in_houses,
            "synastry_angle_aspects": syn_angle_aspects,
            "mutual_receptions": mutual_receptions,
            "compatibility_themes": comp_themes,
        }

    # ---- ФОРМАТТЕРЫ ДЛЯ РАЗЛИЧНЫХ СЕКЦИЙ (для промптов) ----

    def _format_planets_table(self, planets: list, include_weight: bool = True) -> str:
        if not planets:
            return "Нет данных о планетах."
        lines = []
        header = "| Планета     | Знак      | Градус | Дом | Ретр | Скорость |"
        if include_weight:
            header += " Вес |"
            lines.append(header)
            lines.append("|-------------|-----------|--------|-----|------|----------|-----|")
            for p in planets:
                name = p.get('name_local', p.get('name', ''))
                sign = p.get('sign', '')
                degree = p.get('degree', 0.0)
                house = p.get('house', 0)
                retro = p.get('retrograde', False)
                speed = p.get('speed', 0.0)
                weight = p.get('weight', 0)
                lines.append(
                    f"| {name:12} | {sign:10} | {degree:6.2f}° | {house:3} | {'Да' if retro else 'Нет':3} | {speed:6.3f} | {weight:3} |")
        else:
            lines.append(header)
            lines.append("|-------------|-----------|--------|-----|------|----------|")
            for p in planets:
                name = p.get('name_local', p.get('name', ''))
                sign = p.get('sign', '')
                degree = p.get('degree', 0.0)
                house = p.get('house', 0)
                retro = p.get('retrograde', False)
                speed = p.get('speed', 0.0)
                lines.append(
                    f"| {name:12} | {sign:10} | {degree:6.2f}° | {house:3} | {'Да' if retro else 'Нет':3} | {speed:6.3f} |")
        return "\n".join(lines)

    def _format_cusps(self, houses: list) -> str:
        if not houses:
            return "Нет данных о куспидах."
        lines = []
        for h in houses:
            number = h.get('number', 0)
            sign = h.get('cusp', '')
            degree = h.get('cusp_degree', 0.0)
            lines.append(f"Дом {number}: {sign} {degree:.2f}°")
        return "\n".join(lines)

    def _format_house_rulers(self, rulers: list) -> str:
        if not rulers:
            return "Нет данных об управителях."
        lines = []
        for r in rulers:
            house = r.get('house', 0)
            cusp = r.get('cusp', '')
            ruler = r.get('ruler', '')
            ruler_sign = r.get('ruler_sign', '')
            ruler_house = r.get('ruler_house', 0)
            retro = r.get('ruler_retrograde', False)
            lines.append(
                f"Дом {house}: {cusp} -> управитель {ruler} (в {ruler_sign}, {ruler_house} доме{' ℞' if retro else ''})"
            )
        return "\n".join(lines)

    def _format_aspects(self, aspects: list) -> str:
        if not aspects:
            return "Нет аспектов."
        lines = []
        for a in aspects:
            p1 = a.get('p1_name_local', a.get('p1', ''))
            p2 = a.get('p2_name_local', a.get('p2', ''))
            aspect = a.get('aspect_local', a.get('aspect', ''))
            orb = a.get('orb', 0.0)
            weight = a.get('weight', 0)
            lines.append(f"{p1} {aspect} {p2} (орб: {orb:.2f}°, вес: {weight:.2f})")
        return "\n".join(lines)

    def _format_themes(self, themes: dict) -> str:
        if not themes:
            return "Нет тем."
        lines = []
        for theme, data in themes.items():
            score = data.get('score', 0)
            conf = data.get('confidence', 0)
            count = data.get('evidence_count', 0)
            repeating = data.get('repeating_theme', False)
            lines.append(
                f"Тема: {theme} (score: {score:.2f}, conf: {conf:.2f}, док-в: {count}, повторяется: {'да' if repeating else 'нет'})"
            )
            for ev in data.get('evidence', [])[:3]:
                lines.append(f"  - {ev.get('type')}: {ev.get('source')} ({ev.get('weight', 0)})")
        return "\n".join(lines)

    def _format_transit_planets(self, planets: list) -> str:
        if not planets:
            return "Нет транзитных планет."
        lines = []
        for p in planets:
            name = p.get('name', '')
            sign = p.get('sign', '')
            degree = p.get('degree', 0.0)
            house = p.get('house', 0)
            retro = p.get('retrograde', False)
            speed = p.get('speed', 0.0)
            lines.append(
                f"{name}: {sign} {degree:.2f}° в {house} доме, скорость: {speed:.3f}/день, {'ретроградный' if retro else 'директный'}"
            )
        return "\n".join(lines)

    def _format_transit_aspects(self, aspects: list) -> str:
        if not aspects:
            return "Нет транзитных аспектов."
        lines = []
        for a in aspects:
            transit = a.get('transit_planet', '')
            natal = a.get('natal_planet', '')
            aspect = a.get('aspect', '')
            orb = a.get('orb', 0.0)
            phase = a.get('phase', '')
            exact = a.get('exact_date', '')
            score = a.get('score', 0)
            conf = a.get('confidence', 0)
            themes = ', '.join(a.get('themes', []))
            lines.append(
                f"Transit {transit} → Natal {natal}: {aspect} (орб: {orb:.2f}°, фаза: {phase}, точная дата: {exact or 'не определена'}, score: {score:.2f}, conf: {conf:.2f}, темы: {themes})"
            )
        return "\n".join(lines)

    def _format_transit_angle_aspects(self, aspects: list) -> str:
        if not aspects:
            return "Нет транзитных аспектов к углам."
        lines = []
        for a in aspects:
            transit = a.get('transit_planet', '')
            angle = a.get('angle', '')
            aspect = a.get('aspect', '')
            orb = a.get('orb', 0.0)
            phase = a.get('phase', '')
            exact = a.get('exact_date', '')
            score = a.get('score', 0)
            lines.append(
                f"Transit {transit} → {angle}: {aspect} (орб: {orb:.2f}°, фаза: {phase}, точная дата: {exact or 'не определена'}, score: {score:.2f})"
            )
        return "\n".join(lines)

    def _format_transit_passes(self, passes: list) -> str:
        if not passes:
            return "Нет проходов медленных планет в указанный период."
        lines = []
        for item in passes:
            lines.append(f"{item['transit_planet']} {item['aspect']} {item['natal_planet']}:")
            for p in item['passes']:
                lines.append(f"  - {p['date']} ({p.get('direction', 'direct')})")
        return "\n".join(lines)

    def _format_transit_ingresses(self, ingresses: list) -> str:
        if not ingresses:
            return "Нет ингрессий в указанный период."
        lines = []
        for i in ingresses:
            planet = i.get('planet', '')
            typ = i.get('type', '')
            from_val = i.get('from', '')
            to_val = i.get('to', '')
            date = i.get('date', '')
            if typ == 'sign':
                # Переводим номер знака в название
                sign_names = ['Овен', 'Телец', 'Близнецы', 'Рак', 'Лев', 'Дева', 'Весы', 'Скорпион', 'Стрелец',
                              'Козерог', 'Водолей', 'Рыбы']
                from_sign = sign_names[from_val] if from_val < len(sign_names) else str(from_val)
                to_sign = sign_names[to_val] if to_val < len(sign_names) else str(to_val)
                lines.append(f"{planet}: вход в знак {to_sign} (~{date})")
            else:
                lines.append(f"{planet}: смена дома с {from_val} на {to_val} (~{date})")
        return "\n".join(lines)

    def _format_transit_stations(self, stations: list) -> str:
        if not stations:
            return "Нет стационарных планет в указанный период."
        lines = []
        for s in stations:
            planet = s.get('planet', '')
            sign = s.get('sign', '')
            house = s.get('house', 0)
            lines.append(f"{planet}: stationary (в {sign}, {house} доме)")
        return "\n".join(lines)

    def _format_active_periods(self, periods: list) -> str:
        if not periods:
            return "Нет активных периодов."
        lines = []
        for p in periods:
            start = p.get('start', '')
            end = p.get('end', '')
            theme = p.get('theme', '')
            intensity = p.get('intensity', 0)
            conf = p.get('confidence', 0)
            lines.append(f"{start} — {end}: {theme} (интенсивность: {intensity:.1f}, conf: {conf:.2f})")
            for ev in p.get('evidence', [])[:3]:
                lines.append(
                    f"  - {ev.get('transit')} {ev.get('aspect')} {ev.get('natal')} (орб: {ev.get('orb')}, фаза: {ev.get('phase')})"
                )
        return "\n".join(lines)

    def _format_transit_themes(self, themes: dict) -> str:
        if not themes:
            return "Нет тем транзитов."
        lines = []
        for theme, data in themes.items():
            score = data.get('score', 0)
            conf = data.get('confidence', 0)
            count = data.get('count', 0)
            lines.append(f"Тема: {theme} (score: {score:.2f}, conf: {conf:.2f}, аспектов: {count})")
            for ev in data.get('evidence', [])[:3]:
                lines.append(f"  - {ev.get('source')} (score: {ev.get('score')})")
        return "\n".join(lines)

    def _format_synastry_aspects(self, aspects: list) -> str:
        if not aspects:
            return "Нет синастрических аспектов."
        lines = []
        for a in aspects:
            p_a = a.get('person_a_planet', '')
            p_b = a.get('person_b_planet', '')
            aspect = a.get('aspect', '')
            orb = a.get('orb', 0.0)
            score = a.get('score', 0)
            conf = a.get('confidence', 0)
            themes = ', '.join(a.get('themes', []))
            lines.append(
                f"{p_a} → {p_b}: {aspect} (орб: {orb:.2f}°, score: {score:.2f}, conf: {conf:.2f}, темы: {themes})"
            )
        return "\n".join(lines)

    def _format_planets_in_houses(self, houses_data: dict) -> str:
        if not houses_data:
            return "Нет данных о планетах в домах."
        lines = []
        a_in_b = houses_data.get('a_in_b_houses', [])
        b_in_a = houses_data.get('b_in_a_houses', [])
        if a_in_b:
            lines.append("Планеты A в домах B:")
            for item in a_in_b:
                lines.append(f"  {item.get('planet')} в {item.get('house')} доме")
        if b_in_a:
            lines.append("Планеты B в домах A:")
            for item in b_in_a:
                lines.append(f"  {item.get('planet')} в {item.get('house')} доме")
        return "\n".join(lines)

    def _format_synastry_angle_aspects(self, aspects: list) -> str:
        if not aspects:
            return "Нет синастрических аспектов к углам."
        lines = []
        for a in aspects:
            planet = a.get('person_planet', '')
            angle = a.get('other_angle', '')
            aspect = a.get('aspect', '')
            orb = a.get('orb', 0.0)
            score = a.get('score', 0)
            lines.append(f"{planet} → {angle}: {aspect} (орб: {orb:.2f}°, score: {score:.2f})")
        return "\n".join(lines)

    def _format_mutual_receptions(self, receptions: list) -> str:
        if not receptions:
            return "Нет взаимных рецепций."
        lines = []
        for r in receptions:
            p_a = r.get('planet_a', '')
            p_b = r.get('planet_b', '')
            strength = r.get('strength', 0)
            lines.append(f"{p_a} ↔ {p_b} (сила: {strength:.1f})")
        return "\n".join(lines)

    def _format_synastry_themes(self, themes: dict) -> str:
        if not themes:
            return "Нет тем совместимости."
        lines = []
        for theme, data in themes.items():
            score = data.get('score', 0)
            conf = data.get('confidence', 0)
            count = data.get('count', 0)
            lines.append(f"Тема: {theme} (score: {score:.2f}, conf: {conf:.2f}, док-в: {count})")
            for ev in data.get('evidence', [])[:3]:
                lines.append(f"  - {ev.get('source')}")
        return "\n".join(lines)

    # ---- ОСТАЛЬНЫЕ МЕТОДЫ (астрология и пр.) ----
    def _build_astrology_prompt(self, json_data: Dict[str, Any], lang: str) -> str:
        template = self._load_prompt_template('prompt_astrology_v2.txt')
        if not template:
            logger.warning("Шаблон prompt_astrology_v2.txt не найден, используется fallback")
            return self._build_fallback_prompt(json_data, 'astrology')
        replacements = self._prepare_astrology_replacements(json_data, lang)
        prompt = template
        for key, value in replacements.items():
            prompt = prompt.replace(f'{{{key}}}', str(value))
        if lang == 'en':
            language_instruction = "IMPORTANT: Respond in English only. All your analysis must be in English."
        else:
            language_instruction = "ВАЖНО: Отвечай только на русском языке. Весь анализ должен быть на русском."
        prompt = prompt.replace('{language_instruction}', language_instruction)
        return prompt

    def get_astrology_display_data(self, user_data: Dict[str, Any], lang: str, is_admin: bool = False) -> Dict[
        str, str]:
        """
        Возвращает basic и full данные для отображения пользователю и администратору.
        basic — всегда, full — только для администратора.
        """
        import logging
        import pytz
        from datetime import datetime
        from bot.locales import TEXTS
        from bot.calculators.astrology_data_builder import AstrologyDataBuilder

        logger = logging.getLogger(__name__)
        try:
            texts = TEXTS.get(lang, TEXTS['ru'])

            # Создаём билдер БЕЗ ТРАНЗИТОВ (для натальной карты они не нужны)
            builder = AstrologyDataBuilder(user_data, lang, include_transits=False)
            data = builder.build()
            natal = data.get('natal', {})
            planets = natal.get('planets', [])
            houses = natal.get('houses', [])
            angles = natal.get('angles', {})
            metadata = data.get('metadata', {})
            location = metadata.get('location', {})
            lat = location.get('lat', 0.0)
            lng = location.get('lng', 0.0)
            timezone = metadata.get('timezone', '')
            utc_datetime = metadata.get('utc_datetime', '')
            birth_date = user_data.get('birth_date', '')
            birth_time = user_data.get('birth_time', '00:00')
            local_time = f"{birth_date} {birth_time}" if birth_date else 'Unknown'

            # Солнце, Луна, Асцендент
            sun = next((p for p in planets if p.get('name') == 'Sun'), {})
            moon = next((p for p in planets if p.get('name') == 'Moon'), {})
            asc_deg = angles.get('ASC', 0.0)
            asc_sign = houses[0].get('sign', 'Unknown') if houses else 'Unknown'
            if asc_sign == 'Unknown' and asc_deg != 0.0:
                sign_degrees = [
                    (0, 'Ari'), (30, 'Tau'), (60, 'Gem'), (90, 'Can'),
                    (120, 'Leo'), (150, 'Vir'), (180, 'Lib'), (210, 'Sco'),
                    (240, 'Sag'), (270, 'Cap'), (300, 'Aqu'), (330, 'Pis')
                ]
                for deg, sign in sign_degrees:
                    if asc_deg >= deg and asc_deg < deg + 30:
                        asc_sign = sign
                        break
                if asc_sign == 'Unknown':
                    asc_sign = 'Unknown'

            gender = user_data.get('gender', 'M')
            if lang == 'en':
                gender_display = "Male" if gender == 'M' else "Female" if gender == 'F' else "Not specified"
            else:
                gender_display = "Мужской" if gender == 'M' else "Женский" if gender == 'F' else "Не указан"

            # Формируем basic параметры
            if lang == 'en':
                basic_params = (
                    f"🌙 Your astrological analysis\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{texts.get('astro_name', '👤 Name')}: {user_data.get('name', '')}\n"
                    f"{texts.get('astro_gender', '⚥ Gender')}: {gender_display}\n"
                    f"{texts.get('astro_local_time', '📅 Local time')}: {local_time}\n"
                    f"{texts.get('astro_timezone', '🕒 Timezone')}: {timezone or 'Unknown'}\n"
                    f"{texts.get('astro_utc_time', '🕒 UTC time')}: {utc_datetime or 'Unknown'}\n"
                    f"{texts.get('astro_place', '📍 Place')}: {user_data.get('birth_place', '')}\n"
                    f"{texts.get('astro_coordinates', '🌐 Coordinates')}: {lat:.4f}, {lng:.4f}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{texts.get('astro_sun', '☀️ Sun')}: {sun.get('sign', 'Unknown')}\n"
                    f"{texts.get('astro_moon', '🌙 Moon')}: {moon.get('sign', 'Unknown')}\n"
                    f"{texts.get('astro_ascendant', '⬆️ Ascendant')}: {asc_sign}"
                )
            else:
                basic_params = (
                    f"🌙 Ваш астрологический разбор\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{texts.get('astro_name', '👤 Имя')}: {user_data.get('name', '')}\n"
                    f"{texts.get('astro_gender', '⚥ Пол')}: {gender_display}\n"
                    f"{texts.get('astro_local_time', '📅 Локальное время')}: {local_time}\n"
                    f"{texts.get('astro_timezone', '🕒 Часовой пояс')}: {timezone or 'Unknown'}\n"
                    f"{texts.get('astro_utc_time', '🕒 Время UTC')}: {utc_datetime or 'Unknown'}\n"
                    f"{texts.get('astro_place', '📍 Место')}: {user_data.get('birth_place', '')}\n"
                    f"{texts.get('astro_coordinates', '🌐 Координаты')}: {lat:.4f}, {lng:.4f}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{texts.get('astro_sun', '☀️ Солнце')}: {sun.get('sign', 'Неизвестно')}\n"
                    f"{texts.get('astro_moon', '🌙 Луна')}: {moon.get('sign', 'Неизвестно')}\n"
                    f"{texts.get('astro_ascendant', '⬆️ Асцендент')}: {asc_sign}"
                )

            # Полные параметры для администратора
            full_params = ""
            if is_admin:
                # Используем данные из data для построения полного блока
                # Это тот же код, что был в format_full_astrology_parameters, но с учётом структуры данных
                from bot.utils.formatters import format_full_astrology_parameters
                full_params = format_full_astrology_parameters(data, transit_data=None, lang=lang)

            return {'basic': basic_params, 'full': full_params}

        except Exception as e:
            logger.error(f"❌ Ошибка в get_astrology_display_data: {e}", exc_info=True)
            return {'basic': f"❌ Ошибка при формировании данных: {e}", 'full': ""}

    async def generate_horoscope_with_context(self, user_id: int, context: str, lang: str,
                                              period: str = 'today', display_date: str = '') -> str:
        from bot.db import get_emulation_mode
        emulation = await get_emulation_mode(user_id)
        template = self._load_prompt_template('prompt_horoscope_v3.txt')
        if not template:
            logger.error("Шаблон prompt_horoscope_v3.txt не найден")
            return "❌ Ошибка: шаблон для гороскопа не найден."

        period_name = "день" if period == 'today' else "месяц" if period == 'month' else "год"
        replacements = {
            "context": context,
            "period": period_name
        }
        if lang == 'en':
            replacements[
                'language_instruction'] = "IMPORTANT: Respond in English only. All your output must be in English."
        else:
            replacements[
                'language_instruction'] = "ВАЖНО: Отвечай только на русском языке. Весь твой ответ должен быть на русском."

        prompt = self._replace_placeholders(template, replacements)
        if emulation:
            return f"🔍 РЕЖИМ ЭМУЛЯЦИИ (промпт не отправлен в нейросеть):\n\n{prompt}"
        return self._send_prompt(prompt, lang)

    def _prepare_astrology_replacements(self, json_data: Dict[str, Any], lang: str) -> Dict[str, str]:
        """Подготавливает замены для промпта астрологии (натальной карты)."""
        from datetime import datetime
        from bot.utils.zodiac import get_zodiac_sign_localized

        # Извлекаем данные
        natal = json_data.get('natal', {})
        metadata = json_data.get('metadata', {})
        user_data = self.user_data or {}

        name = user_data.get('name', 'Человек')
        gender = user_data.get('gender', 'M')
        if lang == 'ru':
            gender_text = "Мужчина" if gender == 'M' else "Женщина" if gender == 'F' else "Не указан"
        else:
            gender_text = "Male" if gender == 'M' else "Female" if gender == 'F' else "Not specified"
        birth_date = user_data.get('birth_date', 'не указана')
        birth_time = user_data.get('birth_time', 'не указано')
        birth_place = user_data.get('birth_place', 'не указано')
        analysis_date = datetime.now().strftime('%d.%m.%Y')

        # Натальные секции
        planets = natal.get('planets', [])
        houses = natal.get('houses', [])
        rulers = natal.get('house_rulers', [])
        aspects = natal.get('aspects', [])
        themes = json_data.get('themes', {})
        angles = natal.get('angles', {})

        # Форматирование
        planets_table = self._format_planets_table(planets)
        cusps_str = self._format_cusps(houses)
        house_rulers_str = self._format_house_rulers(rulers)
        natal_aspects_str = self._format_aspects(aspects)
        themes_str = self._format_themes(themes)
        angles_str = (
            f"ASC: {angles.get('ASC', 0):.2f}°, "
            f"MC: {angles.get('MC', 0):.2f}°, "
            f"DSC: {angles.get('DSC', 0):.2f}°, "
            f"IC: {angles.get('IC', 0):.2f}°"
        ) if angles else "Нет данных об углах."

        # Метаданные
        settings = metadata.get('settings', {})
        metadata_settings = (
            f"Зодиак: {settings.get('zodiac', 'tropical')}\n"
            f"Система домов: {settings.get('house_system', 'Placidus')}\n"
            f"Эфемериды: {settings.get('ephemeris', 'kerykeion')}\n"
            f"Лунный узел: {settings.get('lunar_node', 'true')}\n"
            f"Система координат: {settings.get('coordinate_system', 'geocentric')}\n"
            f"Тип прогрессий: {settings.get('progression_type', 'secondary')}\n"
            f"Орбы аспектов: {settings.get('aspect_orb', {})}"
        )

        # Дополнительные блоки (транзиты, прогрессии, медицинские показатели)
        transits = json_data.get('transits', {})
        transit_aspects = transits.get('aspects', [])
        transit_aspects_str = self._format_transit_aspects(transit_aspects)

        progressions = json_data.get('progressions', {})
        progression_aspects = progressions.get('aspects', [])
        progression_aspects_str = self._format_transit_aspects(progression_aspects)  # используем тот же форматтер

        # Медицинские показатели (заглушка, можно дополнить)
        health_indicators_str = "6-й дом (здоровье) и 8-й дом (кризисы) — см. натальные дома."

        # Астрокартография (заглушка)
        astrocartography_str = "Астрокартографические линии: см. натальную карту."

        # Языковая инструкция добавляется в _build_astrology_prompt отдельно

        replacements = {
            "person_name": name,
            "person_gender": gender_text,
            "birth_date": birth_date,
            "birth_time": birth_time,
            "birth_place": birth_place,
            "analysis_date": analysis_date,
            "metadata_settings": metadata_settings,
            "planets_table": planets_table,
            "angles": angles_str,
            "cusps": cusps_str,
            "house_rulers_list": house_rulers_str,
            "natal_aspects_list": natal_aspects_str,
            "themes_with_evidence": themes_str,
            "transit_aspects_list": transit_aspects_str,
            "progression_aspects_list": progression_aspects_str,
            "health_indicators_list": health_indicators_str,
            "astrocartography_lines": astrocartography_str,
            "extra_info": "",
            "pronoun": "он" if gender == 'M' else "она",
            "possessive": "его" if gender == 'M' else "её",
        }

        return replacements