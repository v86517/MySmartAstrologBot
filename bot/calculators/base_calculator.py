import datetime
import math
from typing import Optional, Dict, Any, Tuple


class BaseCalculator:
    """Базовый класс с общими расчетами для всех режимов."""

    @staticmethod
    def reduce_to_single(num: int, allow_master: bool = False) -> int:
        """Сворачивает число до 1-9, но мастер-числа 11,22 оставляет."""
        if allow_master and num in (11, 22):
            return num
        while num > 9:
            num = sum(int(d) for d in str(num))
        return num

    @staticmethod
    def get_arcan(num: int) -> int:
        """Приводит к аркану 1-22 (без нуля)."""
        if num == 0:
            return 22
        num = num % 22
        return num if num != 0 else 22

    @staticmethod
    def get_zodiac_sign(day: int, month: int) -> str:
        """Определяет знак зодиака."""
        if (month == 3 and day >= 21) or (month == 4 and day <= 19):
            return "Овен"
        elif (month == 4 and day >= 20) or (month == 5 and day <= 20):
            return "Телец"
        elif (month == 5 and day >= 21) or (month == 6 and day <= 20):
            return "Близнецы"
        elif (month == 6 and day >= 21) or (month == 7 and day <= 22):
            return "Рак"
        elif (month == 7 and day >= 23) or (month == 8 and day <= 22):
            return "Лев"
        elif (month == 8 and day >= 23) or (month == 9 and day <= 22):
            return "Дева"
        elif (month == 9 and day >= 23) or (month == 10 and day <= 22):
            return "Весы"
        elif (month == 10 and day >= 23) or (month == 11 and day <= 21):
            return "Скорпион"
        elif (month == 11 and day >= 22) or (month == 12 and day <= 21):
            return "Стрелец"
        elif (month == 12 and day >= 22) or (month == 1 and day <= 19):
            return "Козерог"
        elif (month == 1 and day >= 20) or (month == 2 and day <= 18):
            return "Водолей"
        else:
            return "Рыбы"

    @staticmethod
    def get_zodiac_element(sign: str) -> str:
        """Определяет стихию знака зодиака."""
        fire = ["Овен", "Лев", "Стрелец"]
        earth = ["Телец", "Дева", "Козерог"]
        air = ["Близнецы", "Весы", "Водолей"]
        water = ["Рак", "Скорпион", "Рыбы"]

        if sign in fire: return "Огонь"
        if sign in earth: return "Земля"
        if sign in air: return "Воздух"
        if sign in water: return "Вода"
        return "Неизвестно"

    @staticmethod
    def get_zodiac_quality(sign: str) -> str:
        """Определяет крест (качество) знака."""
        cardinal = ["Овен", "Рак", "Весы", "Козерог"]
        fixed = ["Телец", "Лев", "Скорпион", "Водолей"]
        mutable = ["Близнецы", "Дева", "Стрелец", "Рыбы"]

        if sign in cardinal: return "Кардинальный"
        if sign in fixed: return "Фиксированный"
        if sign in mutable: return "Мутабельный"
        return "Неизвестно"

    @staticmethod
    def moon_phase_percent(target_date: str) -> float:
        """Рассчитывает процент освещенности Луны (0-100%)."""
        known_new_moon = datetime.datetime(2000, 1, 6, 18, 14)
        target = datetime.datetime.strptime(target_date, '%d.%m.%Y')
        days_diff = (target - known_new_moon).days
        lunar_cycle = 29.530587981
        phase = (days_diff % lunar_cycle) / lunar_cycle
        return round(phase * 100, 1)

    @staticmethod
    def week_day_name(date_str: str) -> str:
        """Возвращает название дня недели."""
        days = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
        dt = datetime.datetime.strptime(date_str, '%d.%m.%Y')
        return days[dt.weekday()]

    @staticmethod
    def days_until_birthday(birth_date: str, target_date: str) -> int:
        """Считает дни до ближайшего дня рождения."""
        b_day, b_month, _ = map(int, birth_date.split('.'))
        target = datetime.datetime.strptime(target_date, '%d.%m.%Y')

        next_birthday = datetime.datetime(target.year, b_month, b_day)
        if next_birthday < target:
            next_birthday = datetime.datetime(target.year + 1, b_month, b_day)

        delta = next_birthday - target
        return delta.days

    @staticmethod
    def calculate_age(birth_date: str, target_date: str) -> int:
        """Вычисляет возраст."""
        b_day, b_month, b_year = map(int, birth_date.split('.'))
        t_day, t_month, t_year = map(int, target_date.split('.'))

        age = t_year - b_year
        if (t_month, t_day) < (b_month, b_day):
            age -= 1
        return age

    @staticmethod
    def calculate_life_path_number(birth_date: str) -> int:
        """Вычисляет число жизненного пути."""
        day, month, year = map(int, birth_date.split('.'))
        total = day + month + year
        return BaseCalculator.reduce_to_single(total)

    @staticmethod
    def calculate_personal_day_number(birth_date: str, target_date: str) -> int:
        """Вычисляет число персонального дня."""
        b_day, b_month, _ = map(int, birth_date.split('.'))
        t_day, t_month, t_year = map(int, target_date.split('.'))
        total = b_day + b_month + t_day + t_month + t_year
        return BaseCalculator.reduce_to_single(total)

    @staticmethod
    def calculate_personal_year(birth_date: str, target_date: str) -> int:
        """Вычисляет личный год."""
        b_day, b_month, _ = map(int, birth_date.split('.'))
        _, _, t_year = map(int, target_date.split('.'))
        total = b_day + b_month + t_year
        return BaseCalculator.reduce_to_single(total)

    @staticmethod
    def calculate_matrix_arcans(birth_date: str) -> Dict[str, int]:
        """Рассчитывает основные арканы матрицы судьбы."""
        day, month, year = map(int, birth_date.split('.'))

        m1 = BaseCalculator.get_arcan(day)
        m2 = BaseCalculator.get_arcan(month)
        m3 = BaseCalculator.get_arcan(sum(int(d) for d in str(year)))

        opv = BaseCalculator.get_arcan(m1 - m2)
        sz = BaseCalculator.get_arcan(m1 + m2 + m3)

        return {
            'm1': m1,
            'm2': m2,
            'm3': m3,
            'opv': opv,
            'sz': sz,
        }

    @staticmethod
    def calculate_transit_arcan(birth_date: str, target_date: str) -> int:
        """Вычисляет транзитный аркан на сегодня."""
        b_year = int(birth_date.split('.')[2])
        t_day, t_month, t_year = map(int, target_date.split('.'))

        arcan_birth_year = BaseCalculator.get_arcan(sum(int(d) for d in str(b_year)))
        arcan_target_day = BaseCalculator.get_arcan(t_day)
        arcan_target_month = BaseCalculator.get_arcan(t_month)
        arcan_target_year = BaseCalculator.get_arcan(sum(int(d) for d in str(t_year)))

        total = arcan_birth_year + arcan_target_day + arcan_target_month + arcan_target_year
        return BaseCalculator.get_arcan(total)

    @staticmethod
    def get_lunar_day(target_date: str) -> int:
        """Вычисляет лунный день (1-30)."""
        known_new_moon = datetime.datetime(2000, 1, 6, 18, 14)
        target = datetime.datetime.strptime(target_date, '%d.%m.%Y')
        days_diff = (target - known_new_moon).days
        lunar_cycle = 29.530587981
        lunar_day = int((days_diff % lunar_cycle) + 1)
        return lunar_day if lunar_day <= 30 else 30

    @staticmethod
    def calculate_compatibility_number(date1: str, date2: str) -> int:
        """Вычисляет число совместимости двух дат."""
        total1 = sum(map(int, date1.split('.')))
        total2 = sum(map(int, date2.split('.')))
        total = total1 + total2
        return BaseCalculator.reduce_to_single(total)

    @staticmethod
    def calculate_compatibility_arcan(date1: str, date2: str) -> int:
        """Вычисляет аркан совместимости."""
        day1, month1, year1 = map(int, date1.split('.'))
        day2, month2, year2 = map(int, date2.split('.'))

        total = day1 + month1 + year1 + day2 + month2 + year2
        return BaseCalculator.get_arcan(total)

    @staticmethod
    def calculate_full_matrix(birth_date: str) -> Dict[str, int]:
        """Полный расчет матрицы судьбы (все 11 вершин)."""
        matrix = BaseCalculator.calculate_matrix_arcans(birth_date)

        m1, m2, m3 = matrix['m1'], matrix['m2'], matrix['m3']
        opv, sz = matrix['opv'], matrix['sz']

        # Прямой квадрат
        obstacle = BaseCalculator.get_arcan(m1 + m2)
        traitor = BaseCalculator.get_arcan(m2 + m3)
        comfort = BaseCalculator.get_arcan(obstacle + traitor)

        # Кристалл судьбы
        v_left = BaseCalculator.get_arcan(m1 + opv)
        v_right = BaseCalculator.get_arcan(m2 + sz)
        v_bottom_left = BaseCalculator.get_arcan(m3 + opv)
        v_bottom_right = BaseCalculator.get_arcan(m3 + sz)
        v_left_side = BaseCalculator.get_arcan(m1 + m3)
        v_right_side = BaseCalculator.get_arcan(m2 + m3)
        v_top = BaseCalculator.get_arcan(opv + sz)

        return {
            'm1': m1, 'm2': m2, 'm3': m3,
            'opv': opv, 'sz': sz,
            'obstacle': obstacle,
            'traitor': traitor,
            'comfort': comfort,
            'v_left': v_left,
            'v_right': v_right,
            'v_bottom_left': v_bottom_left,
            'v_bottom_right': v_bottom_right,
            'v_left_side': v_left_side,
            'v_right_side': v_right_side,
            'v_top': v_top
        }