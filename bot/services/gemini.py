import os
import requests
import json
from typing import Optional, Dict, Any
from datetime import datetime
from bot.calculators.base_calculator import BaseCalculator
from bot.calculators.natal_calculator import NatalCalculator
from bot.db import get_user_language  # если нужно

class GeminiService:
    def __init__(self):
        self.api_key = os.getenv('GEMINI_API_KEY')
        if not self.api_key:
            raise ValueError("❌ GEMINI_API_KEY не найден в .env файле!")
        self.base_url = "https://proxy.gen-api.ru/v1/chat/completions"
        self.model = "gemini-3-1-flash-lite"
        self.prompts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'prompts')
        self._base_calc = BaseCalculator()

    def _load_prompt_template(self, filename: str) -> str:
        filepath = os.path.join(self.prompts_dir, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
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

    def generate_from_prompt(self, prompt_data: Dict[str, Any], prompt_file: str, lang: str = 'ru') -> str:
        template = self._load_prompt_template(prompt_file)
        if not template:
            return f"❌ Шаблон {prompt_file} не найден."
        prompt = self._replace_placeholders(template, prompt_data)
        prompt = self._add_language_instruction(prompt, lang)

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Ты - профессиональный астролог, нумеролог и эзотерик."},
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

    def _send_prompt(self, prompt: str, lang: str = 'ru') -> str:
        prompt = self._add_language_instruction(prompt, lang)
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

    # ---------- ГОРОСКОП ----------
    def generate_horoscope(self, user_data: Dict[str, Any], date: str = None, lang: str = 'ru') -> str:
        from bot.calculators.transit_horoscope_calculator import TransitHoroscopeCalculator
        calculator = TransitHoroscopeCalculator(user_data)
        prompt_data = calculator.calculate()
        return self.generate_from_prompt(prompt_data, 'prompt_horoscope.txt', lang)

    # ---------- СОВМЕСТИМОСТЬ ----------
    def generate_compatibility_from_prompt(self, person1: Dict[str, Any], person2: Dict[str, Any], lang: str = 'ru') -> str:
        from bot.calculators.compatibility_calculator import CompatibilityCalculator
        calculator = CompatibilityCalculator(person1, person2)
        prompt_data = calculator.get_prompt_data()
        return self.generate_from_prompt(prompt_data, 'prompt_connect.txt', lang)

    # ---------- НУМЕРОЛОГИЯ ----------
    def generate_numerology(self, user_data: Dict[str, Any], lang: str = 'ru') -> str:
        from bot.calculators import NatalCalculator
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

        # Новые нумерологические числа
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

        return self.generate_from_prompt(prompt_data, 'prompt_numerology.txt', lang)

    # ---------- АСТРОЛОГИЯ ----------
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