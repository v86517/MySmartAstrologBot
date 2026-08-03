import os
import requests
import json
from typing import Optional, Dict, Any
from datetime import datetime


class GeminiService:
    """Сервис для работы с Gemini API через gen-api.ru"""

    def __init__(self):
        self.api_key = os.getenv('GEMINI_API_KEY')
        if not self.api_key:
            raise ValueError("❌ GEMINI_API_KEY не найден в .env файле!")

        self.base_url = "https://proxy.gen-api.ru/v1/chat/completions"
        self.model = "gemini-3-1-flash-lite"
        self.prompts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'prompts')

    def _load_prompt_template(self, filename: str) -> str:
        """Загрузка шаблона промпта из файла"""
        filepath = os.path.join(self.prompts_dir, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            return None

    def _replace_placeholders(self, template: str, data: Dict[str, str]) -> str:
        """Замена плейсхолдеров {key} на значения"""
        result = template
        for key, value in data.items():
            result = result.replace(f'{{{key}}}', str(value))
        return result

    def generate_from_prompt(self, prompt_data: Dict[str, Any], prompt_file: str) -> str:
        """
        Универсальный метод генерации из промпта
        """
        # Загружаем шаблон
        template = self._load_prompt_template(prompt_file)

        if not template:
            return f"❌ Шаблон {prompt_file} не найден. Обратитесь к администратору."

        # Заменяем плейсхолдеры
        prompt = self._replace_placeholders(template, prompt_data)

        # Отправляем запрос
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

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
            response = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=90
            )

            if response.status_code == 200:
                data = response.json()
                if 'choices' in data and len(data['choices']) > 0:
                    return data['choices'][0]['message']['content']
                else:
                    return "❌ Не удалось получить ответ от ИИ. Попробуйте позже."
            else:
                return f"❌ Ошибка API: {response.status_code}"

        except requests.exceptions.Timeout:
            return "❌ Превышено время ожидания. Попробуйте позже."
        except Exception as e:
            return f"❌ Ошибка: {str(e)}"

    def _send_prompt(self, prompt: str) -> str:
        """
        Отправляет произвольный готовый промпт в нейросеть.
        Используется для методов, которые сами формируют промпт без шаблона.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

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
            response = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=90
            )

            if response.status_code == 200:
                data = response.json()
                if 'choices' in data and len(data['choices']) > 0:
                    return data['choices'][0]['message']['content']
                else:
                    return "❌ Не удалось получить ответ от ИИ."
            else:
                return f"❌ Ошибка API: {response.status_code}"
        except Exception as e:
            return f"❌ Ошибка: {str(e)}"

    def generate_horoscope(self, user_data: Dict[str, Any], date: str = None) -> str:
        """
        Генерация гороскопа с использованием транзитов
        """
        from bot.calculators.transit_horoscope_calculator import TransitHoroscopeCalculator

        calculator = TransitHoroscopeCalculator(user_data)
        prompt_data = calculator.calculate()

        # Если дата передана, заменяем target_date (для тестов)
        if date:
            prompt_data['target_date'] = date

        return self.generate_from_prompt(prompt_data, 'prompt_horoscope.txt')

    def generate_compatibility_from_prompt(self, person1: Dict[str, Any], person2: Dict[str, Any]) -> str:
        """
        Генерация совместимости с использованием расчетов
        """
        from bot.calculators import CompatibilityCalculator, PersonData

        p1 = PersonData(
            birth_date=person1.get('birth_date'),
            name=person1.get('name'),
            birth_time=person1.get('birth_time'),
            birth_place=person1.get('birth_place'),
            gender=person1.get('gender')
        )

        p2 = PersonData(
            birth_date=person2.get('birth_date'),
            name=person2.get('name'),
            birth_time=person2.get('birth_time'),
            birth_place=person2.get('birth_place'),
            gender=person2.get('gender')
        )

        calculator = CompatibilityCalculator(p1, p2)
        prompt_data = calculator.get_prompt_data()
        return self.generate_from_prompt(prompt_data, 'prompt_connect.txt')

    def generate_natal_chart(self, user_data: Dict[str, Any]) -> str:
        """
        Генерация натальной карты (устаревший метод, оставлен для совместимости)
        """
        from bot.calculators import NatalCalculator

        calculator = NatalCalculator(
            birth_date=user_data.get('birth_date'),
            name=user_data.get('name'),
            birth_time=user_data.get('birth_time'),
            birth_place=user_data.get('birth_place'),
            gender=user_data.get('gender')
        )

        prompt_data = calculator.get_prompt_data()
        return self.generate_from_prompt(prompt_data, 'prompt_natal_chart.txt')

    def generate_numerology(self, user_data: Dict[str, Any]) -> str:
        """
        Генерация нумерологического разбора с использованием расчётов
        """
        from bot.calculators import NatalCalculator

        calculator = NatalCalculator(
            birth_date=user_data.get('birth_date'),
            name=user_data.get('name'),
            birth_time=user_data.get('birth_time'),
            birth_place=user_data.get('birth_place'),
            gender=user_data.get('gender')
        )

        prompt_data = calculator.get_prompt_data()
        return self.generate_from_prompt(prompt_data, 'prompt_numerology.txt')

    def generate_astrology(self, user_data: Dict[str, Any]) -> str:
        """
        Генерация астрологического разбора с использованием специализированного расчёта
        и промпта, построенного на основе натальной карты.
        """
        from bot.calculators.astrology_calculator import AstrologyCalculator

        try:
            calculator = AstrologyCalculator(user_data)
            prompt = calculator.build_prompt()
            return self._send_prompt(prompt)
        except Exception as e:
            return f"❌ Ошибка при расчёте астрологии: {str(e)}"

    # Резервный метод для обратной совместимости
    def generate_compatibility(self, person1: Dict[str, Any], person2: Dict[str, Any]) -> str:
        """Резервный метод"""
        return self.generate_compatibility_from_prompt(person1, person2)

    def send_raw_prompt(self, prompt: str) -> str:
        """Отправляет готовый промпт в нейросеть (без повторных расчётов)."""
        return self._send_prompt(prompt)