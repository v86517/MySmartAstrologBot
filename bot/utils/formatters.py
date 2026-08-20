#bot\utils\formatters.py
import logging
from datetime import datetime
from bot.locales import TEXTS
from bot.utils.zodiac import get_zodiac_emoji, get_zodiac_sign_localized
from bot.calculators.base_calculator import BaseCalculator
from bot.calculators.natal_calculator import NatalCalculator
from bot.calculators.compatibility_calculator import CompatibilityCalculator
from bot.calculators.transit_horoscope_calculator import TransitHoroscopeCalculator
from bot.calculators.astrology_calculator import AstrologyCalculator

logger = logging.getLogger(__name__)


def format_parameters(prompt_data: dict, service_type: str, lang: str = 'ru') -> str:
    """Форматирует параметры для отображения пользователю."""
    texts = TEXTS.get(lang, TEXTS['ru'])
    lines = []

    if service_type == 'horoscope':
        lines.append("📅 Гороскоп на день")
        lines.append("")
        lines.append(f"👤 Имя: {prompt_data.get('name', '')}")
        lines.append(f"⚥ Пол: {prompt_data.get('gender_display', '')}")
        lines.append(f"📅 Дата рождения: {prompt_data.get('birth_date', '')}")
        lines.append(f"🕒 Время рождения: {prompt_data.get('birth_time', '')}")
        lines.append(f"📍 Место рождения: {prompt_data.get('birth_place', '')}")
        lines.append("")
        lines.append(f"☀️ Солнце: {prompt_data.get('sun_sign', '')}")
        lines.append(f"🌙 Луна: {prompt_data.get('moon_sign', '')}")
        lines.append(f"⬆️ Асцендент: {prompt_data.get('ascendant', '')}")
        lines.append("")
        lines.append(f"📅 Дата: {prompt_data.get('target_date', '')}")
        lines.append(f"📆 День недели: {prompt_data.get('target_weekday', '')}")
        lines.append(f"🌙 Лунный день: {prompt_data.get('lunar_day', '')}")
        lines.append(f"☀️ Освещённость Луны: {prompt_data.get('moon_illumination', '')}%")
        lines.append(f"🌙 Транзитная Луна в знаке: {prompt_data.get('transit_moon_sign', '')}")
        lines.append(f"🏠 Транзитная Луна в доме: {prompt_data.get('transit_moon_house', '')}")
        lines.append(f"🔮 Аспекты транзитной Луны:\n{prompt_data.get('transit_moon_aspects', '')}")
        lines.append(f"🔄 Ретроградные планеты: {prompt_data.get('retrograde_planets', '')}")
        # Логирование для отладки
        logger.info(f"planets_list в format_parameters: {prompt_data.get('planets_list')}")
        logger.info(f"aspects_list в format_parameters: {prompt_data.get('aspects_list')}")
        logger.info(f"transit_aspects в format_parameters: {prompt_data.get('transit_aspects')}")
        # Натальные планеты, аспекты и транзитные аспекты (только для разрешённых пользователей)
        if prompt_data.get('planets_list'):
            lines.append("")
            lines.append("🪐 Натальные планеты в знаках и домах:")
            lines.append(prompt_data.get('planets_list', ''))

        if prompt_data.get('aspects_list'):
            lines.append("")
            lines.append("🔮 Натальные аспекты:")
            lines.append(prompt_data.get('aspects_list', ''))

        if prompt_data.get('transit_aspects'):
            lines.append("")
            lines.append("🌟 Транзитные аспекты на сегодня:")
            lines.append(prompt_data.get('transit_aspects', ''))
        if prompt_data.get('cusps_list'):
            lines.append("")
            lines.append("🏠 Куспиды домов:")
            lines.append(prompt_data.get('cusps_list', ''))

    elif service_type == 'numerology':
        lines.append("")
        lines.append(f"👤 Имя: {prompt_data.get('name', '')}")
        lines.append(f"⚥ Пол: {prompt_data.get('gender_display', '')}")
        lines.append(f"📅 Дата рождения: {prompt_data.get('birth_date', '')}")
        lines.append(f"🕒 Время рождения: {prompt_data.get('birth_time', '')}")
        lines.append(f"📍 Место рождения: {prompt_data.get('birth_place', '')}")
        lines.append("")
        lines.append(f"🔢 Число жизненного пути: {prompt_data.get('life_path', '')}")
        lines.append(f"🔢 Число экспрессии: {prompt_data.get('expression_number', '')}")
        lines.append(f"🔢 Число души: {prompt_data.get('soul_urge_number', '')}")
        lines.append(f"🔢 Число личности: {prompt_data.get('personality_number', '')}")
        lines.append(f"📅 Личный год: {prompt_data.get('personal_year', '')}")
        lines.append(f"📅 Личный месяц: {prompt_data.get('personal_month', '')}")
        lines.append(f"📅 Личный день: {prompt_data.get('personal_day', '')}")
        lines.append("")
        lines.append("🧩 Матрица судьбы (22 аркана):")
        lines.append(f"  Аркан дня (m1): {prompt_data.get('m1', '')}")
        lines.append(f"  Аркан месяца (m2): {prompt_data.get('m2', '')}")
        lines.append(f"  Аркан года (m3): {prompt_data.get('m3', '')}")
        lines.append(f"  Отношения (ОПВ): {prompt_data.get('opv', '')}")
        lines.append(f"  Судьба (СЗ): {prompt_data.get('sz', '')}")
        lines.append(f"  Препятствие: {prompt_data.get('obstacle', '')}")
        lines.append(f"  Человек-предатель: {prompt_data.get('traitor', '')}")
        lines.append(f"  Зона комфорта: {prompt_data.get('comfort', '')}")
        lines.append(f"  Левая родовая: {prompt_data.get('v_left', '')}")
        lines.append(f"  Правая родовая: {prompt_data.get('v_right', '')}")
        lines.append(f"  Кармическая (нижняя левая): {prompt_data.get('v_bottom_left', '')}")
        lines.append(f"  Кармическая (нижняя правая): {prompt_data.get('v_bottom_right', '')}")
        lines.append(f"  Багаж опыта: {prompt_data.get('v_left_side', '')}")
        lines.append(f"  Человек-предатель (правый бок): {prompt_data.get('v_right_side', '')}")
        lines.append(f"  Внутренний паспорт: {prompt_data.get('v_top', '')}")

    elif service_type == 'compatibility':
        lines.append("")  # убираем лишний заголовок
        # Человек 1
        lines.append(texts.get('compatibility_person', '👤 Person {num}').format(num=1))
        lines.append(f"{texts.get('compatibility_gender_label', '⚥ Gender')}: {prompt_data.get('p1_gender_text', '')}")
        lines.append(
            f"{texts.get('compatibility_birth_date_label', '📅 Date of birth')}: {prompt_data.get('p1_birth_date', '')}")
        lines.append(
            f"{texts.get('compatibility_birth_time_label', '🕒 Time of birth')}: {prompt_data.get('p1_birth_time', '')}")
        lines.append(
            f"{texts.get('compatibility_birth_place_label', '📍 Place of birth')}: {prompt_data.get('p1_birth_place', '')}")
        lines.append(f"{texts.get('compatibility_sun_label', '☀️ Sun')}: {prompt_data.get('p1_sun_sign', '')}")
        lines.append(f"{texts.get('compatibility_moon_label', '🌙 Moon')}: {prompt_data.get('p1_moon_sign', '')}")
        lines.append(
            f"{texts.get('compatibility_ascendant_label', '⬆️ Ascendant')}: {prompt_data.get('p1_ascendant', '')}")
        if prompt_data.get('p1_cusps_list') and prompt_data.get('p1_cusps_list') != "не известно":
            lines.append(texts.get('compatibility_house_cusps_label', '🏠 House cusps') + ":")
            lines.append(prompt_data.get('p1_cusps_list', ''))
        if prompt_data.get('p1_planets_list') and prompt_data.get('p1_planets_list') != "не известно":
            lines.append("")
            lines.append(texts.get('compatibility_natal_planets_label',
                                   '🪐 Natal planets in signs and houses (Person {num})').format(num=1) + ":")
            lines.append(prompt_data.get('p1_planets_list', ''))
        if prompt_data.get('p1_aspects_list') and prompt_data.get('p1_aspects_list') != "не известно":
            lines.append("")
            lines.append(
                texts.get('compatibility_natal_aspects_label', '🔮 Natal aspects (Person {num})').format(num=1) + ":")
            lines.append(prompt_data.get('p1_aspects_list', ''))

        lines.append("")
        # Человек 2
        lines.append(texts.get('compatibility_person', '👤 Person {num}').format(num=2))
        lines.append(f"{texts.get('compatibility_gender_label', '⚥ Gender')}: {prompt_data.get('p2_gender_text', '')}")
        lines.append(
            f"{texts.get('compatibility_birth_date_label', '📅 Date of birth')}: {prompt_data.get('p2_birth_date', '')}")
        lines.append(
            f"{texts.get('compatibility_birth_time_label', '🕒 Time of birth')}: {prompt_data.get('p2_birth_time', '')}")
        lines.append(
            f"{texts.get('compatibility_birth_place_label', '📍 Place of birth')}: {prompt_data.get('p2_birth_place', '')}")
        lines.append(f"{texts.get('compatibility_sun_label', '☀️ Sun')}: {prompt_data.get('p2_sun_sign', '')}")
        lines.append(f"{texts.get('compatibility_moon_label', '🌙 Moon')}: {prompt_data.get('p2_moon_sign', '')}")
        lines.append(
            f"{texts.get('compatibility_ascendant_label', '⬆️ Ascendant')}: {prompt_data.get('p2_ascendant', '')}")
        if prompt_data.get('p2_cusps_list') and prompt_data.get('p2_cusps_list') != "не известно":
            lines.append(texts.get('compatibility_house_cusps_label', '🏠 House cusps') + ":")
            lines.append(prompt_data.get('p2_cusps_list', ''))
        if prompt_data.get('p2_planets_list') and prompt_data.get('p2_planets_list') != "не известно":
            lines.append("")
            lines.append(texts.get('compatibility_natal_planets_label',
                                   '🪐 Natal planets in signs and houses (Person {num})').format(num=2) + ":")
            lines.append(prompt_data.get('p2_planets_list', ''))
        if prompt_data.get('p2_aspects_list') and prompt_data.get('p2_aspects_list') != "не известно":
            lines.append("")
            lines.append(
                texts.get('compatibility_natal_aspects_label', '🔮 Natal aspects (Person {num})').format(num=2) + ":")
            lines.append(prompt_data.get('p2_aspects_list', ''))

        lines.append("")
        lines.append(texts.get('compatibility_synastry_aspects_label', '🔮 Synastry aspects') + ":")
        lines.append(prompt_data.get('aspects_synastry_list', ''))
        lines.append(f"{texts.get('compatibility_date_label', '📅 Date')}: {prompt_data.get('target_date', '')}")
        # Локализуем день недели
        weekday = prompt_data.get('target_weekday', '')
        weekday_map = {
            'Понедельник': texts.get('weekday_monday', 'Monday'),
            'Вторник': texts.get('weekday_tuesday', 'Tuesday'),
            'Среда': texts.get('weekday_wednesday', 'Wednesday'),
            'Четверг': texts.get('weekday_thursday', 'Thursday'),
            'Пятница': texts.get('weekday_friday', 'Friday'),
            'Суббота': texts.get('weekday_saturday', 'Saturday'),
            'Воскресенье': texts.get('weekday_sunday', 'Sunday'),
            'Monday': 'Monday', 'Tuesday': 'Tuesday', 'Wednesday': 'Wednesday',
            'Thursday': 'Thursday', 'Friday': 'Friday', 'Saturday': 'Saturday', 'Sunday': 'Sunday',
        }
        target_weekday = weekday_map.get(weekday, weekday)
        lines.append(f"{texts.get('compatibility_weekday_label', '📆 Day of week')}: {target_weekday}")
        lines.append(f"{texts.get('compatibility_lunar_day_label', '🌙 Lunar day')}: {prompt_data.get('lunar_day', '')}")
        lines.append(
            f"{texts.get('compatibility_moon_illumination_label', '☀️ Moon illumination')}: {prompt_data.get('moon_illumination', '')}%")

    elif service_type == 'astrology':
        pass

    return "\n".join(lines)


def format_basic_horoscope_parameters(prompt_data: dict, lang: str = 'ru') -> str:
    """Форматирует базовые параметры гороскопа для обычных пользователей."""
    texts = TEXTS.get(lang, TEXTS['ru'])

    gender_display = prompt_data.get('gender_display', texts.get('astro_gender_unknown', 'Not specified'))

    weekday = prompt_data.get('target_weekday', '')
    weekday_map = {
        'Понедельник': texts.get('weekday_monday', 'Monday'),
        'Вторник': texts.get('weekday_tuesday', 'Tuesday'),
        'Среда': texts.get('weekday_wednesday', 'Wednesday'),
        'Четверг': texts.get('weekday_thursday', 'Thursday'),
        'Пятница': texts.get('weekday_friday', 'Friday'),
        'Суббота': texts.get('weekday_saturday', 'Saturday'),
        'Воскресенье': texts.get('weekday_sunday', 'Sunday'),
        'Monday': 'Monday', 'Tuesday': 'Tuesday', 'Wednesday': 'Wednesday',
        'Thursday': 'Thursday', 'Friday': 'Friday', 'Saturday': 'Saturday', 'Sunday': 'Sunday',
    }
    target_weekday = weekday_map.get(weekday, weekday)

    lines = []
    lines.append("")
    lines.append(f"{texts.get('horoscope_basic_name', '👤 Name')}: {prompt_data.get('name', '')}")
    lines.append(f"{texts.get('horoscope_basic_gender', '⚥ Gender')}: {gender_display}")
    lines.append(f"{texts.get('horoscope_basic_birth_date', '📅 Date of birth')}: {prompt_data.get('birth_date', '')}")
    lines.append(f"{texts.get('horoscope_basic_birth_time', '🕒 Time of birth')}: {prompt_data.get('birth_time', '')}")
    lines.append(f"{texts.get('horoscope_basic_birth_place', '📍 Place of birth')}: {prompt_data.get('birth_place', '')}")
    lines.append("")
    lines.append(f"{texts.get('horoscope_basic_sun', '☀️ Sun')}: {prompt_data.get('sun_sign', '')}")
    lines.append(f"{texts.get('horoscope_basic_moon', '🌙 Moon')}: {prompt_data.get('moon_sign', '')}")
    lines.append(f"{texts.get('horoscope_basic_ascendant', '⬆️ Ascendant')}: {prompt_data.get('ascendant', '')}")
    lines.append("")
    lines.append(f"{texts.get('horoscope_basic_target_date', '📅 Date')}: {prompt_data.get('target_date', '')}")
    lines.append(f"{texts.get('horoscope_basic_target_weekday', '📆 Day of week')}: {target_weekday}")
    lines.append(f"{texts.get('horoscope_basic_lunar_day', '🌙 Lunar day')}: {prompt_data.get('lunar_day', '')}")
    lines.append(f"{texts.get('horoscope_basic_moon_illumination', '☀️ Moon illumination')}: {prompt_data.get('moon_illumination', '')}%")
    lines.append(f"{texts.get('horoscope_basic_transit_moon_sign', '🌙 Transit Moon in sign')}: {prompt_data.get('transit_moon_sign', '')}")
    lines.append(f"{texts.get('horoscope_basic_transit_moon_house', '🏠 Transit Moon in house')}: {prompt_data.get('transit_moon_house', '')}")
    lines.append(f"{texts.get('horoscope_basic_retrograde', '🔄 Retrograde planets')}: {prompt_data.get('retrograde_planets', '')}")

    return "\n".join(lines)


def format_profile_data(data: dict, lang: str, show_timezone: bool = True) -> str:
    """Форматирует данные пользователя для отображения с учётом языка"""
    texts = TEXTS.get(lang, TEXTS['ru'])

    if data.get('gender') == 'M':
        gender_display = texts.get('astro_gender_male', 'Мужской')
    elif data.get('gender') == 'F':
        gender_display = texts.get('astro_gender_female', 'Женский')
    else:
        gender_display = texts.get('astro_gender_unknown', 'Не указан')

    zodiac_emoji = get_zodiac_emoji(data.get('zodiac', 'Неизвестно'))
    zodiac_name = get_zodiac_sign_localized(data.get('zodiac', 'Неизвестно'), lang)
    timezone = data.get('timezone_offset', 3)

    lines = [
        f"{texts.get('profile_field_name', '👤 Имя')}: {data.get('name', 'Не указано')}",
        f"{texts.get('profile_field_birth_date', '📅 Дата рождения')}: {data.get('birth_date', 'Не указана')}",
        f"{texts.get('profile_field_birth_time', '🕒 Время рождения')}: {data.get('birth_time', 'Не указано')}",
        f"{texts.get('profile_field_birth_place', '📍 Место рождения')}: {data.get('birth_place', 'Не указано')}",
        f"{texts.get('profile_field_gender', '👤 Пол')}: {gender_display}",
        f"{zodiac_emoji} {texts.get('profile_field_zodiac', 'Знак зодиака')}: {zodiac_name}",
    ]
    if show_timezone:
        lines.append(f"{texts.get('profile_field_timezone', '🕒 Часовой пояс')}: UTC+{timezone}")
    return "\n".join(lines)


def format_numerology_parameters(data: dict) -> str:
    """Форматирует нумерологические данные для администратора (устаревшее, но используется)"""
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━",
        f"👤 Имя: {data.get('name', 'Не указано')}",
        f"⚥ Пол: {data.get('gender_display', 'Не указан')}",
        f"📅 Дата рождения: {data.get('birth_date', 'Не указана')}",
        f"🕒 Время рождения: {data.get('birth_time', 'Не указано')}",
        f"📍 Место рождения: {data.get('birth_place', 'Не указано')}",
        "━━━━━━━━━━━━━━━━━━━━━",
        f"🔢 Число жизненного пути: {data.get('life_path', '—')}",
        f"✨ Число экспрессии: {data.get('expression_number', '—')}",
        f"❤️ Число души: {data.get('soul_urge_number', '—')}",
        f"👤 Число личности: {data.get('personality_number', '—')}",
        f"📅 Личный год: {data.get('personal_year', '—')}",
        f"📆 Личный месяц: {data.get('personal_month', '—')}",
        f"📆 Личный день: {data.get('personal_day', '—')}",
        "━━━━━━━━━━━━━━━━━━━━━",
        f"🧩 Аркан дня (m1): {data.get('m1', '—')}",
        f"🧩 Аркан месяца (m2): {data.get('m2', '—')}",
        f"🧩 Аркан года (m3): {data.get('m3', '—')}",
        f"💞 Отношения (ОПВ): {data.get('opv', '—')}",
        f"🌟 Судьба (СЗ): {data.get('sz', '—')}",
        f"⚠️ Препятствие: {data.get('obstacle', '—')}",
        f"👥 Человек-предатель: {data.get('traitor', '—')}",
        f"😌 Зона комфорта: {data.get('comfort', '—')}",
        f"👨 Левая родовая: {data.get('v_left', '—')}",
        f"👩 Правая родовая: {data.get('v_right', '—')}",
        f"🌿 Карма левая: {data.get('v_bottom_left', '—')}",
        f"🌿 Карма правая: {data.get('v_bottom_right', '—')}",
        f"🧳 Багаж опыта: {data.get('v_left_side', '—')}",
        f"🕵️ Человек-предатель (правый бок): {data.get('v_right_side', '—')}",
        f"🪪 Внутренний паспорт: {data.get('v_top', '—')}",
    ]
    return "\n".join(lines)


def prepare_numerology_prompt_data(user_data: dict) -> dict:
    """Подготавливает данные для промпта нумерологии (используется для админов)"""
    calc = BaseCalculator()
    birth_date = user_data.get('birth_date')
    target_date = datetime.now().strftime('%d.%m.%Y')
    name = user_data.get('name', '')

    natal_calc = NatalCalculator(
        birth_date=birth_date,
        name=name,
        birth_time=user_data.get('birth_time'),
        birth_place=user_data.get('birth_place'),
        gender=user_data.get('gender')
    )
    matrix = natal_calc.calculate()

    prompt_data = {
        "name": name,
        "gender_display": "Мужчина" if user_data.get('gender') == 'M' else "Женщина",
        "birth_date": birth_date,
        "birth_time": user_data.get('birth_time', 'не указано'),
        "birth_place": user_data.get('birth_place', 'не указано'),
        "life_path": calc.calculate_life_path_number(birth_date),
        "expression_number": calc.calculate_expression_number(name) or "не рассчитано",
        "soul_urge_number": calc.calculate_soul_urge_number(name) or "не рассчитано",
        "personality_number": calc.calculate_personality_number(name) or "не рассчитано",
        "personal_year": calc.calculate_personal_year(birth_date, target_date),
        "personal_month": calc.calculate_personal_month(birth_date, target_date),
        "personal_day": calc.calculate_personal_day(birth_date, target_date),
        "pronoun": "он" if user_data.get('gender') == 'M' else "она",
        "possessive": "его" if user_data.get('gender') == 'M' else "её",
    }
    prompt_data.update(matrix)
    return prompt_data


def format_basic_compatibility_parameters(person1: dict, person2: dict, lang: str = 'ru') -> str:
    """Форматирует базовые данные для совместимости (не администратор)"""
    texts = TEXTS.get(lang, TEXTS['ru'])

    def person_text(person, num):
        if person.get('gender') == 'M':
            gender = texts.get('astro_gender_male', 'Male')
        else:
            gender = texts.get('astro_gender_female', 'Female')
        return texts['compatibility_confirm_person'].format(
            num=num,
            name=person.get('name', ''),
            gender=gender,
            birth_date=person.get('birth_date', ''),
            birth_time=person.get('birth_time', ''),
            birth_place=person.get('birth_place', '')
        )

    lines = [
        person_text(person1, 1),
        "",
        person_text(person2, 2),
    ]
    return "\n".join(lines)


# ---- НОВЫЕ ФУНКЦИИ ДЛЯ ВЫВОДА БАЗОВЫХ И ПОЛНЫХ ПАРАМЕТРОВ ----

def format_basic_astrology_parameters(user_data: dict, lang: str) -> str:
    """
    Возвращает строку с базовыми параметрами для вывода пользователю.
    Формат соответствует ТЗ:
      👤 Имя: ...
      ⚥ Пол: ...
      📅 Локальное время рождения: ...
      🕒 Часовой пояс места рождения: ...
      🕒 Время рождения UTC: ...
      📍 Место рождения: ...
      🌐 Координаты места рождения: ...
      ━━━━━━━━━━━━━━━━━━━━━
      ☀️ Солнце: ...
      🌙 Луна: ...
      ⬆️ Асцендент: ...
    """
    from bot.calculators.astrology_calculator import AstrologyCalculator
    texts = TEXTS.get(lang, TEXTS['ru'])

    calc = AstrologyCalculator(user_data)
    chart = calc._calculate_chart()
    angles = chart.get('angles', {})
    asc_deg = angles.get('ASC', 0.0)
    houses = chart.get('houses', [])
    asc_sign = houses[0]['sign'] if houses else 'unknown'
    from bot.utils.zodiac import get_zodiac_sign_localized
    asc_sign_local = get_zodiac_sign_localized(asc_sign, lang)

    planets = chart.get('planets', [])
    sun = next((p for p in planets if p['name'] == 'Sun'), {})
    moon = next((p for p in planets if p['name'] == 'Moon'), {})
    sun_sign = get_zodiac_sign_localized(sun.get('sign', 'unknown'), lang)
    moon_sign = get_zodiac_sign_localized(moon.get('sign', 'unknown'), lang)

    gender = user_data.get('gender', 'M')
    if lang == 'ru':
        gender_display = "Мужской" if gender == 'M' else "Женский" if gender == 'F' else "Не указан"
    else:
        gender_display = "Male" if gender == 'M' else "Female" if gender == 'F' else "Not specified"

    birth_date = user_data.get('birth_date', '')
    birth_time = user_data.get('birth_time', '')
    timezone = chart.get('timezone', '')
    utc_datetime = chart.get('utc_datetime', '')
    place = user_data.get('birth_place', '')
    location = chart.get('location', {})
    lat = location.get('lat', 0.0)
    lng = location.get('lng', 0.0)

    lines = [
        f"👤 {texts.get('astro_name', 'Имя')}: {user_data.get('name', '')}",
        f"⚥ {texts.get('astro_gender', 'Пол')}: {gender_display}",
        f"📅 {texts.get('astro_local_time', 'Локальное время')}: {birth_date} {birth_time}",
        f"🕒 {texts.get('astro_timezone', 'Часовой пояс')}: {timezone}",
        f"🕒 {texts.get('astro_utc_time', 'Время UTC')}: {utc_datetime}",
        f"📍 {texts.get('astro_place', 'Место')}: {place}",
        f"🌐 {texts.get('astro_coordinates', 'Координаты')}: {lat:.4f}, {lng:.4f}",
        "━━━━━━━━━━━━━━━━━━━━━",
        f"☀️ {texts.get('astro_sun', 'Солнце')}: {sun_sign}",
        f"🌙 {texts.get('astro_moon', 'Луна')}: {moon_sign}",
        f"⬆️ {texts.get('astro_ascendant', 'Асцендент')}: {asc_sign_local}",
    ]
    return "\n".join(lines)


def format_full_astrology_parameters(natal_data: dict, transit_data: dict = None, lang: str = 'ru') -> str:
    """
    Возвращает строку с полными параметрами для администратора.
    Использует данные из AstrologyDataBuilder (natal_data) и при необходимости transit_data.
    Локализована.
    """
    texts = TEXTS.get(lang, TEXTS['ru'])
    natal = natal_data.get('natal', {})
    lines = []

    # Планеты
    planets = natal.get('planets', [])
    if planets:
        lines.append(texts.get('astro_full_planets_header', '🪐 Планеты в знаках и домах:'))
        for p in planets:
            name = p.get('name_local', p.get('name', ''))
            sign = p.get('sign', '')
            degree = p.get('degree', 0.0)
            house = p.get('house', 0)
            lines.append(f"  • {name} в {sign} ({degree:.2f}°) в {house} доме")
        lines.append("")

    # Куспиды домов
    houses = natal.get('houses', [])
    if houses:
        lines.append(texts.get('astro_full_cusps_header', '🏠 Куспиды домов:'))
        for h in houses:
            number = h.get('number', 0)
            sign = h.get('cusp', '')
            degree = h.get('cusp_degree', 0.0)
            lines.append(f"Дом {number}: {sign} {degree:.2f}°")
        lines.append("")

    # Управители домов
    rulers = natal.get('house_rulers', [])
    if rulers:
        lines.append(texts.get('astro_full_house_rulers_header', '### Управители домов'))
        retro_symbol = texts.get('astro_retrograde_symbol', ' ℞')
        for r in rulers:
            house = r.get('house', 0)
            cusp = r.get('cusp', '')
            ruler = r.get('ruler', '')
            ruler_sign = r.get('ruler_sign', '')
            ruler_house = r.get('ruler_house', 0)
            retro = r.get('ruler_retrograde', False)
            retro_str = retro_symbol if retro else ''
            fmt = texts.get('astro_house_ruler_format', 'Дом {house}: {cusp} -> управитель {ruler} (в {ruler_sign}, {ruler_house} доме{retro})')
            lines.append(fmt.format(house=house, cusp=cusp, ruler=ruler, ruler_sign=ruler_sign, ruler_house=ruler_house, retro=retro_str))
        lines.append("")

    # Натальные аспекты
    aspects = natal.get('aspects', [])
    if aspects:
        lines.append(texts.get('astro_full_aspects_header', '🔮 Аспекты между планетами (мажорные, орбис ≤ 5°):'))
        for a in aspects:
            p1 = a.get('p1_name_local', a.get('p1', ''))
            p2 = a.get('p2_name_local', a.get('p2', ''))
            aspect = a.get('aspect_local', a.get('aspect', ''))
            orb = a.get('orb', 0.0)
            if orb <= 5.0:
                lines.append(f"  • {p1} {aspect} {p2} (орбис: {orb:.2f}°)")
        lines.append("")

    # Транзитные аспекты (если переданы)
    if transit_data:
        transit_aspects = transit_data.get('transit_aspects', [])
        if transit_aspects:
            lines.append(texts.get('astro_full_transits_header', '🌟 Транзитные аспекты на текущий момент:'))
            for a in transit_aspects:
                transit_planet = a.get('transit_planet', '')
                natal_planet = a.get('natal_planet', '')
                aspect = a.get('aspect', '')
                orb = a.get('orb', 0.0)
                lines.append(f"Transit {transit_planet} → Natal {natal_planet} → {aspect} → {orb:.2f}°")
            lines.append("")

        # Прогрессии (если есть)
        progressions = natal_data.get('progressions', {}).get('aspects', [])
        if progressions:
            lines.append(texts.get('astro_full_progressions_header', '🔄 Прогрессивные аспекты:'))
            for a in progressions:
                prog = a.get('progressed_planet', '')
                natal_pl = a.get('natal_planet', '')
                aspect = a.get('aspect', '')
                orb = a.get('orb', 0.0)
                lines.append(f"Progressed {prog} → Natal {natal_pl} → {aspect} → {orb:.2f}°")
            lines.append("")

    # Медицинские показатели — УДАЛЕНЫ

    return "\n".join(lines)

def format_natal_section(natal_data: dict, lang: str = 'ru') -> str:
    """
    Форматирует натальные данные для вставки в контекст гороскопа.
    Возвращает текст с разделами: планеты, углы, куспиды, управители, аспекты.
    """
    texts = TEXTS.get(lang, TEXTS['ru'])
    natal = natal_data.get('natal', {})
    lines = []

    # Планеты
    planets = natal.get('planets', [])
    if planets:
        lines.append("### Натальные планеты")
        lines.append("| Планета | Знак | Градус | Дом | Ретроградность |")
        lines.append("|---------|------|--------|-----|----------------|")
        for p in planets:
            name = p.get('name_local', p.get('name', ''))
            sign = p.get('sign', '')
            degree = p.get('degree', 0.0)
            house = p.get('house', 0)
            retro = 'Да' if p.get('retrograde', False) else 'Нет'
            lines.append(f"| {name} | {sign} | {degree:.2f}° | {house} | {retro} |")
        lines.append("")

    # Углы
    angles = natal.get('angles', {})
    if angles:
        lines.append("### Углы")
        asc = angles.get('ASC', 0.0)
        mc = angles.get('MC', 0.0)
        dsc = angles.get('DSC', 0.0)
        ic = angles.get('IC', 0.0)
        lines.append(f"ASC: {asc:.2f}°")
        lines.append(f"MC: {mc:.2f}°")
        lines.append(f"DSC: {dsc:.2f}°")
        lines.append(f"IC: {ic:.2f}°")
        lines.append("")

    # Куспиды домов
    houses = natal.get('houses', [])
    if houses:
        lines.append("### Куспиды домов")
        for h in houses:
            number = h.get('number', 0)
            sign = h.get('cusp', '')
            degree = h.get('cusp_degree', 0.0)
            lines.append(f"Дом {number}: {sign} {degree:.2f}°")
        lines.append("")

    # Управители домов
    rulers = natal.get('house_rulers', [])
    if rulers:
        lines.append("### Управители домов")
        for r in rulers:
            house = r.get('house', 0)
            cusp = r.get('cusp', '')
            ruler = r.get('ruler', '')
            ruler_sign = r.get('ruler_sign', '')
            ruler_house = r.get('ruler_house', 0)
            retro = ' ℞' if r.get('ruler_retrograde', False) else ''
            lines.append(f"Дом {house}: {cusp} -> управитель {ruler} (в {ruler_sign}, {ruler_house} доме{retro})")
        lines.append("")

    # Натальные аспекты (выводим только с орбом <= 3° для компактности)
    aspects = natal.get('aspects', [])
    if aspects:
        lines.append("### Натальные аспекты")
        aspects_sorted = sorted(aspects, key=lambda x: x.get('orb', 10.0))
        for a in aspects_sorted:
            orb = a.get('orb', 0.0)
            if orb > 3.0:
                continue
            p1 = a.get('p1_name_local', a.get('p1', ''))
            p2 = a.get('p2_name_local', a.get('p2', ''))
            aspect = a.get('aspect_local', a.get('aspect', ''))
            lines.append(f"{p1} {aspect} {p2}, орб {orb:.2f}°")
        lines.append("")

    return "\n".join(lines)