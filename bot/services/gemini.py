import os
import requests
import json
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from bot.calculators.base_calculator import BaseCalculator
from bot.calculators.natal_calculator import NatalCalculator
from bot.db import get_user_language

# ============ НАСТРОЙКИ ОТЛАДКИ ============
# Установите True, чтобы видеть полный промпт в логах перед отправкой в LLM
DEBUG_PRINT_PROMPT = True  # <-- после отладки установите False
# ===========================================

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
        self.user_data = None  # будет установлено в методах генерации
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
        """Отправляет промпт в LLM. Если DEBUG_PRINT_PROMPT = True, выводит промпт в лог."""
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

    # ==================== СТАРЫЕ МЕТОДЫ (ОБРАТНАЯ СОВМЕСТИМОСТЬ) ====================

    def generate_from_prompt(self, prompt_data: Dict[str, Any], prompt_file: str, lang: str = 'ru') -> str:
        template = self._load_prompt_template(prompt_file)
        if not template:
            return f"❌ Шаблон {prompt_file} не найден."
        prompt = self._replace_placeholders(template, prompt_data)
        return self._send_prompt(prompt, lang)

    # ---------- ГОРОСКОП ----------
    def generate_horoscope(self, user_data: Dict[str, Any], lang: str = 'ru') -> str:
        from bot.calculators.transit_horoscope_calculator import TransitHoroscopeCalculator
        calculator = TransitHoroscopeCalculator(user_data, lang)
        prompt_data = calculator.calculate()

        if lang == 'en':
            prompt_data['language_instruction'] = "IMPORTANT: Respond in English only. All your forecast must be in English."
        else:
            prompt_data['language_instruction'] = "ВАЖНО: Отвечай только на русском языке. Весь прогноз должен быть на русском."

        return self.generate_from_prompt(prompt_data, 'prompt_horoscope.txt', lang)

    # ---------- СОВМЕСТИМОСТЬ ----------
    def generate_compatibility_from_prompt(self, person1: Dict[str, Any], person2: Dict[str, Any],
                                           lang: str = 'ru') -> str:
        from bot.calculators.compatibility_calculator import CompatibilityCalculator
        calculator = CompatibilityCalculator(person1, person2)
        prompt_data = calculator.get_prompt_data()

        if lang == 'en':
            prompt_data['language_instruction'] = "IMPORTANT: Respond in English only. All your analysis must be in English."
        else:
            prompt_data['language_instruction'] = "ВАЖНО: Отвечай только на русском языке. Весь анализ должен быть на русском."

        return self.generate_from_prompt(prompt_data, 'prompt_connect.txt', lang)

    # ---------- НУМЕРОЛОГИЯ ----------
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

    # ---------- АСТРОЛОГИЯ (старый метод) ----------
    def generate_astrology(self, user_data: Dict[str, Any], lang: str = 'ru') -> str:
        from bot.calculators.astrology_calculator import AstrologyCalculator
        calculator = AstrologyCalculator(user_data)
        prompt = calculator.build_prompt(lang)
        return self._send_prompt(prompt, lang)

    # ---------- ОТПРАВКА ПРОИЗВОЛЬНОГО ПРОМПТА ----------
    def send_raw_prompt(self, prompt: str, lang: str = 'ru') -> str:
        return self._send_prompt(prompt, lang)

    # ---------- РЕЗЕРВНЫЙ МЕТОД ДЛЯ СОВМЕСТИМОСТИ ----------
    def generate_compatibility(self, person1: Dict[str, Any], person2: Dict[str, Any], lang: str = 'ru') -> str:
        return self.generate_compatibility_from_prompt(person1, person2, lang)

    # ==================== НОВЫЙ МЕТОД ДЛЯ НАТАЛЬНОЙ КАРТЫ (JSON v2) ====================

    def generate_astrology_v2(self, user_data: Dict[str, Any], lang: str = 'ru') -> str:
        """
        Генерирует интерпретацию натальной карты на основе JSON v2.
        Использует AstrologyDataBuilder и новый промпт для натальной карты.
        """
        self.user_data = user_data
        self.lang = lang

        from bot.calculators.astrology_data_builder import AstrologyDataBuilder
        builder = AstrologyDataBuilder(user_data, lang)
        json_data = builder.build()

        prompt = self._build_astrology_prompt(json_data, lang)
        return self._send_prompt(prompt, lang)

    def _build_astrology_prompt(self, json_data: Dict[str, Any], lang: str) -> str:
        """Строит промпт для натальной карты из JSON v2."""
        template = self._load_prompt_template('prompt_astrology_v2.txt')
        if not template:
            logger.warning("Шаблон prompt_astrology_v2.txt не найден, используется fallback")
            return self._build_fallback_prompt(json_data, 'astrology')

        replacements = self._prepare_astrology_replacements(json_data, lang)

        prompt = template
        for key, value in replacements.items():
            prompt = prompt.replace(f'{{{key}}}', str(value))

        # Языковая инструкция (если не вставлена через плейсхолдер)
        if lang == 'en':
            language_instruction = "IMPORTANT: Respond in English only. All your analysis must be in English."
        else:
            language_instruction = "ВАЖНО: Отвечай только на русском языке. Весь анализ должен быть на русском."
        prompt = prompt.replace('{language_instruction}', language_instruction)

        return prompt

    def _prepare_astrology_replacements(self, data: Dict[str, Any], lang: str) -> Dict[str, str]:
        """Извлекает и форматирует данные из JSON v2 для подстановки в промпт."""
        natal = data.get('natal', {})
        transits = data.get('transits', {})
        progressions = data.get('progressions', {})
        themes = data.get('themes', {})
        timeline = data.get('timeline', [])
        metadata = data.get('metadata', {})

        user_data = self.user_data or {}

        # Базовые данные
        name = user_data.get('name', 'Человек')
        gender = user_data.get('gender', 'M')
        gender_text = "Мужчина" if gender == 'M' else "Женщина"
        birth_date = user_data.get('birth_date', 'не указана')
        birth_time = user_data.get('birth_time', 'не указано')
        birth_place = user_data.get('birth_place', 'не указано')
        analysis_date = datetime.now().strftime('%d.%m.%Y')

        # Стандарт расчёта
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

        # Планеты (таблица)
        planets = natal.get('planets', [])
        planets_table = "| Планета | Знак | Градус | Дом | Ретроград | Скорость | Вес |\n"
        planets_table += "|---------|------|--------|-----|-----------|----------|-----|\n"
        for p in planets:
            planets_table += (
                f"| {p.get('name_local', p.get('name', ''))} "
                f"| {p.get('sign', '')} "
                f"| {p.get('degree', 0):.2f}° "
                f"| {p.get('house', 0)} "
                f"| {'Да' if p.get('retrograde') else 'Нет'} "
                f"| {p.get('speed', 0):.3f} "
                f"| {p.get('weight', 0)} |\n"
            )

        # Углы
        # Попробуем извлечь из данных или построить через расчёт
        angles = "ASC: {:.2f}°\nMC: {:.2f}°\nDSC: {:.2f}°\nIC: {:.2f}°".format(0, 0, 0, 0)
        # В будущем можно добавить реальные углы из builder

        # Куспиды домов
        houses = natal.get('houses', [])
        cusps = "\n".join([f"Дом {h['number']}: {h['cusp']} ({h['cusp_degree']:.2f}°)" for h in houses])

        # Управители домов
        rulers = natal.get('house_rulers', [])
        house_rulers_list = "\n".join([
            f"Дом {r['house']}: {r['cusp']} -> управитель {r['ruler']} (в {r['ruler_sign']}, {r['ruler_house']} доме)"
            for r in rulers
        ])

        # Диспозиторы
        dispositors = natal.get('dispositors', [])
        dispositors_list = "\n".join([
            f"{d['planet']} -> {d['dispositor']} (цепь: {' -> '.join(d['chain'])}, финал: {d['final_dispositor']})"
            for d in dispositors
        ])

        # Натальные аспекты
        aspects = natal.get('aspects', [])
        natal_aspects_list = "\n".join([
            f"{a['p1_name_local']} {a['aspect_local']} {a['p2_name_local']} (орб: {a['orb']}°, вес: {a['weight']})"
            for a in aspects
        ])

        # Аспекты к углам
        angle_aspects = natal.get('angle_aspects', [])
        angle_aspects_list = "\n".join([
            f"{a['planet_local']} {a['aspect_local']} {a['angle']} (орб: {a['orb']}°, скор: {a['score']})"
            for a in angle_aspects
        ])

        # Доминанты
        elements = natal.get('dominant_elements', {})
        modalities = natal.get('dominant_modalities', {})
        signs = natal.get('dominant_signs', {})
        houses_dom = natal.get('dominant_houses', {})
        dominants = (
            f"Элементы: {elements}\n"
            f"Модальности: {modalities}\n"
            f"Знаки: {signs}\n"
            f"Дома: {houses_dom}"
        )

        # Стеллиумы и конфигурации
        patterns = natal.get('patterns', [])
        patterns_list = "\n".join([
            f"{p['type']}: {', '.join(p.get('planets', p.get('objects', [])))} (сила: {p.get('strength', 0)})"
            for p in patterns
        ])

        # Ретроградные планеты
        retrograde_planets = ", ".join([p['name_local'] for p in planets if p.get('retrograde')])

        # Сводка
        summary_data = natal.get('summary', {})
        summary = (
            f"Доминирующие планеты: {summary_data.get('dominant_planets', [])}\n"
            f"Доминирующие элементы: {summary_data.get('dominant_elements', [])}\n"
            f"Доминирующие модальности: {summary_data.get('dominant_modalities', [])}\n"
            f"Доминирующие знаки: {summary_data.get('dominant_signs', [])}\n"
            f"Доминирующие дома: {summary_data.get('dominant_houses', [])}\n"
            f"Ключевые темы: {summary_data.get('core_themes', [])}\n"
            f"Сильнейшие аспекты: {summary_data.get('strongest_aspects', [])}\n"
            f"Основные напряжения: {summary_data.get('major_tensions', [])}\n"
            f"Основные ресурсы: {summary_data.get('major_resources', [])}"
        )

        # Темы с доказательствами
        themes_with_evidence = ""
        for theme, tdata in themes.items():
            ev = tdata.get('evidence', [])
            ev_str = "; ".join([f"{e['source']} ({e['type']})" for e in ev[:3]])
            themes_with_evidence += (
                f"{theme}: score={tdata['score']}, confidence={tdata['confidence']}, "
                f"evidence_count={tdata['evidence_count']}, repeating={tdata['repeating_theme']}\n"
                f"  Доказательства: {ev_str}\n"
            )

        # ---- Транзиты (подробно) ----
        transit_aspects = transits.get('aspects', [])
        transit_lines = []
        for ta in transit_aspects[:10]:
            line = (
                f"**{ta['transit_planet_local']} → {ta['natal_planet_local']}**\n"
                f"  Аспект: {ta['aspect_local']}\n"
                f"  Орбис: {ta['orb']}°\n"
                f"  Фаза: {ta['phase']}\n"
                f"  Точная дата: {ta['exact_date'] or 'не определена'}\n"
                f"  Транзитный дом: {ta['transit_house']}\n"
                f"  Натальный дом: {ta['natal_house']}\n"
                f"  Score: {ta['score']}\n"
                f"  Confidence: {ta['confidence']}\n"
                f"  Темы: {', '.join(ta.get('themes', []))}"
            )
            transit_lines.append(line)
        transits_str = "\n\n".join(transit_lines) if transit_lines else "Нет значимых транзитных аспектов."

        # ---- Прогрессии (подробно) ----
        prog_aspects = progressions.get('aspects', [])
        prog_lines = []
        for pa in prog_aspects[:10]:
            line = (
                f"**{pa['progressed_planet_local']} → {pa['natal_planet_local']}**\n"
                f"  Аспект: {pa['aspect_local']}\n"
                f"  Орбис: {pa['orb']}°\n"
                f"  Фаза: {pa['phase']}\n"
                f"  Точная дата: {pa['exact_date'] or 'не определена'}\n"
                f"  Натальный дом: {pa.get('natal_house', 'не указан')}\n"
                f"  Score: {pa['score']}\n"
                f"  Confidence: {pa['confidence']}\n"
                f"  Темы: {', '.join(pa.get('themes', []))}"
            )
            prog_lines.append(line)
        progressions_str = "\n\n".join(prog_lines) if prog_lines else "Нет значимых прогрессивных аспектов."

        # Общий блок транзитов и прогрессий
        transits_and_progressions = "**Транзитные аспекты:**\n\n" + transits_str
        if progressions_str:
            transits_and_progressions += "\n\n**Прогрессивные аспекты:**\n\n" + progressions_str

        # ---- Активные периоды (таймлайн) ----
        active_periods = transits.get('active_periods', [])
        timeline_lines = []
        for period in active_periods[:5]:
            start = period.get('start', '')
            end = period.get('end', '')
            theme = period.get('theme', '')
            intensity = period.get('intensity', 0)
            confidence = period.get('confidence', 0)
            evidence = period.get('evidence', [])
            evidence_str = ""
            for ev in evidence[:3]:
                evidence_str += (
                    f"    - {ev['transit']} {ev['aspect']} {ev['natal']} "
                    f"(орб: {ev['orb']}°, фаза: {ev['phase']}, точная дата: {ev.get('exact_date', 'не опр.')})\n"
                    f"      Score: {ev['score']}, Confidence: {ev['confidence']}\n"
                )
            timeline_lines.append(
                f"**{start} — {end}**\n"
                f"Тема: {theme}\n"
                f"Интенсивность: {intensity}/10\n"
                f"Confidence: {confidence}\n"
                f"Подтверждения:\n{evidence_str}"
            )
        timeline_str = "\n\n".join(timeline_lines) if timeline_lines else "Нет активных периодов."

        # Собираем словарь для подстановки
        replacements = {
            "person_name": name,
            "person_gender": gender_text,
            "birth_date": birth_date,
            "birth_time": birth_time,
            "birth_place": birth_place,
            "analysis_date": analysis_date,
            "metadata_settings": metadata_settings,
            "planets_table": planets_table,
            "angles": angles,
            "cusps": cusps,
            "house_rulers_list": house_rulers_list,
            "dispositors_list": dispositors_list,
            "natal_aspects_list": natal_aspects_list,
            "angle_aspects_list": angle_aspects_list,
            "dominants": dominants,
            "patterns_list": patterns_list,
            "retrograde_planets": retrograde_planets or "Нет ретроградных планет",
            "summary": summary,
            "themes_with_evidence": themes_with_evidence,
            "transits_and_progressions": transits_and_progressions,
            "timeline": timeline_str,
        }
        return replacements

    def _build_fallback_prompt(self, json_data: Dict, service_type: str) -> str:
        """Резервный метод для старых форматов."""
        if service_type == 'astrology':
            from bot.calculators.astrology_calculator import AstrologyCalculator
            calc = AstrologyCalculator(self.user_data or {})
            return calc.build_prompt(self.lang)
        else:
            return "❌ Новые шаблоны для JSON v2 не найдены. Используйте старые методы."