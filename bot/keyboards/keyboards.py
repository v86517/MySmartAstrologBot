from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
import os
import django

# Настройка Django перед импортом моделей
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from core.models import UserMessage


def get_main_menu():
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="🔮 Гороскоп на сегодня"))
    builder.add(KeyboardButton(text="💕 Совместимость"))
    builder.add(KeyboardButton(text="🔢 Нумерология"))                 # изменено
    builder.add(KeyboardButton(text="🌌 Натальная карта"))              # изменено (было Астрология)
    builder.add(KeyboardButton(text="⭐ Premium"))                      # изменено (было Подписка)
    builder.add(KeyboardButton(text="👩‍🏫 Личный астролог"))            # изменено (было Эксперт)
    builder.add(KeyboardButton(text="📖 Мои прогнозы"))                 # изменено (было Архив)
    builder.add(KeyboardButton(text="👤 Мой профиль"))                 # изменено (было ⚙️ Мой профиль)
    builder.adjust(2, 2, 2, 2)  # 4 ряда по 2 кнопки
    return builder.as_markup(resize_keyboard=True)


def get_zodiac_keyboard():
    """Клавиатура для выбора знака зодиака"""
    builder = InlineKeyboardBuilder()

    zodiacs = [
        ("♈ Овен", "Овен"),
        ("♉ Телец", "Телец"),
        ("♊ Близнецы", "Близнецы"),
        ("♋ Рак", "Рак"),
        ("♌ Лев", "Лев"),
        ("♍ Дева", "Дева"),
        ("♎ Весы", "Весы"),
        ("♏ Скорпион", "Скорпион"),
        ("♐ Стрелец", "Стрелец"),
        ("♑ Козерог", "Козерог"),
        ("♒ Водолей", "Водолей"),
        ("♓ Рыбы", "Рыбы"),
    ]

    for label, sign in zodiacs:
        builder.button(text=label, callback_data=f"zodiac_{sign}")

    builder.adjust(3, 3, 3, 3)
    return builder.as_markup()


def get_zodiac_keyboard_person2():
    """Клавиатура для выбора знака зодиака (человек 2)"""
    builder = InlineKeyboardBuilder()

    zodiacs = [
        ("♈ Овен", "Овен"),
        ("♉ Телец", "Телец"),
        ("♊ Близнецы", "Близнецы"),
        ("♋ Рак", "Рак"),
        ("♌ Лев", "Лев"),
        ("♍ Дева", "Дева"),
        ("♎ Весы", "Весы"),
        ("♏ Скорпион", "Скорпион"),
        ("♐ Стрелец", "Стрелец"),
        ("♑ Козерог", "Козерог"),
        ("♒ Водолей", "Водолей"),
        ("♓ Рыбы", "Рыбы"),
    ]

    for label, sign in zodiacs:
        builder.button(text=label, callback_data=f"comp_zodiac2_{sign}")

    builder.adjust(3, 3, 3, 3)
    return builder.as_markup()


def get_cancel_keyboard():
    """Кнопка отмены"""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="cancel")
    return builder.as_markup()


def get_compatibility_keyboard():
    """Кнопки для совместимости"""
    builder = InlineKeyboardBuilder()
    builder.button(text="👤 Использовать мои данные", callback_data="use_my_data")
    builder.button(text="✏️ Заполнить заново", callback_data="fill_person1")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_confirm_keyboard():
    """Кнопки подтверждения данных"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, всё верно", callback_data="confirm_data")
    builder.button(text="✏️ Изменить", callback_data="edit_person1")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_continue_keyboard():
    """Кнопка продолжения"""
    builder = InlineKeyboardBuilder()
    builder.button(text="➡️ Продолжить", callback_data="continue_to_person2")
    builder.button(text="✏️ Изменить", callback_data="edit_person1")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_natal_payment_keyboard():
    """Клавиатура для оплаты натальной карты"""
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Оплатить 888 ₽", callback_data="natal_pay")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_natal_confirm_keyboard():
    """Клавиатура для подтверждения данных натальной карты"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Получить карту", callback_data="natal_confirm")
    builder.button(text="✏️ Изменить данные", callback_data="edit_natal_data")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_natal_use_data_keyboard():
    """Клавиатура для выбора использования данных"""
    builder = InlineKeyboardBuilder()
    builder.button(text="👤 Использовать мои данные", callback_data="natal_use_my_data")
    builder.button(text="✏️ Заполнить другие данные", callback_data="natal_fill_new_data")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_numerology_payment_keyboard():
    """Клавиатура для оплаты нумерологии (888 ₽)"""
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Оплатить 888 ₽", callback_data="numerology_pay")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()

def get_numerology_confirm_keyboard():
    """Клавиатура для подтверждения данных нумерологии"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Получить разбор", callback_data="numerology_confirm")
    builder.button(text="✏️ Изменить данные", callback_data="edit_numerology_data")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()

def get_numerology_use_data_keyboard():
    """Клавиатура для выбора использования сохранённых данных (нумерология)"""
    builder = InlineKeyboardBuilder()
    builder.button(text="👤 Использовать мои данные", callback_data="numerology_use_my_data")
    builder.button(text="✏️ Заполнить другие данные", callback_data="numerology_fill_new_data")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_astrology_payment_keyboard():
    """Клавиатура для оплаты астрологии (999 ₽)"""
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Оплатить 999 ₽", callback_data="astrology_pay")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()

def get_astrology_confirm_keyboard():
    """Клавиатура для подтверждения данных астрологии"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Получить разбор", callback_data="astrology_confirm")
    builder.button(text="✏️ Изменить данные", callback_data="edit_astrology_data")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()

def get_astrology_use_data_keyboard():
    """Клавиатура для выбора использования сохранённых данных (астрология)"""
    builder = InlineKeyboardBuilder()
    builder.button(text="👤 Использовать мои данные", callback_data="astrology_use_my_data")
    builder.button(text="✏️ Заполнить другие данные", callback_data="astrology_fill_new_data")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_expert_keyboard():
    """Клавиатура для эксперта"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📩 Отправить заявку эксперту", callback_data="expert_request")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_subscription_keyboard():
    """Клавиатура для подписки"""
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐ Оформить подписку 333 ₽", callback_data="subscribe_pay")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_subscription_active_keyboard():
    """Клавиатура для активной подписки"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Продлить подписку", callback_data="subscribe_extend")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_archive_keyboard(messages):
    """Клавиатура для архива с кнопками на каждое сообщение"""
    builder = InlineKeyboardBuilder()

    type_emoji = {
        'horoscope': '🔮',
        'compatibility': '💕',
        'natal_chart': '🌌'
    }

    type_display = {
        'horoscope': 'Гороскоп',
        'compatibility': 'Совместимость',
        'natal_chart': 'Натальная карта'
    }

    for msg in messages:
        emoji = type_emoji.get(msg.message_type, '📝')
        type_name = type_display.get(msg.message_type, msg.message_type)
        date_str = msg.date.strftime("%d.%m")

        button_text = f"{emoji} {type_name} ({date_str})"

        builder.button(
            text=button_text,
            callback_data=f"archive_{msg.id}"
        )

    builder.button(text="🔄 Обновить", callback_data="archive_refresh")
    builder.button(text="🏠 Главное меню", callback_data="main_menu")

    builder.adjust(1)

    return builder.as_markup()


def get_profile_keyboard():
    """Клавиатура для профиля (изменить данные + отменить подписку)"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Изменить данные", callback_data="edit_profile")
    builder.button(text="🕒 Сменить часовой пояс", callback_data="edit_timezone")
    builder.button(text="❌ Отменить подписку", callback_data="cancel_subscription")
    builder.adjust(1)
    return builder.as_markup()


def get_payment_url_keyboard(url: str) -> InlineKeyboardMarkup:
    """Клавиатура со ссылкой на оплату"""
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Перейти к оплате", url=url)
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_skip_keyboard():
    """Клавиатура с кнопкой 'Пропустить' для редактирования"""
    builder = InlineKeyboardBuilder()
    builder.button(text="⏩ Пропустить", callback_data="skip_edit")
    return builder.as_markup()


def get_timezone_keyboard():
    """Клавиатура с выбором часового пояса UTC+1..UTC+12"""
    builder = InlineKeyboardBuilder()
    for i in range(1, 13):
        builder.button(text=f"UTC+{i}", callback_data=f"tz_{i}")
    builder.adjust(3, 3, 3, 3)  # 4 ряда по 3 кнопки
    return builder.as_markup()

def get_after_timezone_keyboard():
    """Клавиатура после выбора часового пояса"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()

def get_subscription_promo_keyboard():
    """Клавиатура с одной кнопкой для оформления подписки (используется в промо)"""
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐ Оформить подписку 333 ₽", callback_data="subscribe_pay")
    return builder.as_markup()