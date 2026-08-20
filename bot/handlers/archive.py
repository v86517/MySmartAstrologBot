# bot/handlers/archive.py
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.utils.helpers import get_text
from bot.utils.messaging import send_long_message
from bot.keyboards.keyboards import (
    get_main_menu,
    get_subscription_keyboard,
    get_archive_keyboard,
    get_main_menu_button,
)
from bot.db import (
    get_user_archive,
    get_archive_message,
    get_user_language,
    check_subscription_db,
)

logger = logging.getLogger(__name__)
router = Router()


async def show_archive_func(message: Message):
    """Показать архив (экспортируется для вызова из других модулей)"""
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    is_subscribed = await check_subscription_db(user_id)

    messages = await get_user_archive(user_id, limit=50)

    if not messages:
        await message.answer(
            await get_text(user_id, 'archive_empty'),
            reply_markup=get_main_menu(lang)
        )
        return

    if not is_subscribed:
        allowed_types = ['numerology', 'astrology']
        messages = [msg for msg in messages if msg.message_type in allowed_types]

        if not messages:
            await message.answer(
                await get_text(user_id, 'archive_no_premium'),
                reply_markup=get_subscription_keyboard(lang)
            )
            return

    type_display_map = {
        'horoscope': await get_text(user_id, 'type_horoscope'),
        'compatibility': await get_text(user_id, 'type_compatibility'),
        'numerology': await get_text(user_id, 'type_numerology'),
        'astrology': await get_text(user_id, 'type_astrology'),
    }

    type_emoji_map = {
        'horoscope': '🔮',
        'compatibility': '💕',
        'numerology': '🔢',
        'astrology': '🌙',
    }

    archive_text = await get_text(user_id, 'archive_title')

    for i, msg in enumerate(messages, 1):
        date_str = msg.date.strftime("%d.%m.%Y %H:%M")
        emoji = type_emoji_map.get(msg.message_type, '📝')
        type_name = type_display_map.get(msg.message_type, msg.message_type)

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        preview = preview.replace('\n', ' ')

        template = await get_text(user_id, 'archive_item')
        archive_text += template.format(
            i=i,
            emoji=emoji,
            type=type_name,
            date=date_str,
            preview=preview
        )

    archive_text += await get_text(user_id, 'archive_footer')

    await message.answer(
        archive_text,
        reply_markup=get_archive_keyboard(messages, lang)
    )


@router.callback_query(F.data == "archive_refresh")
async def refresh_archive(callback: CallbackQuery):
    await callback.answer()
    await callback.message.delete()

    class FakeMessage:
        def __init__(self, callback):
            self.from_user = callback.from_user
            self.chat = callback.message.chat
            self.answer = callback.message.answer

    fake_msg = FakeMessage(callback)
    await show_archive_func(fake_msg)


@router.callback_query(F.data.startswith("archive_"))
async def show_archive_message(callback: CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)

    try:
        message_id = int(callback.data.replace("archive_", ""))
    except ValueError:
        await callback.message.answer(await get_text(user_id, 'error_not_found'))
        return

    try:
        msg = await get_archive_message(message_id, callback.from_user.id)

        if not msg:
            await callback.message.answer(
                await get_text(user_id, 'error_not_found'),
                reply_markup=get_main_menu(lang)
            )
            return

        type_emoji = {
            'horoscope': '🔮',
            'compatibility': '💕',
            'natal_chart': '🌌',
            'numerology': '🔢',
            'astrology': '🌙',
        }

        type_display = {
            'horoscope': await get_text(user_id, 'type_horoscope'),
            'compatibility': await get_text(user_id, 'type_compatibility'),
            'natal_chart': await get_text(user_id, 'type_horoscope'),
            'numerology': await get_text(user_id, 'type_numerology'),
            'astrology': await get_text(user_id, 'type_astrology'),
        }

        emoji = type_emoji.get(msg.message_type, '📝')
        type_name = type_display.get(msg.message_type, msg.message_type)

        template = await get_text(user_id, 'archive_message_header')
        full_text = template.format(
            emoji=emoji,
            type=type_name,
            date=msg.date.strftime('%d.%m.%Y %H:%M'),
            content=msg.content
        )

        await send_long_message(callback.message, full_text)

    except Exception as e:
        await callback.message.answer(
            f"❌ Ошибка: {str(e)}",
            reply_markup=get_main_menu(lang)
        )