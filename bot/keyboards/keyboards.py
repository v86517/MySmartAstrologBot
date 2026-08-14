from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from core.models import UserMessage
from bot.locales import TEXTS


def get_main_menu(lang: str = 'ru'):
    """Главное меню (ReplyKeyboard) — локализованное"""
    builder = ReplyKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.add(KeyboardButton(text=texts['menu_horoscope']))
    builder.add(KeyboardButton(text=texts['menu_compatibility']))
    builder.add(KeyboardButton(text=texts['menu_numerology']))
    builder.add(KeyboardButton(text=texts['menu_astrology']))
    builder.add(KeyboardButton(text=texts['menu_premium']))
    builder.add(KeyboardButton(text=texts['menu_expert']))
    builder.add(KeyboardButton(text=texts['menu_archive']))
    builder.add(KeyboardButton(text=texts['menu_profile']))
    builder.add(KeyboardButton(text=texts['menu_language']))
    builder.adjust(2, 2, 2, 3)
    return builder.as_markup(resize_keyboard=True)


def get_zodiac_keyboard():
    """Клавиатура для выбора знака зодиака (без локализации — только эмодзи и названия)"""
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
    """Клавиатура для выбора знака зодиака (человек 2) — без локализации"""
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


def get_cancel_keyboard(lang: str = 'ru'):
    """Кнопка отмены"""
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_cancel'], callback_data="cancel")
    return builder.as_markup()


def get_compatibility_keyboard(lang: str = 'ru'):
    """Кнопки для совместимости"""
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_use_my_data'], callback_data="use_my_data")
    builder.button(text=texts['kb_fill_new'], callback_data="fill_person1")
    builder.button(text=texts['kb_cancel'], callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_confirm_keyboard(lang: str = 'ru'):
    """Кнопки подтверждения данных"""
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_confirm'], callback_data="confirm_data")
    builder.button(text=texts['kb_edit'], callback_data="edit_person1")
    builder.button(text=texts['kb_cancel'], callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_continue_keyboard(lang: str = 'ru'):
    """Кнопка продолжения"""
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_continue'], callback_data="continue_to_person2")
    builder.button(text=texts['kb_edit'], callback_data="edit_person1")
    builder.button(text=texts['kb_cancel'], callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_natal_payment_keyboard(lang: str = 'ru'):
    """Клавиатура для оплаты натальной карты (устаревшая, но оставим)"""
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_pay_888'], callback_data="natal_pay")
    builder.button(text=texts['kb_cancel'], callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_natal_confirm_keyboard(lang: str = 'ru'):
    """Клавиатура для подтверждения данных натальной карты (устаревшая)"""
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_get_card'], callback_data="natal_confirm")
    builder.button(text=texts['kb_edit_data'], callback_data="edit_natal_data")
    builder.button(text=texts['kb_cancel'], callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_natal_use_data_keyboard(lang: str = 'ru'):
    """Клавиатура для выбора использования данных (устаревшая)"""
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_use_my_data'], callback_data="natal_use_my_data")
    builder.button(text=texts['kb_fill_new'], callback_data="natal_fill_new_data")
    builder.button(text=texts['kb_cancel'], callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_numerology_payment_keyboard(lang: str = 'ru'):
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_pay_888'], callback_data="numerology_pay")
    #builder.button(text=texts['kb_cancel'], callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_numerology_confirm_keyboard(lang: str = 'ru'):
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_get_analysis'], callback_data="numerology_confirm")
    builder.button(text=texts['kb_edit_data'], callback_data="edit_numerology_data")
    builder.button(text=texts['kb_cancel'], callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_numerology_use_data_keyboard(lang: str = 'ru'):
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_use_my_data'], callback_data="numerology_use_my_data")
    builder.button(text=texts['kb_fill_new'], callback_data="numerology_fill_new_data")
    builder.button(text=texts['kb_cancel'], callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_astrology_payment_keyboard(lang: str = 'ru'):
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_pay_999'], callback_data="astrology_pay")
    #builder.button(text=texts['kb_cancel'], callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_astrology_confirm_keyboard(lang: str = 'ru'):
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_get_analysis'], callback_data="astrology_confirm")
    builder.button(text=texts['kb_edit_data'], callback_data="edit_astrology_data")
    builder.button(text=texts['kb_cancel'], callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_astrology_use_data_keyboard(lang: str = 'ru'):
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_use_my_data'], callback_data="astrology_use_my_data")
    builder.button(text=texts['kb_fill_new'], callback_data="astrology_fill_new_data")
    builder.button(text=texts['kb_cancel'], callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_expert_keyboard(lang: str = 'ru'):
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_send_request'], callback_data="expert_request")
    #builder.button(text=texts['kb_cancel'], callback_data="cancel_expert")   # <-- было cancel
    builder.adjust(1)
    return builder.as_markup()


def get_subscription_keyboard(lang: str = 'ru'):
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_pay_333'], callback_data="subscribe_pay")
    #builder.button(text=texts['kb_cancel'], callback_data="close_subscription")
    builder.adjust(1)
    return builder.as_markup()


def get_subscription_active_keyboard(lang: str = 'ru'):
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_extend'], callback_data="subscribe_extend")
    builder.button(text=texts['kb_cancel'], callback_data="close_subscription")
    builder.adjust(1)
    return builder.as_markup()


def get_save_data_keyboard(lang: str = 'ru'):
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_save'], callback_data="save_data")
    builder.button(text=texts['kb_dont_save'], callback_data="dont_save_data")
    builder.adjust(1)
    return builder.as_markup()


def get_archive_keyboard(messages, lang: str = 'ru'):
    """Клавиатура для архива с кнопками на каждое сообщение"""
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])

    type_emoji = {
        'horoscope': '🔮',
        'compatibility': '💕',
        'natal_chart': '🌌',
        'numerology': '🔢',
        'astrology': '🌙',
    }
    type_display = {
        'horoscope': texts['type_horoscope'],
        'compatibility': texts['type_compatibility'],
        'natal_chart': texts['type_horoscope'],  # если используется
        'numerology': texts['type_numerology'],
        'astrology': texts['type_astrology'],
    }

    for msg in messages:
        emoji = type_emoji.get(msg.message_type, '📝')
        type_name = type_display.get(msg.message_type, msg.message_type)
        date_str = msg.date.strftime("%d.%m")
        button_text = f"{emoji} {type_name} ({date_str})"
        builder.button(text=button_text, callback_data=f"archive_{msg.id}")

    builder.button(text=texts['kb_refresh'], callback_data="archive_refresh")
    builder.button(text=texts['kb_main_menu'], callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


def get_profile_keyboard(lang: str = 'ru'):
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_edit_profile'], callback_data="edit_profile")
    builder.button(text=texts['kb_change_timezone'], callback_data="edit_timezone")
    builder.button(text=texts['kb_cancel_subscription'], callback_data="cancel_subscription")
    builder.button(text=texts['kb_support'], callback_data="support")
    builder.adjust(1)
    return builder.as_markup()


def get_support_keyboard(support_url: str, lang: str = 'ru'):
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_write_support'], url=support_url)
    builder.button(text=texts['kb_cancel'], callback_data="back_to_profile")
    builder.adjust(1)
    return builder.as_markup()


def get_payment_url_keyboard(url: str, lang: str = 'ru'):
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_go_pay'], url=url)
    #builder.button(text=texts['kb_cancel'], callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_skip_keyboard(lang: str = 'ru'):
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_skip'], callback_data="skip_edit")
    builder.button(text=texts['kb_cancel'], callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_timezone_keyboard(lang: str = 'ru'):
    builder = InlineKeyboardBuilder()
    for i in range(1, 13):
        builder.button(text=f"UTC+{i}", callback_data=f"tz_{i}")
    # кнопка "Отмена" удалена
    builder.adjust(3, 3, 3, 3)
    return builder.as_markup()


def get_after_timezone_keyboard(lang: str = 'ru'):
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_main_menu'], callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


def get_after_save_keyboard(lang: str = 'ru'):
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_cancel'], callback_data="main_menu")
    return builder.as_markup()


def get_subscription_promo_keyboard(lang: str = 'ru'):
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_pay_333'], callback_data="subscribe_pay")
    return builder.as_markup()


def get_subscription_payment_keyboard(url: str, lang: str = 'ru'):
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_go_pay'], url=url)
    #builder.button(text=texts['kb_cancel'], callback_data="close_subscription")
    builder.adjust(1)
    return builder.as_markup()


def get_fill_profile_keyboard(lang: str = 'ru'):
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_fill_and_save'], callback_data="fill_and_save")
    return builder.as_markup()


def get_horoscope_confirm_keyboard(lang: str = 'ru'):
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_get_horoscope'], callback_data="confirm_horoscope")
    builder.button(text=texts['kb_cancel'], callback_data="cancel_horoscope")
    builder.adjust(1)
    return builder.as_markup()


def get_language_keyboard():
    """Клавиатура выбора языка (без перевода)"""
    builder = InlineKeyboardBuilder()
    builder.button(text="English", callback_data="lang_en")
    builder.button(text="Русский", callback_data="lang_ru")
    builder.adjust(2)
    return builder.as_markup()


def get_main_menu_button(lang: str = 'ru'):
    """Инлайн-кнопка для возврата в главное меню."""
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.get('main_menu_button', '🏠 Главное меню'), callback_data="main_menu")
    return builder.as_markup()


def get_compatibility_confirm_keyboard(lang: str = 'ru'):
    builder = InlineKeyboardBuilder()
    texts = TEXTS.get(lang, TEXTS['ru'])
    builder.button(text=texts['kb_confirm_compatibility'], callback_data="confirm_compatibility")
    builder.button(text=texts['kb_cancel_compatibility'], callback_data="cancel_compatibility")
    builder.adjust(1)
    return builder.as_markup()