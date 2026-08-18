import re
from datetime import datetime


def normalize_gender(text: str) -> str:
    """
    Приводит введённый пол к стандартному виду 'M' или 'F'.
    Принимает: М, Ж, M, F (регистр не важен).
    Возвращает 'M' или 'F', либо None, если не распознано.
    """
    text = text.strip().upper()
    if text in ('М', 'M'):
        return 'M'
    elif text in ('Ж', 'F'):
        return 'F'
    return None


def validate_date(date_str: str) -> bool:
    """Проверяет, что строка имеет формат ДД.ММ.ГГГГ и является валидной датой."""
    if not re.match(r'^\d{2}\.\d{2}\.\d{4}$', date_str):
        return False
    try:
        datetime.strptime(date_str, "%d.%m.%Y")
        return True
    except ValueError:
        return False


def validate_time(time_str: str) -> bool:
    """Проверяет, что строка имеет формат ЧЧ:ММ и является валидным временем."""
    if not re.match(r'^\d{2}:\d{2}$', time_str):
        return False
    try:
        datetime.strptime(time_str, "%H:%M")
        return True
    except ValueError:
        return False