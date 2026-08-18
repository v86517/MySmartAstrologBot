import logging
import os
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

from bot.utils.helpers import get_text
from bot.keyboards.keyboards import (
    get_expert_keyboard,
    get_main_menu_button,
)
from bot.db import get_user_data, get_user_language

logger = logging.getLogger(__name__)
router = Router()


async def expert_request_func(message: Message):
    """Обработчик запроса эксперта (экспортируется)"""
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    username = message.from_user.username or "Не указан"
    first_name = message.from_user.first_name or "Не указано"

    user_data_from_db = await get_user_data(user_id)

    user_info = ""
    if user_data_from_db:
        user_info = (
            f"\n👤 Имя: {user_data_from_db.get('name', 'Не указано')}"
            f"\n📅 Дата рождения: {user_data_from_db.get('birth_date', 'Не указана')}"
            f"\n🕒 Время рождения: {user_data_from_db.get('birth_time', 'Не указано')}"
            f"\n📍 Место рождения: {user_data_from_db.get('birth_place', 'Не указано')}"
            f"\n♈ Знак зодиака: {user_data_from_db.get('zodiac', 'Неизвестно')}"
        )

    expert_text = await get_text(user_id, 'expert_intro')

    await message.answer(
        expert_text,
        reply_markup=get_expert_keyboard(lang)
    )


@router.callback_query(F.data == "expert_request")
async def send_expert_request(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    username = callback.from_user.username or "Не указан"
    first_name = callback.from_user.first_name or "Не указано"

    user_data_from_db = await get_user_data(user_id)

    user_info = ""
    if user_data_from_db:
        user_info = (
            f"\n👤 Имя: {user_data_from_db.get('name', 'Не указано')}"
            f"\n📅 Дата рождения: {user_data_from_db.get('birth_date', 'Не указана')}"
            f"\n🕒 Время рождения: {user_data_from_db.get('birth_time', 'Не указано')}"
            f"\n📍 Место рождения: {user_data_from_db.get('birth_place', 'Не указано')}"
            f"\n♈ Знак зодиака: {user_data_from_db.get('zodiac', 'Неизвестно')}"
        )

    await callback.message.answer(
        await get_text(user_id, 'expert_sent'),
        reply_markup=get_main_menu_button(lang)
    )

    expert_chat_id = os.getenv('EXPERT_CHAT_ID')
    logger.info(f"🔍 EXPERT_CHAT_ID из .env: '{expert_chat_id}'")
    if expert_chat_id:
        try:
            expert_message = (
                f"📩 НОВАЯ ЗАЯВКА НА КОНСУЛЬТАЦИЮ!\n\n"
                f"👤 Пользователь: @{username}\n"
                f"📛 Имя: {first_name}\n"
                f"🆔 ID: {user_id}{user_info}\n\n"
                f"💰 Услуга: Экспертный разбор (5000 ₽)\n"
                f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            )
            # Используем callback.bot для отправки
            await callback.bot.send_message(expert_chat_id, expert_message)
            logger.info(f"✅ Сообщение эксперту отправлено на {expert_chat_id}")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки эксперту: {e}")
    else:
        logger.warning("⚠️ EXPERT_CHAT_ID не задан в .env, сообщение эксперту не отправлено")