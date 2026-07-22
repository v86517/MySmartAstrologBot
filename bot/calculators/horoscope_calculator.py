from datetime import datetime
from typing import Optional, Dict
from .base_calculator import BaseCalculator


class HoroscopeCalculator(BaseCalculator):
    """
    Режим 1: Гороскоп на день.
    """

    def __init__(
            self,
            birth_date: str,
            target_date: Optional[str] = None,
            name: Optional[str] = None,
            birth_time: Optional[str] = None,
            birth_place: Optional[str] = None,
            gender: Optional[str] = None
    ):
        self.birth_date = birth_date
        self.target_date = target_date or datetime.now().strftime('%d.%m.%Y')
        self.name = name if name else "Человек"
        self.birth_time = birth_time if birth_time else "не указано"
        self.birth_place = birth_place if birth_place else "не указано"
        self.gender = gender if gender else "не указан"

        self.b_day, self.b_month, self.b_year = map(int, birth_date.split('.'))
        self.t_day, self.t_month, self.t_year = map(int, self.target_date.split('.'))

        self.data = {}

    def calculate(self) -> Dict:
        """Выполняет все расчеты."""

        zodiac = self.get_zodiac_sign(self.b_day, self.b_month)
        element = self.get_zodiac_element(zodiac)
        quality = self.get_zodiac_quality(zodiac)
        age = self.calculate_age(self.birth_date, self.target_date)

        life_path = self.calculate_life_path_number(self.birth_date)
        personal_day = self.calculate_personal_day_number(self.birth_date, self.target_date)
        personal_year = self.calculate_personal_year(self.birth_date, self.target_date)

        matrix = self.calculate_matrix_arcans(self.birth_date)
        transit_arcan = self.calculate_transit_arcan(self.birth_date, self.target_date)

        moon_illumination = self.moon_phase_percent(self.target_date)
        lunar_day = self.get_lunar_day(self.target_date)
        week_day = self.week_day_name(self.target_date)
        birth_weekday = self.week_day_name(self.birth_date)
        days_to_birthday = self.days_until_birthday(self.birth_date, self.target_date)

        self.data = {
            'name': self.name,
            'gender': self.gender,
            'gender_text': "Мужчина" if self.gender == 'М' else "Женщина" if self.gender == 'Ж' else "Человек",
            'birth_date': self.birth_date,
            'birth_weekday': birth_weekday,
            'birth_time': self.birth_time,
            'birth_place': self.birth_place,
            'target_date': self.target_date,
            'target_weekday': week_day,
            'age': age,
            'zodiac_sign': zodiac,
            'zodiac_element': element,
            'zodiac_quality': quality,
            'life_path_number': life_path,
            'personal_day_number': personal_day,
            'personal_year': personal_year,
            'matrix_center': matrix['sz'],
            'transit_arcan': transit_arcan,
            'moon_illumination': moon_illumination,
            'lunar_day': lunar_day,
            'days_to_birthday': days_to_birthday,
            'is_birthday_today': days_to_birthday == 0,
            'birthday_note': "СЕГОДНЯ ДЕНЬ РОЖДЕНИЯ! 🎂" if days_to_birthday == 0 else f"До дня рождения: {days_to_birthday} дней",
            'birthday_congrats': "ОБЯЗАТЕЛЬНО поздравь с Днем Рождения и дай мощный энергетический заряд!" if days_to_birthday == 0 else "",
        }

        return self.data

    def get_prompt_data(self) -> Dict:
        """Возвращает данные для подстановки в промпт."""
        if not self.data:
            self.calculate()
        return self.data