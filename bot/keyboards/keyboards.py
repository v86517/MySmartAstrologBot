from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
import os
import django

# Настройка Django перед импортом моделей
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from core.models import UserMessage


def get_main_menu():
    """Главное меню в стиле Premium Dark Mystic"""
    builder = ReplyKeyboardBuilder()

    builder.add(KeyboardButton(text="🔮 Гороскоп на сегодня"))
    builder.add(KeyboardButton(text="💕 Совместимость"))
    builder.add(KeyboardButton(text="🌌 Натальная карта"))
    builder.add(KeyboardButton(text="⭐ Подписка"))
    builder.add(KeyboardButton(text="👤 Эксперт"))
    builder.add(KeyboardButton(text="📚 Архив"))
    builder.add(KeyboardButton(text="⚙️ Мой профиль"))

    builder.adjust(2, 2, 3)
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
    builder.button(text="💳 Оплатить 999 ₽", callback_data="natal_pay")
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
    builder.button(text="⭐ Оформить подписку 299 ₽", callback_data="subscribe_pay")
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
    """Клавиатура для профиля"""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отменить подписку", callback_data="cancel_subscription")
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()

def get_payment_url_keyboard(url):
    """Клавиатура со ссылкой на оплату"""
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Перейти к оплате", url=url)
    builder.button(text="🔄 Проверить оплату", callback_data="check_payment")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()