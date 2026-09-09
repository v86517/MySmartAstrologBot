# bot/calculators/numerology_alvasar.py

import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)


class NumerologyAlvasarCalculator:
    """
    Калькулятор нумерологии по методике «Альвасар» Джулии По.
    Использует только имя, дату рождения и пол.
    """

    # Пифагорейские соответствия для кириллицы и латиницы
    PYTHAGOREAN_MAP = {
        # Кириллица
        'а': 1, 'б': 2, 'в': 3, 'г': 4, 'д': 5, 'е': 6, 'ё': 7, 'ж': 8, 'з': 9,
        'и': 1, 'й': 2, 'к': 3, 'л': 4, 'м': 5, 'н': 6, 'о': 7, 'п': 8, 'р': 9,
        'с': 1, 'т': 2, 'у': 3, 'ф': 4, 'х': 5, 'ц': 6, 'ч': 7, 'ш': 8, 'щ': 9,
        'ъ': 1, 'ы': 2, 'ь': 3, 'э': 4, 'ю': 5, 'я': 6,
        # Латиница
        'a': 1, 'b': 2, 'c': 3, 'd': 4, 'e': 5, 'f': 6, 'g': 7, 'h': 8, 'i': 9,
        'j': 1, 'k': 2, 'l': 3, 'm': 4, 'n': 5, 'o': 6, 'p': 7, 'q': 8, 'r': 9,
        's': 1, 't': 2, 'u': 3, 'v': 4, 'w': 5, 'x': 6, 'y': 7, 'z': 8,
    }

    VOWELS_CYRILLIC = set('аеёиоуыэюя')
    VOWELS_LATIN = set('aeiouy')

    SIGNS = [
        (120, 'Стрелец'), (102, 'Скорпион'), (84, 'Весы'), (66, 'Дева'),
        (48, 'Лев'), (30, 'Рак'), (12, 'Близнецы'), (354, 'Телец'),
        (336, 'Овен'), (318, 'Рыбы'), (300, 'Водолей'), (282, 'Козерог'),
    ]

    def __init__(self, name: str, birth_date: str, gender: Optional[str] = None):
        self.name = name.strip()
        self.birth_date_str = birth_date
        self.gender = gender

        self._birth_date = None
        self._day = None
        self._month = None
        self._year = None
        self._parse_birth_date()

        self._matrix = {}
        self._life_path = None
        self._name_numbers = {}
        self._personal_periods = {}
        self._emotionality = None
        self._zodiac = {}

        self._calculated = False

    # ---------- ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ----------

    def _parse_birth_date(self):
        try:
            dt = datetime.strptime(self.birth_date_str, '%d.%m.%Y')
            self._birth_date = dt
            self._day = dt.day
            self._month = dt.month
            self._year = dt.year
        except ValueError:
            logger.error(f"Неверный формат даты: {self.birth_date_str}")
            self._birth_date = None
            self._day = 1
            self._month = 1
            self._year = 2000

    @staticmethod
    def _reduce_to_arcan(num: int) -> int:
        """Приводит число к аркану 1–22 (0 → 22)."""
        if num == 0:
            return 22
        num = num % 22
        return num if num != 0 else 22

    @staticmethod
    def _reduce_to_master(num: int) -> int:
        """Приводит к 1–9, оставляя мастер-числа 11, 22, 33."""
        if num in (11, 22, 33):
            return num
        while num > 9:
            num = sum(int(d) for d in str(num))
        return num

    @staticmethod
    def _sum_digits(num: int) -> int:
        return sum(int(d) for d in str(num))

    def _get_pythagorean_value(self, char: str) -> Optional[int]:
        return self.PYTHAGOREAN_MAP.get(char.lower())

    def _transliterate_name(self, name: str) -> str:
        """Если имя содержит китайские иероглифы, транслитерируем (заглушка)."""
        # Для простоты пока возвращаем как есть
        return name

    # ---------- РАСЧЁТ МАТРИЦЫ СУДЬБЫ ----------

    def _calculate_matrix(self) -> Dict[str, int]:
        """
        Рассчитывает 11 позиций матрицы судьбы по методике Альвасар.
        """
        m1 = self._reduce_to_arcan(self._day)
        m2 = self._reduce_to_arcan(self._month)
        m3 = self._reduce_to_arcan(self._sum_digits(self._year))

        opv = self._reduce_to_arcan(abs(m1 - m2))
        sz = self._reduce_to_arcan(m1 + m2 + m3)

        matrix = {
            'm1': m1,
            'm2': m2,
            'm3': m3,
            'opv': opv,
            'sz': sz,
            'obstacle': self._reduce_to_arcan(m1 + m2),
            'traitor': self._reduce_to_arcan(m2 + m3),
            'comfort': self._reduce_to_arcan(m1 + m3),
            'v_left': self._reduce_to_arcan(m1 + opv),
            'v_right': self._reduce_to_arcan(m2 + sz),
            'v_bottom_left': self._reduce_to_arcan(m3 + opv),
            'v_bottom_right': self._reduce_to_arcan(m3 + sz),
            'v_left_side': self._reduce_to_arcan(m1 + m3),  # совпадает с comfort
            'v_right_side': self._reduce_to_arcan(m2 + m3),  # совпадает с traitor
            'v_top': self._reduce_to_arcan(opv + sz),
        }
        self._matrix = matrix
        return matrix

    # ---------- ЧИСЛО ЖИЗНЕННОГО ПУТИ ----------

    def _calculate_life_path(self) -> int:
        total = self._day + self._month + self._year
        self._life_path = self._reduce_to_master(total)
        return self._life_path

    # ---------- ЧИСЛА ИМЕНИ ----------

    def _calculate_name_numbers(self) -> Dict[str, int]:
        name = self._transliterate_name(self.name)
        if not name:
            return {'expression': None, 'soul': None, 'personality': None}

        total = 0
        vowel_total = 0
        consonant_total = 0

        # Определяем язык: если есть кириллица, используем кириллицу
        is_cyrillic = any('а' <= c <= 'я' for c in name.lower())

        vowels = self.VOWELS_CYRILLIC if is_cyrillic else self.VOWELS_LATIN

        for char in name:
            val = self._get_pythagorean_value(char)
            if val is not None:
                total += val
                if char.lower() in vowels:
                    vowel_total += val
                else:
                    consonant_total += val

        self._name_numbers = {
            'expression': self._reduce_to_master(total) if total else None,
            'soul': self._reduce_to_master(vowel_total) if vowel_total else None,
            'personality': self._reduce_to_master(consonant_total) if consonant_total else None,
        }
        return self._name_numbers

    # ---------- ЛИЧНЫЕ ПЕРИОДЫ ----------

    def _calculate_personal_periods(self) -> Dict[str, int]:
        now = datetime.now()
        target_date = now.strftime('%d.%m.%Y')
        t_day, t_month, t_year = map(int, target_date.split('.'))

        # Личный год
        personal_year = self._reduce_to_master(self._day + self._month + t_year)
        personal_month = self._reduce_to_master(personal_year + t_month)
        personal_day = self._reduce_to_master(personal_month + t_day)

        self._personal_periods = {
            'year': personal_year,
            'month': personal_month,
            'day': personal_day,
        }
        return self._personal_periods

    # ---------- ЭМОЦИОНАЛЬНОСТЬ В ОТНОШЕНИЯХ ----------

    def _calculate_emotionality(self) -> int:
        """
        Аркан эмоциональности = Число экспрессии + Аркан зоны комфорта → 1–22.
        """
        if not self._name_numbers:
            self._calculate_name_numbers()
        if not self._matrix:
            self._calculate_matrix()

        expr = self._name_numbers.get('expression', 0)
        comfort = self._matrix.get('comfort', 0)
        if expr is None:
            expr = 0
        total = expr + comfort
        self._emotionality = self._reduce_to_arcan(total)
        return self._emotionality

    # ---------- ЗНАК ЗОДИАКА ----------

    def _calculate_zodiac(self) -> Dict[str, str]:
        day = self._day
        month = self._month

        if (month == 3 and day >= 21) or (month == 4 and day <= 20):
            sign = "Овен"
        elif (month == 4 and day >= 21) or (month == 5 and day <= 21):
            sign = "Телец"
        elif (month == 5 and day >= 22) or (month == 6 and day <= 21):
            sign = "Близнецы"
        elif (month == 6 and day >= 22) or (month == 7 and day <= 22):
            sign = "Рак"
        elif (month == 7 and day >= 23) or (month == 8 and day <= 23):
            sign = "Лев"
        elif (month == 8 and day >= 24) or (month == 9 and day <= 23):
            sign = "Дева"
        elif (month == 9 and day >= 24) or (month == 10 and day <= 22):
            sign = "Весы"
        elif (month == 10 and day >= 23) or (month == 11 and day <= 22):
            sign = "Скорпион"
        elif (month == 11 and day >= 23) or (month == 12 and day <= 21):
            sign = "Стрелец"
        elif (month == 12 and day >= 22) or (month == 1 and day <= 19):
            sign = "Козерог"
        elif (month == 1 and day >= 20) or (month == 2 and day <= 19):
            sign = "Водолей"
        else:
            sign = "Рыбы"

        elements = {
            'Овен': 'Огонь', 'Лев': 'Огонь', 'Стрелец': 'Огонь',
            'Телец': 'Земля', 'Дева': 'Земля', 'Козерог': 'Земля',
            'Близнецы': 'Воздух', 'Весы': 'Воздух', 'Водолей': 'Воздух',
            'Рак': 'Вода', 'Скорпион': 'Вода', 'Рыбы': 'Вода',
        }
        qualities = {
            'Овен': 'Кардинальный', 'Рак': 'Кардинальный', 'Весы': 'Кардинальный', 'Козерог': 'Кардинальный',
            'Телец': 'Фиксированный', 'Лев': 'Фиксированный', 'Скорпион': 'Фиксированный', 'Водолей': 'Фиксированный',
            'Близнецы': 'Мутабельный', 'Дева': 'Мутабельный', 'Стрелец': 'Мутабельный', 'Рыбы': 'Мутабельный',
        }

        self._zodiac = {
            'sign': sign,
            'element': elements.get(sign, 'Неизвестно'),
            'quality': qualities.get(sign, 'Неизвестно'),
        }
        return self._zodiac

    # ---------- ГЛАВНЫЙ МЕТОД РАСЧЁТА ----------

    def calculate(self) -> Dict[str, Any]:
        if self._calculated:
            return self._get_all_data()

        self._calculate_matrix()
        self._calculate_life_path()
        self._calculate_name_numbers()
        self._calculate_personal_periods()
        self._calculate_emotionality()
        self._calculate_zodiac()

        self._calculated = True
        return self._get_all_data()

    def _get_all_data(self) -> Dict[str, Any]:
        gender_display = "Мужчина" if self.gender == 'M' else "Женщина" if self.gender == 'F' else "Не указан"
        pronoun = "он" if self.gender == 'M' else "она" if self.gender == 'F' else "человек"
        possessive = "его" if self.gender == 'M' else "её" if self.gender == 'F' else "человека"

        return {
            'name': self.name,
            'gender': self.gender,
            'gender_display': gender_display,
            'pronoun': pronoun,
            'possessive': possessive,
            'birth_date': self.birth_date_str,
            'day': self._day,
            'month': self._month,
            'year': self._year,
            'life_path': self._life_path,
            'matrix': self._matrix,
            'm1': self._matrix.get('m1'),
            'm2': self._matrix.get('m2'),
            'm3': self._matrix.get('m3'),
            'opv': self._matrix.get('opv'),
            'sz': self._matrix.get('sz'),
            'obstacle': self._matrix.get('obstacle'),
            'traitor': self._matrix.get('traitor'),
            'comfort': self._matrix.get('comfort'),
            'v_left': self._matrix.get('v_left'),
            'v_right': self._matrix.get('v_right'),
            'v_bottom_left': self._matrix.get('v_bottom_left'),
            'v_bottom_right': self._matrix.get('v_bottom_right'),
            'v_left_side': self._matrix.get('v_left_side'),
            'v_right_side': self._matrix.get('v_right_side'),
            'v_top': self._matrix.get('v_top'),
            'expression_number': self._name_numbers.get('expression'),
            'soul_urge_number': self._name_numbers.get('soul'),
            'personality_number': self._name_numbers.get('personality'),
            'personal_year': self._personal_periods.get('year'),
            'personal_month': self._personal_periods.get('month'),
            'personal_day': self._personal_periods.get('day'),
            'emotionality_arcan': self._emotionality,
            'zodiac_sign': self._zodiac.get('sign'),
            'zodiac_element': self._zodiac.get('element'),
            'zodiac_quality': self._zodiac.get('quality'),
        }

    # ---------- ФОРМИРОВАНИЕ КОНТЕКСТА ДЛЯ ПРОМПТА ----------

    def build_prompt_context(self, lang: str = 'ru') -> str:
        data = self._get_all_data()
        matrix = data['matrix']

        lines = []
        lines.append("### Нумерологические параметры")
        lines.append("")
        lines.append(f"Дата рождения: {data['birth_date']}")
        lines.append(f"Имя: {data['name']}")
        lines.append(f"Пол: {data['gender_display']}")
        lines.append("")
        lines.append("#### Матрица судьбы (22 аркана)")
        lines.append(f"Аркан дня: {matrix['m1']}")
        lines.append(f"Аркан месяца: {matrix['m2']}")
        lines.append(f"Аркан года: {matrix['m3']}")
        lines.append(f"Отношения (ОПВ): {matrix['opv']}")
        lines.append(f"Судьба (СЗ): {matrix['sz']}")
        lines.append(f"Препятствие: {matrix['obstacle']}")
        lines.append(f"Человек-предатель: {matrix['traitor']}")
        lines.append(f"Зона комфорта: {matrix['comfort']}")
        lines.append(f"Левая родовая: {matrix['v_left']}")
        lines.append(f"Правая родовая: {matrix['v_right']}")
        lines.append(f"Карма левая: {matrix['v_bottom_left']}")
        lines.append(f"Карма правая: {matrix['v_bottom_right']}")
        lines.append(f"Внутренний паспорт: {matrix['v_top']}")
        lines.append("")
        lines.append("#### Числа имени")
        lines.append(f"Число экспрессии: {data['expression_number'] or 'не рассчитано'}")
        lines.append(f"Число души: {data['soul_urge_number'] or 'не рассчитано'}")
        lines.append(f"Число личности: {data['personality_number'] or 'не рассчитано'}")
        lines.append("")
        lines.append("#### Личные периоды (на сегодня)")
        lines.append(f"Личный год: {data['personal_year']}")
        lines.append(f"Личный месяц: {data['personal_month']}")
        lines.append(f"Личный день: {data['personal_day']}")
        lines.append("")
        lines.append("#### Эмоциональность в отношениях")
        lines.append(f"Аркан эмоциональности: {data['emotionality_arcan']}")
        lines.append("")
        lines.append("#### Знак зодиака")
        lines.append(f"Знак: {data['zodiac_sign']}")
        lines.append(f"Стихия: {data['zodiac_element']}")
        lines.append(f"Крест: {data['zodiac_quality']}")

        return "\n".join(lines)