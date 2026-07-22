from datetime import datetime
from typing import Optional, Dict
from .base_calculator import BaseCalculator


class NatalCalculator(BaseCalculator):
    """
    Режим 3: Натальная карта.
    """

    def __init__(
            self,
            birth_date: str,
            name: Optional[str] = None,
            birth_time: Optional[str] = None,
            birth_place: Optional[str] = None,
            gender: Optional[str] = None
    ):
        self.birth_date = birth_date
        self.name = name if name else "Человек"
        self.birth_time = birth_time if birth_time else "не указано"
        self.birth_place = birth_place if birth_place else "не указано"
        self.gender = gender if gender else "не указан"

        self.day, self.month, self.year = map(int, birth_date.split('.'))
        self.target_date = datetime.now().strftime('%d.%m.%Y')

        self.data = {}

    def calculate(self) -> Dict:
        """Выполняет все расчеты."""

        zodiac = self.get_zodiac_sign(self.day, self.month)
        element = self.get_zodiac_element(zodiac)
        quality = self.get_zodiac_quality(zodiac)

        life_path = self.calculate_life_path_number(self.birth_date)

        # Полная матрица
        matrix = self.calculate_full_matrix(self.birth_date)

        birth_weekday = self.week_day_name(self.birth_date)
        age = self.calculate_age(self.birth_date, self.target_date)

        # Упрощенный асцендент
        if self.birth_time != "не указано":
            ascendant = self.get_zodiac_sign(
                (self.day + 15) % 30 + 1,
                (self.month + 2) % 12 + 1
            )
            ascendant_note = ""
        else:
            ascendant = "требуется точное время для расчета"
            ascendant_note = "Если время рождения не указано — объясни, как определить асцендент при точном времени."

        self.data = {
            'name': self.name,
            'gender': self.gender,
            'gender_text': "Мужчина" if self.gender == 'М' else "Женщина" if self.gender == 'Ж' else "Человек",
            'birth_date': self.birth_date,
            'birth_weekday': birth_weekday,
            'birth_time': self.birth_time,
            'birth_place': self.birth_place,
            'age': age,
            'zodiac_sign': zodiac,
            'zodiac_element': element,
            'zodiac_quality': quality,
            'ascendant': ascendant,
            'ascendant_note': ascendant_note,
            'life_path': life_path,
            'matrix': matrix,
            # Для удобства подстановки
            'm1': matrix['m1'],
            'm2': matrix['m2'],
            'm3': matrix['m3'],
            'opv': matrix['opv'],
            'sz': matrix['sz'],
            'obstacle': matrix['obstacle'],
            'traitor': matrix['traitor'],
            'comfort': matrix['comfort'],
            'v_left': matrix['v_left'],
            'v_right': matrix['v_right'],
            'v_bottom_left': matrix['v_bottom_left'],
            'v_bottom_right': matrix['v_bottom_right'],
            'v_left_side': matrix['v_left_side'],
            'v_right_side': matrix['v_right_side'],
            'v_top': matrix['v_top'],
            'age_next_1': age + 1,
            'age_next_5': age + 5,
            'age_next_10': age + 10,
        }

        return self.data

    def get_prompt_data(self) -> Dict:
        """Возвращает данные для подстановки в промпт."""
        if not self.data:
            self.calculate()
        return self.data