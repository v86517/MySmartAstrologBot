from datetime import datetime
from typing import Optional, Dict
from .base_calculator import BaseCalculator


class PersonData:
    """Класс для хранения данных одного человека."""

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


class CompatibilityCalculator(BaseCalculator):
    """
    Режим 2: Совместимость двух людей.
    """

    def __init__(
            self,
            person1: PersonData,
            person2: PersonData,
            target_date: Optional[str] = None
    ):
        self.p1 = person1
        self.p2 = person2
        self.target_date = target_date or datetime.now().strftime('%d.%m.%Y')
        self.data = {}

    def calculate(self) -> Dict:
        """Выполняет все расчеты."""

        zodiac1 = self.get_zodiac_sign(self.p1.day, self.p1.month)
        zodiac2 = self.get_zodiac_sign(self.p2.day, self.p2.month)

        element1 = self.get_zodiac_element(zodiac1)
        element2 = self.get_zodiac_element(zodiac2)

        quality1 = self.get_zodiac_quality(zodiac1)
        quality2 = self.get_zodiac_quality(zodiac2)

        life_path1 = self.calculate_life_path_number(self.p1.birth_date)
        life_path2 = self.calculate_life_path_number(self.p2.birth_date)

        matrix1 = self.calculate_matrix_arcans(self.p1.birth_date)
        matrix2 = self.calculate_matrix_arcans(self.p2.birth_date)

        compatibility_number = self.calculate_compatibility_number(
            self.p1.birth_date, self.p2.birth_date
        )
        compatibility_arcan = self.calculate_compatibility_arcan(
            self.p1.birth_date, self.p2.birth_date
        )

        # Совместимость по стихиям
        element_compatibility = {
            ("Огонь", "Огонь"): "Высокая — оба энергичны, но могут конкурировать.",
            ("Огонь", "Земля"): "Средняя — дополняют друг друга, но требуют усилий.",
            ("Огонь", "Воздух"): "Отличная — воздух раздувает огонь, вдохновение.",
            ("Огонь", "Вода"): "Сложная — вода тушит огонь, нужен баланс.",
            ("Земля", "Земля"): "Высокая — стабильность, но возможна скука.",
            ("Земля", "Воздух"): "Сложная — воздух уносит землю, нестабильность.",
            ("Земля", "Вода"): "Отличная — вода питает землю, плодородие.",
            ("Воздух", "Воздух"): "Средняя — легкость, но нет глубины.",
            ("Воздух", "Вода"): "Сложная — вода и воздух конфликтуют.",
            ("Вода", "Вода"): "Высокая — глубокое понимание, но могут утонуть в эмоциях."
        }

        element_pair = tuple(sorted([element1, element2]))
        element_compat = element_compatibility.get(
            (element1, element2),
            element_compatibility.get(element_pair, "Средняя — зависит от других факторов.")
        )

        transit_arcan1 = self.calculate_transit_arcan(self.p1.birth_date, self.target_date)
        transit_arcan2 = self.calculate_transit_arcan(self.p2.birth_date, self.target_date)

        age1 = self.calculate_age(self.p1.birth_date, self.target_date)
        age2 = self.calculate_age(self.p2.birth_date, self.target_date)

        days_to_bday1 = self.days_until_birthday(self.p1.birth_date, self.target_date)
        days_to_bday2 = self.days_until_birthday(self.p2.birth_date, self.target_date)

        week_day = self.week_day_name(self.target_date)
        moon_phase = self.moon_phase_percent(self.target_date)
        lunar_day = self.get_lunar_day(self.target_date)

        self.data = {
            'person1': {
                'name': self.p1.name,
                'gender': self.p1.gender,
                'gender_text': "Мужчина" if self.p1.gender == 'М' else "Женщина" if self.p1.gender == 'Ж' else "Человек",
                'birth_date': self.p1.birth_date,
                'birth_time': self.p1.birth_time,
                'birth_place': self.p1.birth_place,
                'zodiac': zodiac1,
                'element': element1,
                'quality': quality1,
                'life_path': life_path1,
                'age': age1,
                'days_to_birthday': days_to_bday1,
                'matrix_center': matrix1['sz'],
                'transit_arcan': transit_arcan1,
            },
            'person2': {
                'name': self.p2.name,
                'gender': self.p2.gender,
                'gender_text': "Мужчина" if self.p2.gender == 'М' else "Женщина" if self.p2.gender == 'Ж' else "Человек",
                'birth_date': self.p2.birth_date,
                'birth_time': self.p2.birth_time,
                'birth_place': self.p2.birth_place,
                'zodiac': zodiac2,
                'element': element2,
                'quality': quality2,
                'life_path': life_path2,
                'age': age2,
                'days_to_birthday': days_to_bday2,
                'matrix_center': matrix2['sz'],
                'transit_arcan': transit_arcan2,
            },
            'compatibility': {
                'number': compatibility_number,
                'arcan': compatibility_arcan,
                'element_compatibility': element_compat,
                'zodiac_pair': f"{zodiac1} + {zodiac2}",
            },
            'target_date': self.target_date,
            'target_weekday': week_day,
            'moon_phase': moon_phase,
            'lunar_day': lunar_day,
        }

        return self.data

    def get_prompt_data(self) -> Dict:
        """Возвращает данные для подстановки в промпт."""
        if not self.data:
            self.calculate()

        # Упрощаем структуру для подстановки в промпт
        p1 = self.data['person1']
        p2 = self.data['person2']
        comp = self.data['compatibility']

        return {
            'p1_name': p1['name'],
            'p1_gender_text': p1['gender_text'],
            'p1_birth_date': p1['birth_date'],
            'p1_birth_time': p1['birth_time'],
            'p1_birth_place': p1['birth_place'],
            'p1_zodiac': p1['zodiac'],
            'p1_element': p1['element'],
            'p1_quality': p1['quality'],
            'p1_life_path': p1['life_path'],
            'p1_matrix_center': p1['matrix_center'],
            'p1_age': p1['age'],
            'p1_days_to_birthday': p1['days_to_birthday'],
            'p2_name': p2['name'],
            'p2_gender_text': p2['gender_text'],
            'p2_birth_date': p2['birth_date'],
            'p2_birth_time': p2['birth_time'],
            'p2_birth_place': p2['birth_place'],
            'p2_zodiac': p2['zodiac'],
            'p2_element': p2['element'],
            'p2_quality': p2['quality'],
            'p2_life_path': p2['life_path'],
            'p2_matrix_center': p2['matrix_center'],
            'p2_age': p2['age'],
            'p2_days_to_birthday': p2['days_to_birthday'],
            'zodiac_pair': comp['zodiac_pair'],
            'element_compatibility': comp['element_compatibility'],
            'compatibility_number': comp['number'],
            'compatibility_arcan': comp['arcan'],
            'target_date': self.data['target_date'],
            'target_weekday': self.data['target_weekday'],
            'lunar_day': self.data['lunar_day'],
            'moon_phase': self.data['moon_phase'],
        }